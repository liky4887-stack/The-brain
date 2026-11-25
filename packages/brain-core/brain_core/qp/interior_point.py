"""Primal-dual path-following interior-point method for convex QP.

Source: Potra & Wright, "Interior-Point Methods" (J. Comput. Appl.
Math., 2000), sec. 3, problem (3.18): the convex quadratic program
    min c^T x + (1/2) x^T Q x   s.t.  A x = b, x >= 0
with Q symmetric positive semidefinite. The search-direction system is
the LP system with the Hessian Q added to the stationarity block
("identical to (2.10) except that the (2;2) block ... is replaced by
Q"), and the same step length is used for primal and dual variables.

Central path: Qx + c - A^T y - z = 0, Ax = b, XZe = mu e, (x, z) > 0.
Infeasible-start Newton iteration from any (x, z) > 0, mirroring
brain_core.lp.interior_point (Vanderbei ch.16-17).

Honest scope: floats; claims a near-optimal solution on feasible,
bounded instances only - no infeasibility or unboundedness certificates.
Q must be symmetric positive semidefinite; we symmetrize and reject a
negative eigenvalue beyond float noise by checking the quadratic form on
the returned step (documented, not a full PSD certificate).
"""

from __future__ import annotations

from typing import List, Optional

from ..lp.simplex import LPStatus

DELTA = 0.1          # barrier shrink factor
MARGIN = 0.9         # fraction-to-boundary margin (same step for x, y, z)
TOL = 1e-9
MAX_ITER = 500


def _gauss_solve(A: List[List[float]], b: List[float]) -> List[float]:
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-300:
            raise ArithmeticError("singular KKT system")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            if f != 0.0:
                M[r] = [a - f * bb for a, bb in zip(M[r], M[col])]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / M[r][r]
    return x


def solve_qp_ipm(Q, c, A, b, tol: float = TOL, max_iter: int = MAX_ITER) -> dict:
    """Minimize (1/2) x^T Q x + c^T x s.t. A x = b, x >= 0.

    Q may be None (pure LP) or an n-by-n nested list; A may be empty
    (no equalities). Returns {"status", "objective", "x", "y", "z"}.
    Only OPTIMAL is returned on success; anything else raises
    ArithmeticError (no certificates - see the module docstring).
    """
    n = len(c)
    m = len(A)
    for row in A:
        if len(row) != n:
            raise ValueError("every row of A must have n entries")
    if len(b) != m:
        raise ValueError("A and b row-count mismatch")
    Qm = [[0.0] * n for _ in range(n)] if Q is None else [
        [0.5 * (float(Q[i][j]) + float(Q[j][i])) for j in range(n)]
        for i in range(n)
    ]
    if any(len(row) != n for row in Qm):
        raise ValueError("Q must be n-by-n")
    cf = [float(v) for v in c]
    Af = [[float(v) for v in row] for row in A]
    bf = [float(v) for v in b]

    # Infeasible-start: large strictly positive x, z; y = 0.
    big = 1.0 + max([abs(v) for v in cf] + [abs(v) for v in bf] + [1.0])
    x = [big] * n
    y = [0.0] * m
    z = [big] * n

    status: Optional[LPStatus] = None
    for _ in range(max_iter):
        mu = sum(x[j] * z[j] for j in range(n)) / n
        # residuals: rs = Qx + c - A^T y - z, rp = Ax - b
        rs = [
            sum(Qm[j][k] * x[k] for k in range(n)) + cf[j]
            - sum(Af[i][j] * y[i] for i in range(m)) - z[j]
            for j in range(n)
        ]
        rp = [sum(Af[i][j] * x[j] for j in range(n)) - bf[i] for i in range(m)]
        if mu <= tol and max(
            max(abs(v) for v in rs),
            max((abs(v) for v in rp), default=0.0),
        ) <= max(tol * 100, 1e-9):
            status = LPStatus.OPTIMAL
            break
        mu_t = DELTA * mu
        # Eliminate dz = X^-1 (mu' e - XZe) - X^-1 Z dx.
        # Reduced (n+m) system in (dx, dy):
        #   (Q + X^-1 Z) dx - A^T dy = -rs - X^-1 (XZe - mu' e)
        #   A dx                 = -rp
        K = [[0.0] * (n + m) for _ in range(n + m)]
        rhs = [0.0] * (n + m)
        for j in range(n):
            for k in range(n):
                K[j][k] = Qm[j][k]
            K[j][j] += z[j] / x[j]
            rhs[j] = -rs[j] - (x[j] * z[j] - mu_t) / x[j]
        for i in range(m):
            for j in range(n):
                K[j][n + i] = -Af[i][j]
                K[n + i][j] = Af[i][j]
            rhs[n + i] = -rp[i]
        try:
            d = _gauss_solve(K, rhs)
        except ArithmeticError as exc:
            raise ArithmeticError(
                "KKT system singular - problem may be infeasible, "
                "unbounded, or Q not positive semidefinite"
            ) from exc
        dx, dy = d[:n], d[n:]
        dz = [
            (mu_t - x[j] * z[j]) / x[j] - (z[j] / x[j]) * dx[j]
            for j in range(n)
        ]
        # One fraction-to-boundary step for ALL variables (QP rule).
        theta = 1.0
        for j in range(n):
            if dx[j] < 0.0:
                theta = min(theta, -x[j] / dx[j])
            if dz[j] < 0.0:
                theta = min(theta, -z[j] / dz[j])
        theta = min(1.0, MARGIN * theta)
        if theta <= 0.0:
            raise ArithmeticError("no positive step - stalled")
        x = [x[j] + theta * dx[j] for j in range(n)]
        y = [y[i] + theta * dy[i] for i in range(m)]
        z = [z[j] + theta * dz[j] for j in range(n)]
    if status is None:
        raise ArithmeticError(f"no convergence in {max_iter} iterations")
    obj = 0.5 * sum(
        x[j] * Qm[j][k] * x[k] for j in range(n) for k in range(n)
    ) + sum(cf[j] * x[j] for j in range(n))
    return {"status": status, "objective": obj, "x": x, "y": y, "z": z}
