"""SDP interior-point solver (Alizadeh-Haeberly-Overton, XZ+ZX with
Mehrotra predictor-corrector) on instances with independently known
answers.

Oracles, none of which is path-following:
  - a locked 2x2 problem with the analytic optimum;
  - planted strictly complementary KKT points: for a convex SDP, any
    primal-feasible X*, dual-feasible (y*, Z*) with X* Z* = 0 is
    optimal, so the planted value is the exact optimum by construction;
  - diagonal SDPs are LPs (the paper's remark): cross-checked against
    the exact-rational simplex;
  - the MAXCUT SDP relaxation must upper-bound the brute-force maximum
    cut, with a closed duality gap.
KKT residuals (primal/dual feasibility, complementarity) are verified
on the returned triple as well.
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lp import LPStatus, solve_lp
from brain_core.sdp import solve_sdp_ipm
from brain_core.sdp.interior_point import _jacobi_eig


def test_locked_rank_one_optimum():
    # X = [[x, y], [y, z]] psd; min z s.t. x = 1, 2y = -2.
    # psd <=> z >= y^2 / x = 1 -> optimum z = 1 at X = [[1,-1],[-1,1]].
    C = [[0.0, 0.0], [0.0, 1.0]]
    A1 = [[1.0, 0.0], [0.0, 0.0]]
    A2 = [[0.0, 1.0], [1.0, 0.0]]
    res = solve_sdp_ipm(C, [A1, A2], [1.0, -2.0])
    assert res["status"] == "optimal"
    assert abs(res["objective"] - 1.0) < 1e-5
    assert abs(res["X"][0][0] - 1.0) < 1e-4
    assert abs(res["X"][0][1] + 1.0) < 1e-4
    assert abs(res["X"][1][1] - 1.0) < 1e-4
    # duality gap closed
    assert abs(res["objective"] - res["dual_objective"]) < 1e-4


def random_orthogonal(rng, n):
    """Q from the Jacobi eigendecomposition of a random symmetric matrix."""
    M = [[rng.uniform(-1, 1) for _ in range(n)] for _ in range(n)]
    S = [[0.5 * (M[i][j] + M[j][i]) for j in range(n)] for i in range(n)]
    _, Q = _jacobi_eig(S)
    return Q


def planted_sdp(rng, n, m, rank_x):
    """Random SDP with a planted strictly complementary KKT point.

    X* = Q diag(lam, 0) Q^T (rank rank_x), Z* = Q diag(0, om) Q^T
    (rank n - rank_x), lam, om > 0 -> X* Z* = 0. With
    C = Z* + sum y*_k Ak and b_k = Ak . X*, the planted point is
    primal/dual feasible and complementary, hence optimal (convex SDP).
    """
    Q = random_orthogonal(rng, n)
    lam = [rng.uniform(0.5, 2.0) for _ in range(rank_x)]
    om = [rng.uniform(0.5, 2.0) for _ in range(n - rank_x)]
    diag_x = lam + [0.0] * (n - rank_x)
    diag_z = [0.0] * rank_x + om
    Xs = [
        [sum(Q[i][r] * diag_x[r] * Q[j][r] for r in range(n)) for j in range(n)]
        for i in range(n)
    ]
    Zs = [
        [sum(Q[i][r] * diag_z[r] * Q[j][r] for r in range(n)) for j in range(n)]
        for i in range(n)
    ]
    As = []
    for _ in range(m):
        M = [[rng.uniform(-1, 1) for _ in range(n)] for _ in range(n)]
        As.append([[0.5 * (M[i][j] + M[j][i]) for j in range(n)] for i in range(n)])
    ys = [rng.uniform(-1, 1) for _ in range(m)]
    C = [
        [Zs[i][j] + sum(ys[k] * As[k][i][j] for k in range(m)) for j in range(n)]
        for i in range(n)
    ]
    b = [sum(As[k][i][j] * Xs[i][j] for i in range(n) for j in range(n))
         for k in range(m)]
    obj_star = sum(C[i][j] * Xs[i][j] for i in range(n) for j in range(n))
    return C, As, b, obj_star


def test_planted_complementary_optima():
    rng = random.Random(20261125)
    for _ in range(15):
        n = rng.randint(2, 4)
        m = rng.randint(1, n)
        rank_x = rng.randint(1, n - 1)
        C, As, b, obj_star = planted_sdp(rng, n, m, rank_x)
        res = solve_sdp_ipm(C, As, b)
        assert res["status"] == "optimal"
        assert abs(res["objective"] - obj_star) < 1e-3 * max(1.0, abs(obj_star))
        assert abs(res["objective"] - res["dual_objective"]) < 1e-3 * max(
            1.0, abs(obj_star)
        )


def test_diagonal_sdp_matches_exact_simplex():
    # Diagonal SDP = LP (paper: LP is the block-diagonal special case).
    rng = random.Random(11)
    for _ in range(10):
        n = rng.randint(2, 5)
        c = [rng.uniform(-3, 3) for _ in range(n)]
        # equality: sum x_j = n (bounded simplex) via a diagonal A
        C = [[c[i] if i == j else 0.0 for j in range(n)] for i in range(n)]
        A1 = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        exact = solve_lp(c, [[1.0] * n], [float(n)], ["=="])
        assert exact.status == LPStatus.OPTIMAL
        res = solve_sdp_ipm(C, [A1], [float(n)])
        assert abs(res["objective"] - float(exact.objective)) < 1e-4


def test_maxcut_relaxation_bounds_brute_force():
    # MAXCUT SDP relaxation (Goemans-Williamson): min -(1/4) L . X
    # s.t. diag(X) = 1, X psd. The optimum -obj must be >= the true
    # maximum cut (relaxation), and the duality gap must close.
    n = 5
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0), (0, 2), (1, 3)]
    L = [[0.0] * n for _ in range(n)]
    for i, j in edges:
        L[i][i] += 1.0
        L[j][j] += 1.0
        L[i][j] -= 1.0
        L[j][i] -= 1.0
    C = [[-0.25 * L[i][j] for j in range(n)] for i in range(n)]
    As = [
        [[1.0 if (i == k and j == k) else 0.0 for j in range(n)] for i in range(n)]
        for k in range(n)
    ]
    res = solve_sdp_ipm(C, As, [1.0] * n)
    best_cut = 0
    for bits in itertools.product([0, 1], repeat=n):
        cut = sum(1 for i, j in edges if bits[i] != bits[j])
        best_cut = max(best_cut, cut)
    sdp_value = -res["objective"]
    assert sdp_value >= best_cut - 1e-6  # relaxation must bound the cut
    assert abs(res["objective"] - res["dual_objective"]) < 1e-4


def test_kkt_residuals_on_returned_triple():
    # Independent verification on a planted instance: primal equality,
    # dual slack psd, complementarity XZ ~ 0.
    rng = random.Random(5)
    C, As, b, obj_star = planted_sdp(rng, 3, 2, 1)
    res = solve_sdp_ipm(C, As, b)
    X, y, Z = res["X"], res["y"], res["Z"]
    n = 3
    # primal feasibility
    for k in range(2):
        lhs = sum(As[k][i][j] * X[i][j] for i in range(n) for j in range(n))
        assert abs(lhs - b[k]) < 1e-4
    # X psd and Z psd
    ex, _ = _jacobi_eig(X)
    ez, _ = _jacobi_eig(Z)
    assert min(ex) >= -1e-5
    assert min(ez) >= -1e-5
    # dual feasibility: Z = C - sum yk Ak
    for i in range(n):
        for j in range(n):
            lhs = Z[i][j] + sum(y[k] * As[k][i][j] for k in range(2))
            assert abs(lhs - C[i][j]) < 1e-4
    # complementarity: || XZ || small
    xz = [
        [sum(X[i][k] * Z[k][j] for k in range(n)) for j in range(n)]
        for i in range(n)
    ]
    assert max(abs(v) for row in xz for v in row) < 1e-4
