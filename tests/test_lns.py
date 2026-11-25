"""Stage 4, slice 2: large-neighbourhood search on the bucket MILP.

The honest contract: LNS never returns a plan worse than the
incumbent it was given (by recomputed objective), respects its wall
budget, and reports whether it actually improved anything.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lns import lns_improve
from brain_core.rolling import solve_buckets, solve_window, validate_window_plan
from brain_core.synthetic import FnbParams, generate_fnb_factory

H0 = datetime(2026, 11, 30)

SMALL = FnbParams(seed=0, n_lines=3, n_skus=40, days=4,
                  active_fraction=0.9, utilization=0.55,
                  n_raw_materials=5,
                  families=("DAIRY", "BAKERY", "SAUCE"))


def test_lns_never_worse_than_incumbent():
    p = generate_fnb_factory(SMALL)
    inc = solve_buckets(p.factory, p.params.horizon_start,
                        p.params.days, p.day_capacity_minutes,
                        time_limit_s=5)
    assert inc.objective is not None
    res = lns_improve(p.factory, p.params.horizon_start,
                      p.params.days, p.day_capacity_minutes, inc,
                      iterations=2, free_fraction=0.3, neigh_time_s=5,
                      wall_budget_s=60, seed=1)
    assert res.objective <= res.start_objective + 1e-6
    assert res.iterations_run >= 1
    assert res.bucket.qty              # a real plan came back
    # history records measured objectives only
    for h in res.history:
        if "objective" in h:
            assert h["objective"] >= 0.0


def test_lns_result_feeds_the_sequencing_pipeline():
    """The LNS bucket must be a valid BucketResult for level 2: run
    the day sequencing + validator on it end to end."""
    from brain_core.rolling.two_level import (WindowPlan,
                                              solve_day_sequences)
    p = generate_fnb_factory(SMALL)
    inc = solve_buckets(p.factory, p.params.horizon_start,
                        p.params.days, p.day_capacity_minutes,
                        time_limit_s=5)
    res = lns_improve(p.factory, p.params.horizon_start,
                      p.params.days, p.day_capacity_minutes, inc,
                      iterations=1, neigh_time_s=5, seed=2)
    assignments, seq_probs = solve_day_sequences(
        p.factory, res.bucket, p.day_capacity_minutes, time_limit_s=5)
    plan = WindowPlan(p.params.horizon_start, p.params.days,
                      assignments, res.bucket, "test",
                      problems=seq_probs)
    problems, kpis = validate_window_plan(p.factory, plan,
                                          p.day_capacity_minutes)
    assert problems == [], problems[:3]


def test_lns_refuses_incumbent_without_objective():
    from brain_core.rolling.two_level import BucketResult
    p = generate_fnb_factory(SMALL)
    bad = BucketResult("infeasible", None, None, {}, 0, 0, 0)
    res = lns_improve(p.factory, p.params.horizon_start,
                      p.params.days, p.day_capacity_minutes, bad,
                      iterations=2, neigh_time_s=5)
    assert not res.improved
    assert res.iterations_run == 0
    assert "refused" in res.history[0]["note"]


@pytest.mark.benchmark
def test_lns_gate_scale_evidence():
    """Stage 4 slice-2 gate: at 6x400x7 scale, LNS on a cheap (5s)
    incumbent measurably improves the recomputed objective within its
    wall budget. Evidence snapshot in /tmp/gate4-lns.json."""
    params = FnbParams(n_lines=6, n_skus=400, days=7,
                       active_fraction=0.25, utilization=0.65,
                       n_raw_materials=30, seed=1000)
    p = generate_fnb_factory(params)
    inc = solve_buckets(p.factory, p.params.horizon_start, 7, 96 * 15,
                        time_limit_s=5)
    assert inc.objective is not None
    res = lns_improve(p.factory, p.params.horizon_start, 7, 96 * 15,
                      inc, iterations=5, free_fraction=0.4,
                      neigh_time_s=10, wall_budget_s=90, seed=1)
    assert res.improved
    assert res.objective < res.start_objective - 1e-6
    assert res.wall_s <= 95.0
