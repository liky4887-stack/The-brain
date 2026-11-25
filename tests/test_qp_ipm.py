"""Convex-QP interior-point solver (Potra & Wright sec. 3, problem 3.18)
vs an independent active-set enumeration oracle.

The oracle enumerates every subset S of variables held at the bound
x = 0, solves the equality KKT system for the free variables, and keeps
the feasible candidate (free x > 0, duals z >= 0) with the smallest
objective. That is a different algorithm from path-following, so
agreement is real cross-validation. Q is symmetric PSD by construction
(Q = R^T R + alpha I); the single all-ones equality row puts x in a
simplex, so every random instance is feasible and bounded.
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lp import LPStatus, solve_lp
from brain_core.qp import solve_qp_ipm


def gauss_solve(M, rhs):
    """Float solve of a square system; None if numerically singular."""
    n = len(M)
    A = [row[:] + [rhs[i]] for i, row in enumerate(M)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-12:
            return None
        A[col], A[piv] = A[piv], A[col]
        for r in range(n):
            if r != col and A[r][col] != 0.0:
                f = A[r][col] / A[col][col]
                A[r] = [a - f * b for a, b in zip(A[r], A[col])]
    return [A[r][n] / A[r][r] for r in range(n)]


def active_set_oracle(Q, c, A, b):
    """Brute-force optimum of min 1/2 x'Qx + c'x, Ax=b, x>=0, or None."""
    n = len(c)
    m = len(A)
    best = None
    for k in range(n + 1):
        for S in itertools.combinations(range(n), k):
            free = [j for j in range(n) if j not in S]
            # KKT for free vars: [Q_FF, -A_F^T; A_F, 0] [x_F; y] = [-c_F; b]
            dim = len(free) + m
            M = [[0.0] * dim for _ in range(dim)]
            rhs = [0.0] * dim
            for a, ja in enumerate(free):
                for bq, jb in enumerate(free):
                    M[a][bq] = Q[ja][jb]
                for i in range(m):
                    M[a][len(free) + i] = -A[i][ja]
                rhs[a] = -c[ja]
            for i in range(m):
                for a, ja in enumerate(free):
                    M[len(free) + i][a] = A[i][ja]
                rhs[len(free) + i] = b[i]
            sol = gauss_solve(M, rhs)
            if sol is None:
                continue
            x = [0.0] * n
            ok = True
            for a, ja in enumerate(free):
                if sol[a] < -1e-7:
                    ok = False
                    break
                x[ja] = sol[a]
            if not ok:
                continue
            y = sol[len(free):]
            # duals: z = Qx + c - A^T y must be >= 0 (esp. on S)
            z = [
                sum(Q[j][jj] * x[jj] for jj in range(n)) + c[j]
                - sum(A[i][j] * y[i] for i in range(m))
                for j in range(n)
            ]
            if min(z) < -1e-6:
                continue
            obj = 0.5 * sum(
                x[j] * Q[j][jj] * x[jj] for j in range(n) for jj in range(n)
            ) + sum(c[j] * x[j] for j in range(n))
            if best is None or obj < best[0] - 1e-9:
                best = (obj, x)
    return best


def test_locked_sphere_on_plane():
    # min 1/2 (x1^2 + x2^2) s.t. x1 + x2 = 1 -> (0.5, 0.5), obj 0.25
    res = solve_qp_ipm([[1.0, 0.0], [0.0, 1.0]], [0.0, 0.0], [[1.0, 1.0]], [1.0])
    assert res["status"] == LPStatus.OPTIMAL
    assert abs(res["objective"] - 0.25) < 1e-6
    assert abs(res["x"][0] - 0.5) < 1e-5
    assert abs(res["x"][1] - 0.5) < 1e-5


def test_locked_no_equalities():
    # min (x - 2)^2 - 4 = 1/2 * 2 x^2 - 4 x, x >= 0 -> x = 2, obj -4
    res = solve_qp_ipm([[2.0]], [-4.0], [], [])
    assert res["status"] == LPStatus.OPTIMAL
    assert abs(res["objective"] - (-4.0)) < 1e-6
    assert abs(res["x"][0] - 2.0) < 1e-5


def random_psd_qp(rng):
    n = rng.randint(2, 5)
    R = [[rng.uniform(-2, 2) for _ in range(n)] for _ in range(n)]
    alpha = rng.uniform(0.0, 1.0)
    Q = [
        [sum(R[r][i] * R[r][j] for r in range(n)) + (alpha if i == j else 0.0)
         for j in range(n)]
        for i in range(n)
    ]
    c = [rng.uniform(-3, 3) for _ in range(n)]
    A = [[1.0] * n]  # simplex: feasible and bounded
    b = [float(n)]
    return Q, c, A, b


def test_random_qps_agree_with_active_set_oracle():
    rng = random.Random(20261125)
    checked = 0
    for _ in range(40):
        Q, c, A, b = random_psd_qp(rng)
        oracle = active_set_oracle(Q, c, A, b)
        assert oracle is not None  # simplex is feasible by construction
        res = solve_qp_ipm(Q, c, A, b)
        assert res["status"] == LPStatus.OPTIMAL
        assert abs(res["objective"] - oracle[0]) < 1e-4
        x = res["x"]
        assert all(v >= -1e-6 for v in x)
        assert abs(sum(x) - b[0]) < 1e-5
        checked += 1
    assert checked == 40


def test_pure_lp_matches_exact_simplex():
    # Q = 0 must reproduce the LP answer (cross-check vs exact simplex).
    rng = random.Random(7)
    for _ in range(20):
        n = rng.randint(2, 5)
        c = [rng.uniform(-3, 3) for _ in range(n)]
        A = [[1.0] * n]
        b = [float(n)]
        exact = solve_lp(c, A, b, ["=="])
        assert exact.status == LPStatus.OPTIMAL
        res = solve_qp_ipm(None, c, A, b)
        assert abs(res["objective"] - float(exact.objective)) < 1e-4
