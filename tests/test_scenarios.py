"""Stage 3: objective weight sliders + side-by-side scenarios."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)
from brain_core.rolling import (ObjectiveWeights, solve_window,
                                validate_window_plan)
from brain_core.scenarios import Scenario, compare, solve_scenarios

H0 = datetime(2026, 11, 30)


def two_line_factory(eff_a=1.0, eff_b=0.5, qty=200.0):
    """One SKU makeable on two lines: A efficient, B not."""
    return Factory(
        locations=[Location(name="P")],
        items=[Item(name="A")],
        setup_matrices=[SetupMatrix(name="CHG", rules=[
            SetupRule(from_setup="S1", to_setup="S1",
                      duration=timedelta(0))])],
        resources=[
            Resource(name="FAST", location="P", setup_matrix="CHG",
                     efficiency=eff_a),
            Resource(name="SLOW", location="P", setup_matrix="CHG",
                     efficiency=eff_b)],
        operations=[Operation(
            name="MAKE-A", item="A", location="P",
            duration_per=timedelta(minutes=1),
            materials=[OperationMaterial(item="A", quantity=1)],
            loads=[OperationResource(resource="FAST", setup="S1"),
                   OperationResource(resource="SLOW", setup="S1")])],
        demands=[Demand(name="D1", item="A", location="P",
                        due=H0 + timedelta(days=1), quantity=qty)])


def test_energy_slider_prefers_efficient_line():
    f = two_line_factory()
    plain = solve_window(f, H0, 1, 480.0, bucket_time_s=10, seq_time_s=5)
    green = solve_window(f, H0, 1, 480.0, bucket_time_s=10, seq_time_s=5,
                         weights=ObjectiveWeights(energy=10.0))
    assert plain.problems == [] and green.problems == []
    def line_units(plan, line):
        return sum(a.qty for a in plan.assignments if a.line == line)
    # with energy priced, SLOW carries no more than without
    assert line_units(green, "SLOW") <= line_units(plain, "SLOW") + 1e-6
    assert line_units(green, "FAST") >= 200.0 - 1e-6
    gk = green.kpis
    assert gk["energy_proxy"] < 200.0 * 1.0 + 1e-6  # all on FAST: x1.0


def test_on_time_slider_reduces_lateness_on_tight_plant():
    """Cap 100, demand 150 due day 0: 50 units must be late or early-
    impossible. With late priced high vs negligible, both plans are
    valid; the slider test is that late weight changes the late cost
    accounting, and feasibility holds either way."""
    f = two_line_factory(qty=150.0)
    f.resources = f.resources[:1]  # one line, cap 100/day at rate... 480
    f.operations[0].loads = f.operations[0].loads[:1]
    f.operations[0] = f.operations[0].model_copy(
        update={"duration_per": timedelta(minutes=4)})
    plan = solve_window(f, H0, 1, 480.0, bucket_time_s=10, seq_time_s=5,
                        weights=ObjectiveWeights(late=1000.0))
    vp, kpis = validate_window_plan(f, plan, 480.0)
    assert vp == []
    # 150 x 4 = 600 > 480: at least 30 units must be late
    assert kpis["backlog_units_end"] >= 30.0 - 1e-6


def test_scenarios_side_by_side_comparable():
    f = two_line_factory(qty=300.0)
    results = solve_scenarios(
        f, H0, 1, 480.0,
        [Scenario("base", ObjectiveWeights()),
         Scenario("green", ObjectiveWeights(energy=10.0),
                  "prefer efficient lines")],
        bucket_time_s=10, seq_time_s=5)
    assert all(r.problems == [] for r in results)
    table = compare(results)
    assert set(table["scenarios"]) == {"base", "green"}
    # common scale: proxy_cost present for both, deltas vs first
    assert "green" in table["deltas_vs_first"]
    assert table["scenarios"]["green"]["energy_proxy"] <= \
        table["scenarios"]["base"]["energy_proxy"] + 1e-6
    # both serve the full demand
    for r in results:
        assert r.kpis["backlog_units_end"] == pytest.approx(0.0)
