"""Brute-force validation of the Bertsimas & Tsitsiklis sec. 12.5 results.

WSPT optimality (Theorem 12.1) is checked against exhaustive enumeration
of all job permutations. The separation algorithm (Theorem 12.2) is
checked against exhaustive enumeration of all 2^n subsets. No claim in
brain_core/scheduling/single_machine.py is asserted beyond these tests.
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.scheduling.single_machine import (
    completion_times,
    separation,
    supermodular_lhs_doubled,
    supermodular_rhs,
    weighted_completion_sum,
    wspt_order,
)


def brute_force_optimum(weights, p):
    best = None
    for perm in itertools.permutations(range(len(weights))):
        val = weighted_completion_sum(perm, weights, p)
        if best is None or val < best:
            best = val
    return best


def test_wspt_matches_exhaustive_on_small_instances():
    rng = random.Random(20261125)
    for trial in range(60):
        n = rng.randint(1, 7)
        weights = [rng.randint(1, 12) for _ in range(n)]
        p = [rng.randint(1, 12) for _ in range(n)]
        order = wspt_order(weights, p)
        assert weighted_completion_sum(order, weights, p) == brute_force_optimum(
            weights, p
        ), f"trial {trial}: WSPT not optimal for w={weights} p={p}"


def test_wspt_book_two_job_example():
    # N = {1, 2}: WSPT picks the higher w/p ratio first.
    assert wspt_order([3, 1], [1, 1]) == [0, 1]
    assert wspt_order([1, 3], [1, 1]) == [1, 0]
    # Equal ratios: either order optimal; index tiebreak returned.
    assert wspt_order([2, 2], [1, 1]) == [0, 1]


def test_wspt_equal_weights_all_nonidling_optimal():
    # Book: when w_i = p_i for all i, every nonidling schedule is optimal.
    p = [2, 5, 3, 1]
    w = list(p)
    opt = brute_force_optimum(w, p)
    for perm in itertools.permutations(range(4)):
        assert weighted_completion_sum(perm, w, p) == opt


def test_separation_matches_exhaustive_subset_search():
    rng = random.Random(7)
    for trial in range(80):
        n = rng.randint(1, 8)
        p = [rng.randint(1, 9) for _ in range(n)]
        # Mix of real schedules (feasible) and arbitrary vectors (often not).
        if trial % 2 == 0:
            perm = list(range(n))
            rng.shuffle(perm)
            c = completion_times(perm, p)
        else:
            c = {i: rng.randint(1, 5 * n) for i in range(n)}
        feasible, subset, violation = separation(c, p)
        # Exhaustive check over all 2^n subsets.
        brute_worst = 0
        brute_set = None
        for r in range(1, n + 1):
            for combo in itertools.combinations(range(n), r):
                gap = supermodular_rhs(combo, p) - supermodular_lhs_doubled(
                    combo, c, p
                )
                if gap > brute_worst:
                    brute_worst = gap
                    brute_set = list(combo)
        assert feasible == (brute_set is None), (trial, c, p)
        assert violation == brute_worst, (trial, c, p)
        if subset is not None:
            # The returned set must itself be violated by the reported gap.
            gap = supermodular_rhs(subset, p) - supermodular_lhs_doubled(
                subset, c, p
            )
            assert gap == violation


def test_real_schedules_always_feasible():
    rng = random.Random(99)
    for _ in range(50):
        n = rng.randint(1, 9)
        p = [rng.randint(1, 10) for _ in range(n)]
        perm = list(range(n))
        rng.shuffle(perm)
        c = completion_times(perm, p)
        feasible, subset, violation = separation(c, p)
        assert feasible and subset is None and violation == 0


def test_convex_hull_two_jobs_book_example():
    # Book: for N = {1, 2} the convex hull of feasible (C_1, C_2) is
    # C_1 >= p_1, C_2 >= p_2, p_1 C_1 + p_2 C_2 >= p_1^2 + p_2^2 + p_1 p_2.
    p = [2, 3]
    # (5, 3) and (2, 5) are the two real schedules; (4, 3) is below the
    # hull inequality and must be detected as violated.
    corner = {0: 4, 1: 3}
    feasible, subset, violation = separation(corner, p)
    assert not feasible
    assert set(subset) == {0, 1}
    # Doubled gap: 2*(p_1^2 + p_2^2 + p_1*p_2) - 2*(p_1*C_1 + p_2*C_2)
    assert violation == 2 * (4 + 9 + 6) - 2 * (2 * 4 + 3 * 3)
    # The two real schedules saturate the hull inequality.
    for perm in ([0, 1], [1, 0]):
        c = completion_times(perm, p)
        lhs = supermodular_lhs_doubled([0, 1], c, p)
        assert lhs == supermodular_rhs([0, 1], p)
