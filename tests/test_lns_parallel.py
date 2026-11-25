"""Phase B: parallel LNS shard merge semantics."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lns import LNSResult, lns_improve, merge_lns_results
from brain_core.rolling.two_level import solve_buckets
from brain_core.synthetic import FnbParams, generate_fnb_factory


def _incumbent():
    p = generate_fnb_factory(FnbParams(seed=0, n_lines=3, n_skus=40,
                                       days=4, active_fraction=0.9,
                                       utilization=0.5,
                                       n_raw_materials=5,
                                       families=("DAIRY", "BAKERY",
                                                 "SAUCE")))
    b = solve_buckets(p.factory, p.params.horizon_start, 4,
                      p.day_capacity_minutes, 0.15, time_limit_s=5)
    assert b.objective is not None
    return p, b


def test_merge_picks_recomputed_best_and_is_never_worse():
    p, inc = _incumbent()
    r1 = lns_improve(p.factory, p.params.horizon_start, 4,
                     p.day_capacity_minutes, inc, iterations=1,
                     neigh_time_s=5, wall_budget_s=30, seed=11)
    r2 = lns_improve(p.factory, p.params.horizon_start, 4,
                     p.day_capacity_minutes, inc, iterations=1,
                     neigh_time_s=5, wall_budget_s=30, seed=22,
                     free_fraction=0.5)
    merged = merge_lns_results(inc.objective, [r1, r2])
    assert merged.bucket.objective <= min(r1.bucket.objective,
                                          r2.bucket.objective) + 1e-9
    # never worse than the incumbent's own recomputed objective
    assert merged.bucket.objective <= inc.objective + 1e-9
    assert merged.improved == (merged.bucket.objective
                               < inc.objective - 1e-6)


def test_merge_rejects_empty_and_objectiveless():
    with pytest.raises(ValueError):
        merge_lns_results(1.0, [])
    bad = LNSResult(bucket=type("B", (), {"objective": None})(),
                    improved=False, start_objective=1.0, objective=1.0,
                    iterations_run=0, accepted=0, wall_s=0.0, history=[])
    with pytest.raises(ValueError):
        merge_lns_results(1.0, [bad])
