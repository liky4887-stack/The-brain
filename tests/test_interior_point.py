"""Path-following interior-point method (Vanderbei ch.16-17) vs exact simplex.

The IPM works in floating point on the book's max-form with <= rows and
returns near-optimal iterates on feasible, bounded instances only. It
gives no infeasibility or unboundedness certificates - that is the
exact simplex's job (brain_core.lp.simplex.solve_lp).

Scope of the claims tested here, honestly:
  - the locked Wyndor glass problem (Hillier & Lieberman) converges to
    the known optimum;
  - random feasible+bounded LPs agree with the exact-rational two-phase
    simplex within float tolerance on the objective, and the returned
    point is feasible within float tolerance.
"""

import random
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lp import LPStatus, solve_lp
from brain_core.lp.interior_point import solve_lp_ipm


def test_wyndor():
    # maximize 3 x1 + 5 x2  s.t. x1 <= 4, 2 x2 <= 12, 3 x1 + 2 x2 <= 18.
    # Known optimum: Z = 36 at (2, 6).
    res = solve_lp_ipm(
        [-3.0, -5.0],
        [[1.0, 0.0], [0.0, 2.0], [3.0, 2.0]],
        [4.0, 12.0, 18.0],
        ["<=", "<=", "<="],
    )
    assert res["status"] == LPStatus.OPTIMAL
    assert abs(res["objective"] - (-36.0)) < 1e-6
    assert abs(res["x"][0] - 2.0) < 1e-5
    assert abs(res["x"][1] - 6.0) < 1e-5


def random_bounded_feasible_lp(rng):
    """Random LP that is feasible and bounded by construction.

    maximize sum c_j x_j  with 0 <= x_j <= 2 (upper bounds make it
    bounded) and extra <= rows that the point x = (1,...,1) satisfies
    strictly (makes it feasible with an interior).
    Returns (c_min, A, b, senses) for the shared minimize interface.
    """
    n = rng.randint(2, 5)
    m = rng.randint(1, 4)
    c_max = [rng.randint(-5, 5) for _ in range(n)]
    A = []
    b = []
    senses = []
    for _ in range(m):
        row = [rng.randint(0, 4) for _ in range(n)]
        # slack so that x = (1,...,1) is strictly interior to this row
        limit = sum(row) + rng.randint(1, 5)
        A.append([float(v) for v in row])
        b.append(float(limit))
        senses.append("<=")
    # upper bounds x_j <= 2
    for j in range(n):
        row = [0.0] * n
        row[j] = 1.0
        A.append(row)
        b.append(2.0)
        senses.append("<=")
    c_min = [-float(v) for v in c_max]
    return c_min, A, b, senses


def test_random_lps_agree_with_exact_simplex():
    rng = random.Random(20261125)
    checked = 0
    for _ in range(60):
        c, A, b, senses = random_bounded_feasible_lp(rng)
        exact = solve_lp(c, A, b, senses)
        assert exact.status == LPStatus.OPTIMAL  # by construction
        res = solve_lp_ipm(c, A, b, senses)
        assert res["status"] == LPStatus.OPTIMAL
        # objective agreement within float tolerance
        assert abs(res["objective"] - float(exact.objective)) < 1e-4
        # feasibility of the returned point within float tolerance
        x = res["x"]
        n = len(c)
        assert all(v >= -1e-6 for v in x)
        for i, sense in enumerate(senses):
            lhs = sum(A[i][j] * x[j] for j in range(n))
            if sense == "<=":
                assert lhs <= b[i] + 1e-5
            elif sense == ">=":
                assert lhs >= b[i] - 1e-5
            else:
                assert abs(lhs - b[i]) < 1e-4
        checked += 1
    assert checked == 60


def test_mixed_senses():
    # minimize x1 + x2  s.t. x1 + x2 >= 2, x1 <= 5, x2 <= 5.
    # Optimum 2 anywhere on the segment; check objective only.
    res = solve_lp_ipm(
        [1.0, 1.0],
        [[1.0, 1.0], [1.0, 0.0], [0.0, 1.0]],
        [2.0, 5.0, 5.0],
        [">=", "<=", "<="],
    )
    assert res["status"] == LPStatus.OPTIMAL
    assert abs(res["objective"] - 2.0) < 1e-5
