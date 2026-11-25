"""Stage 2, slice 5: back-test harness, optimizer vs naive baseline.

Small-instance correctness tests run in the suite; the 12-week
evidence run at scale is benchmark-marked.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.backtest import naive_plan, run_backtest
from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)
from brain_core.rolling import validate_window_plan
from brain_core.synthetic import FnbParams, generate_fnb_factory

H0 = datetime(2026, 11, 30)

SMALL = FnbParams(seed=0, n_lines=3, n_skus=40, days=4,
                  active_fraction=0.9, utilization=0.5,
                  n_raw_materials=5,
                  families=("DAIRY", "BAKERY", "SAUCE"))


def test_naive_plan_is_valid_and_covers_demand():
    p = generate_fnb_factory(SMALL)
    plan = naive_plan(p.factory, p.params.horizon_start, p.params.days,
                      p.day_capacity_minutes)
    problems, kpis = validate_window_plan(p.factory, plan,
                                          p.day_capacity_minutes)
    assert problems == [], problems[:3]
    # moderate utilization: the naive plan should not be late either
    assert kpis["backlog_units_end"] == pytest.approx(0.0)
    assert kpis["assignments"] > 0


def test_naive_respects_changeover_when_fitting():
    """A tight line-day: naive must not stack lots whose changeovers
    exceed the day (it fits production + true matrix changeover)."""
    f = Factory(
        locations=[Location(name="P")],
        items=[Item(name="A"), Item(name="B")],
        setup_matrices=[SetupMatrix(name="CHG", rules=[
            SetupRule(from_setup="S1", to_setup="S2",
                      duration=timedelta(minutes=200)),
            SetupRule(from_setup="S2", to_setup="S1",
                      duration=timedelta(minutes=200))])],
        resources=[Resource(name="L1", location="P", setup_matrix="CHG")],
        operations=[
            Operation(name="MAKE-A", item="A", location="P",
                      duration_per=timedelta(minutes=1),
                      materials=[OperationMaterial(item="A", quantity=1)],
                      loads=[OperationResource(resource="L1", setup="S1")]),
            Operation(name="MAKE-B", item="B", location="P",
                      duration_per=timedelta(minutes=1),
                      materials=[OperationMaterial(item="B", quantity=1)],
                      loads=[OperationResource(resource="L1", setup="S2")]),
        ],
        demands=[Demand(name="D1", item="A", location="P",
                        due=H0 + timedelta(days=1), quantity=300.0),
                 Demand(name="D2", item="B", location="P",
                        due=H0 + timedelta(days=1), quantity=300.0)])
    plan = naive_plan(f, H0, 1, 480.0)
    problems, kpis = validate_window_plan(f, plan, 480.0)
    assert problems == [], problems
    # 300 + 200 chg + 300 = 800 > 480: B could not fit on the same day
    # after A, so it is split or late, never over capacity.
    assert kpis["backlog_units_end"] > 0 or \
        kpis["changeover_minutes"] <= 200.0


def test_optimizer_beats_naive_on_changeovers_small():
    """Allergen-heavy mix: EDD order interleaves states; the optimizer
    groups them. Same validator on both plans."""
    p = generate_fnb_factory(FnbParams(
        **{**SMALL.__dict__, "utilization": 0.55}))
    opt_problems = []
    res = run_backtest(weeks=2, cap_min=p.day_capacity_minutes,
                       params=SMALL, bucket_time_s=20, seq_time_s=5,
                       week0_seed=42)
    assert res.all_optimizer_plans_valid
    assert res.total_optimizer_late_units <= \
        res.total_naive_late_units + 1e-6
    assert res.total_optimizer_changeover_min <= \
        res.total_naive_changeover_min + 1e-6
    assert res.beats_baseline


@pytest.mark.benchmark
def test_backtest_twelve_weeks():
    """The Stage 2 back-test evidence: 12 weekly instances.

    Runs at a medium scale (6 lines, 400 SKUs) so the full evidence
    run finishes in minutes; the Makkook-scale solve itself is proven
    by the slice-2 gate test.
    """
    params = FnbParams(n_lines=6, n_skus=400, days=7,
                       active_fraction=0.25, utilization=0.65,
                       n_raw_materials=30)
    res = run_backtest(weeks=12, cap_min=96 * 15, params=params,
                       bucket_time_s=60, seq_time_s=20,
                       week0_seed=1000)
    assert res.all_optimizer_plans_valid, [
        (r.week, r.optimizer_problems[:2])
        for r in res.weeks if r.optimizer_problems][:3]
    assert res.beats_baseline, (
        f"optimizer chg {res.total_optimizer_changeover_min} vs naive "
        f"{res.total_naive_changeover_min}; late "
        f"{res.total_optimizer_late_units} vs "
        f"{res.total_naive_late_units}")
