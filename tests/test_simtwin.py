"""Stage 4, slice 3: the simulation twin's execution honesty.

Scores are measured by executing plans through the validator's own
stock walk: a lost line-day shows up as exactly its lost production,
early production measurably absorbs a disruption, and a fixed seed
reproduces the score exactly.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource)
from brain_core.rolling.two_level import LotAssignment, WindowPlan
from brain_core.simtwin import Disruption, execute, robustness_score

H0 = datetime(2026, 11, 30)


def _factory(qty=100.0, due_days=3):
    return Factory(
        locations=[Location(name="P")],
        items=[Item(name="A")],
        resources=[Resource(name="L1", location="P")],
        operations=[Operation(
            name="make-A", item="A", location="P",
            duration_per=timedelta(minutes=1),
            materials=[OperationMaterial(item="A", quantity=1)],
            loads=[OperationResource(resource="L1", setup="sA")])],
        demands=[Demand(name="D1", item="A",
                        due=H0 + timedelta(days=due_days),
                        quantity=qty)])


def _plan(pairs, days=4):
    return WindowPlan(horizon_start=H0, days=days,
                      assignments=[LotAssignment(line=l, day=d, sku=s,
                                                 qty=q, seq_pos=0,
                                                 chg_from_prev_min=0.0)
                                   for (l, d, s, q) in pairs],
                      bucket=None, seq_status="test")


def test_nominal_execution_matches_validator_walk():
    f = _factory()
    plan = _plan([("L1", 2, "A", 100.0)])
    out = execute(f, plan, Disruption())
    assert out["backlog_units_end"] == pytest.approx(0.0)
    assert out["early_unit_days"] == pytest.approx(0.0)


def test_downed_line_day_loses_exactly_its_production():
    f = _factory()
    plan = _plan([("L1", 2, "A", 100.0)])
    out = execute(f, plan, Disruption(down=(("L1", 2),)))
    assert out["backlog_units_end"] == pytest.approx(100.0)


def test_rate_slowdown_scales_production():
    f = _factory()
    plan = _plan([("L1", 2, "A", 100.0)])
    out = execute(f, plan, Disruption(rate_scale=(("L1", 0.9),)))
    assert out["backlog_units_end"] == pytest.approx(10.0)


def test_demand_jitter_scales_demand():
    f = _factory()
    plan = _plan([("L1", 2, "A", 100.0)])
    out = execute(f, plan, Disruption(demand_scale=(("A", 1.2),)))
    assert out["backlog_units_end"] == pytest.approx(20.0)


def test_early_production_absorbs_a_late_disruption():
    """Same factory: just-in-time plan vs one-day-early plan. Under
    L1 down on day 2, the early plan loses nothing."""
    f = _factory()
    jit = _plan([("L1", 2, "A", 100.0)])
    early = _plan([("L1", 1, "A", 100.0)])
    down = Disruption(down=(("L1", 2),))
    assert execute(f, jit, down)["backlog_units_end"] == pytest.approx(100.0)
    assert execute(f, early, down)["backlog_units_end"] == pytest.approx(0.0)


def test_robustness_score_is_reproducible_and_records_params():
    f = _factory()
    plan = _plan([("L1", 2, "A", 100.0)])
    s1 = robustness_score(f, plan, n_scenarios=10, seed=7)
    s2 = robustness_score(f, plan, n_scenarios=10, seed=7)
    assert s1 == s2
    assert s1["n_scenarios"] == 10 and s1["seed"] == 7
    assert s1["nominal"]["backlog_units_end"] == pytest.approx(0.0)
    assert s1["late_units"]["max"] >= s1["late_units"]["mean"] >= 0.0


def test_two_lot_plan_spreads_outage_risk():
    """Splitting production across two days measurably beats one
    all-on-one-day lot under line-day outages: one downed day loses
    only half the production."""
    f = _factory()
    one_lot = _plan([("L1", 1, "A", 100.0)])
    split = _plan([("L1", 0, "A", 50.0), ("L1", 1, "A", 50.0)])
    s_one = robustness_score(f, one_lot, n_scenarios=60, seed=3,
                             p_down_day=0.2)
    s_split = robustness_score(f, split, n_scenarios=60, seed=3,
                               p_down_day=0.2)
    assert s_split["late_units"]["mean"] < s_one["late_units"]["mean"]


@pytest.mark.benchmark
def test_simtwin_gate_scale_scores():
    """Stage 4 slice-3 gate: both plans get a measured robustness
    score at 2-plant scale. No winner is asserted - the finding
    (tighter plan, worse absorption) is the evidence."""
    from brain_core.backtest import naive_plan
    from brain_core.decompose import solve_decomposed
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    from tests.helpers_two_plant import two_plant_factory
    params = FnbParams(n_lines=6, n_skus=400, days=7,
                       active_fraction=0.25, utilization=0.65,
                       n_raw_materials=30, seed=1000)
    p = generate_fnb_factory(params)
    f2 = two_plant_factory(p.factory)
    res = solve_decomposed(f2, p.params.horizon_start, 7, 96 * 15,
                           bucket_time_s=60, seq_time_s=20)
    assert res.problems == []
    naive = naive_plan(f2, p.params.horizon_start, 7, 96 * 15)
    for name, plan in (("optimizer", res.plan), ("naive", naive)):
        s = robustness_score(f2, plan, n_scenarios=20, seed=5,
                             p_down_day=0.03, demand_jitter=0.15)
        assert s["late_units"]["max"] >= s["late_units"]["mean"] >= 0.0
        print(name, s["late_units"], s["nominal"])
