"""Fail-before: a row filed against the pool bound of DIFFERENT pools
(caps-v1 vs caps-v2 of the same seed) used to be compared silently."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))

from brain_core.guards.pool_identity import (compare_to_pool_bound,  # noqa: E402
                                             pools_hash)

SUP_A = {("RAW-01", 2): 133566.3, ("RAW-00", 3): 13834.8}
SUP_B = {("RAW-01", 2): 49742.76, ("RAW-00", 3): 19126.8}  # same seed, other M
LAB = {0: 100.0, 1: 90.0}


def test_hash_is_stable_and_separates_pool_sets():
    assert pools_hash(SUP_A, LAB) == pools_hash(dict(reversed(list(
        SUP_A.items()))), {1: 90.0, 0: 100.0 + 1e-12})
    assert pools_hash(SUP_A, LAB) != pools_hash(SUP_B, LAB)
    assert pools_hash(SUP_A, LAB) != pools_hash(SUP_A, {0: 100.0, 1: 91.0})


def test_different_pools_is_its_own_finding_not_a_false_alarm():
    bound = {"pools_hash": pools_hash(SUP_A, LAB), "lower_bound": 1e5,
             "late_weight": 1000.0}
    row = {"pools_hash": pools_hash(SUP_B, LAB), "kind": "converged_lp",
           "objective": 1983.4}
    f = compare_to_pool_bound(row, bound)
    assert [x.rule for x in f] == ["pools_differ_not_comparable"]
    assert compare_to_pool_bound({"kind": "converged_lp", "objective": 1.0},
                                 bound)[0].rule == "pools_differ_not_comparable"


def test_same_pools_below_bound_is_flagged_and_at_bound_passes():
    h = pools_hash(SUP_A, LAB)
    bound = {"pools_hash": h, "lower_bound": 1e5, "late_weight": 1000.0}
    low = {"pools_hash": h, "kind": "converged_lp", "objective": 1983.4}
    assert [x.rule for x in compare_to_pool_bound(low, bound)] == \
        ["below_physical_bound_pool"]
    ok = {"pools_hash": h, "kind": "plan_objective", "objective": 1.0e8 + 5}
    assert compare_to_pool_bound(ok, bound) == []


def test_weak_lower_bound_below_is_not_a_contradiction():
    h = pools_hash(SUP_A, LAB)
    bound = {"pools_hash": h, "lower_bound": 1e5, "late_weight": 1000.0}
    assert compare_to_pool_bound({"pools_hash": h, "kind": "lower_bound",
                                  "objective": 5.0}, bound) == []


def test_cg_series_guard_flags_master_rise_and_bound_above_master():
    from brain_core.guards.pool_identity import cg_series_findings
    ok = cg_series_findings([10.0, 9.0, 8.5, 8.5], [None, 7.0, 8.4, None])
    assert ok == []
    rise = cg_series_findings([2268.6, 2273.7, 2268.9], [None, None, None])
    assert [x.rule for x in rise] == ["master_not_monotone"]
    cross = cg_series_findings([2273.7, 2268.6], [2269.84, None])
    assert [x.rule for x in cross] == ["farley_above_master"]
