"""NLP interior-point solver (Gould, Orban, Sartenaer & Toint,
Algorithm 4.1) on convex problems with known optima, cross-checked
against the repo's QP solver.

Honest scope of the claims tested: convex objectives and convex-feasible
regions with a strictly feasible start, small dense problems. The solver
is a local method; nothing here claims global convergence on nonconvex
problems.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.nlp import solve_nlp_ipm
from brain_core.qp import solve_qp_ipm

ZERO2 = lambda x: [[0.0, 0.0], [0.0, 0.0]]


def test_locked_equality_only():
    # min (x1-3)^2 + (x2+1)^2 s.t. x1 + x2 = 2, x1 >= 0.
    # Unconstrained minimizer (3, -1) satisfies the equality -> f = 0.
    res = solve_nlp_ipm(
        lambda x: (x[0] - 3.0) ** 2 + (x[1] + 1.0) ** 2,
        lambda x: [2.0 * (x[0] - 3.0), 2.0 * (x[1] + 1.0)],
        lambda x: [[2.0, 0.0], [0.0, 2.0]],
        [lambda x: x[0]],
        lambda x: [[1.0, 0.0]],
        [ZERO2],
        A=[[1.0, 1.0]],
        b=[2.0],
        x0=[1.0, 1.0],
    )
    assert res["status"] == "optimal"
    assert abs(res["objective"]) < 1e-6
    assert abs(res["x"][0] - 3.0) < 1e-4
    assert abs(res["x"][1] + 1.0) < 1e-4


def test_locked_active_linear_inequality():
    # min x1^2 + x2^2 s.t. x1 + x2 - 2 >= 0 -> (1, 1), f = 2.
    res = solve_nlp_ipm(
        lambda x: x[0] ** 2 + x[1] ** 2,
        lambda x: [2.0 * x[0], 2.0 * x[1]],
        lambda x: [[2.0, 0.0], [0.0, 2.0]],
        [lambda x: x[0] + x[1] - 2.0],
        lambda x: [[1.0, 1.0]],
        [ZERO2],
        x0=[2.0, 2.0],
    )
    assert res["status"] == "optimal"
    assert abs(res["objective"] - 2.0) < 1e-5
    assert abs(res["x"][0] - 1.0) < 1e-4
    assert abs(res["x"][1] - 1.0) < 1e-4


def test_locked_nonlinear_inequality():
    # min (x1-2)^2 + (x2-2)^2 s.t. 4 - x1^2 - x2^2 >= 0 (disk radius 2).
    # (2,2) is outside the disk; optimum is the projection onto the
    # circle: x = (sqrt(2), sqrt(2)), f = 2*(2 - sqrt(2))^2.
    import math

    expected = 2.0 * (2.0 - math.sqrt(2.0)) ** 2
    res = solve_nlp_ipm(
        lambda x: (x[0] - 2.0) ** 2 + (x[1] - 2.0) ** 2,
        lambda x: [2.0 * (x[0] - 2.0), 2.0 * (x[1] - 2.0)],
        lambda x: [[2.0, 0.0], [0.0, 2.0]],
        [lambda x: 4.0 - x[0] ** 2 - x[1] ** 2],
        lambda x: [[-2.0 * x[0], -2.0 * x[1]]],
        [lambda x: [[-2.0, 0.0], [0.0, -2.0]]],
        x0=[0.5, 0.5],
    )
    assert res["status"] == "optimal"
    assert abs(res["objective"] - expected) < 1e-5
    assert abs(res["x"][0] - math.sqrt(2.0)) < 1e-4
    assert abs(res["x"][1] - math.sqrt(2.0)) < 1e-4


def test_quadratic_objective_matches_qp_solver():
    # With quadratic f and c(x) = x (bound inequalities), the NLP solver
    # must agree with the QP solver on the same problem.
    rng = random.Random(20261125)
    for _ in range(15):
        n = rng.randint(2, 4)
        R = [[rng.uniform(-1.5, 1.5) for _ in range(n)] for _ in range(n)]
        alpha = rng.uniform(0.1, 1.0)
        Q = [
            [sum(R[r][i] * R[r][j] for r in range(n)) + (alpha if i == j else 0.0)
             for j in range(n)]
            for i in range(n)
        ]
        c = [rng.uniform(-2, 2) for _ in range(n)]
        A = [[1.0] * n]
        b = [float(n) / 2.0]

        qp = solve_qp_ipm(Q, c, A, b)
        nlp = solve_nlp_ipm(
            lambda x: 0.5 * sum(
                x[i] * Q[i][j] * x[j] for i in range(n) for j in range(n)
            ) + sum(c[i] * x[i] for i in range(n)),
            lambda x: [
                sum(Q[i][j] * x[j] for j in range(n)) + c[i] for i in range(n)
            ],
            lambda x: [row[:] for row in Q],
            [lambda x, i=i: x[i] for i in range(n)],
            lambda x: [[1.0 if j == i else 0.0 for j in range(n)] for i in range(n)],
            [
                (lambda x, i=i: [[0.0] * n for _ in range(n)])
                for i in range(n)
            ],
            A=A,
            b=b,
            x0=[b[0] / n] * n,
        )
        assert abs(nlp["objective"] - qp["objective"]) < 1e-4


def test_kkt_residuals_at_solution():
    # Independent verification: stationarity, feasibility, complementary
    # slackness of the returned (x, y, z) on a mixed problem.
    # min x1^2 + x1*x2 + x2^2 - 3 x1  s.t. x1 + x2 = 1, x1 >= 0, x2 >= 0.
    f = lambda x: x[0] ** 2 + x[0] * x[1] + x[1] ** 2 - 3.0 * x[0]
    gf = lambda x: [2.0 * x[0] + x[1] - 3.0, x[0] + 2.0 * x[1]]
    hf = lambda x: [[2.0, 1.0], [1.0, 2.0]]
    cons = [lambda x: x[0], lambda x: x[1]]
    jac = lambda x: [[1.0, 0.0], [0.0, 1.0]]
    hc = [ZERO2, ZERO2]
    res = solve_nlp_ipm(f, gf, hf, cons, jac, hc, A=[[1.0, 1.0]], b=[1.0],
                        x0=[0.5, 0.5])
    x, y, z = res["x"], res["y"], res["z"]
    # primal feasibility
    assert abs(x[0] + x[1] - 1.0) < 1e-6
    assert x[0] >= -1e-7 and x[1] >= -1e-7
    # dual feasibility
    assert z[0] >= -1e-7 and z[1] >= -1e-7
    # stationarity: grad f + A^T y - J^T z = 0
    g = gf(x)
    assert abs(g[0] + y[0] - z[0]) < 1e-4
    assert abs(g[1] + y[0] - z[1]) < 1e-4
    # complementary slackness
    assert abs(x[0] * z[0]) < 1e-4
    assert abs(x[1] * z[1]) < 1e-4


def test_infeasible_start_rejected_loudly():
    # c(x0) > 0 is required; a violating start must raise, not mis-solve.
    try:
        solve_nlp_ipm(
            lambda x: x[0] ** 2,
            lambda x: [2.0 * x[0]],
            lambda x: [[2.0]],
            [lambda x: x[0] - 1.0],
            lambda x: [[1.0]],
            [lambda x: [[0.0]]],
            x0=[0.0],
        )
    except ArithmeticError:
        return
    raise AssertionError("expected ArithmeticError for infeasible start")
