"""Primal-dual path-following interior-point method for LP.

Source: Vanderbei, Linear Programming: Foundations and Extensions, 2nd
ed., ch.16 (the central path) and ch.17 (the path-following method,
Figure 17.1, equations 17.1-17.6). Digital text (pdfTeX), no OCR.

The book's standard form is a MAXIMIZATION with inequality constraints:
    max c^T x  s.t.  Ax + w = b,  (x, w) >= 0
    dual: min b^T y  s.t.  A^T y - z = c,  (y, z) >= 0.
Central path: Ax + w = b, A^T y - z = c, XZe = mu e, YWe = mu e.
One-phase Newton iteration from any strictly positive start; mu is the
current average complementarity shrunk by delta (17.5); the step length
theta keeps every component strictly positive with margin r (17.6).

Honest scope: floats (no exact arithmetic is possible here); the method
only claims a near-optimal solution on FEASIBLE, BOUNDED instances - it
produces no infeasibility or unboundedness certificate (use the simplex
for those). Cross-validated against the repo's exact simplex solver.
"""

from __future__ import annotations

from typing import List, Optional

from .simplex import LPStatus

DELTA = 0.1          # barrier shrink factor (the book's practical choice)
MARGIN = 0.9         # step-length margin r
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


def solve_lp_ipm(c, A, b, senses, tol: float = TOL, max_iter: int = MAX_ITER) -> dict:
    """Minimize c.x s.t. A x <sense> b, x >= 0, by path-following IPM.

    Returns {"status": LPStatus, "objective": float|None, "x": [...]|None}.
    Only OPTIMAL is ever returned on success; anything else raises
    ArithmeticError (no certificates - see the module docstring).
    """
    m, n = len(A), len(c)
    # Convert to the book's max form with <= rows:
    # minimize c.x  <=>  maximize (-c).x; ">=" rows flip to "<="; "=="
    # rows split into two inequalities.
    rows: List[List[float]] = []
    rhs: List[float] = []
    for i in range(m):
        if senses[i] == "<=":
            rows.append([float(v) for v in A[i]])
            rhs.append(float(b[i]))
        elif senses[i] == ">=":
            rows.append([-float(v) for v in A[i]])
            rhs.append(-float(b[i]))
        elif senses[i] == "==":
            rows.append([float(v) for v in A[i]])
            rhs.append(float(b[i]))
            rows.append([-float(v) for v in A[i]])
            rhs.append(-float(b[i]))
        else:
            raise ValueError(f"bad sense {senses[i]!r}")
    m2 = len(rows)
    cmax = [-float(v) for v in c]

    x = [1.0] * n
    w = [1.0] * m2
    y = [1.0] * m2
    z = [1.0] * n

    for _ in range(max_iter):
        # residuals
        rho = [rhs[i] - sum(rows[i][j] * x[j] for j in range(n)) - w[i]
               for i in range(m2)]
        sigma = [cmax[j] - sum(rows[i][j] * y[i] for i in range(m2)) + z[j]
                 for j in range(n)]
        gamma = sum(z[j] * x[j] for j in range(n)) + sum(y[i] * w[i] for i in range(m2))
        if gamma < tol and max(abs(v) for v in rho) < tol and max(abs(v) for v in sigma) < tol:
            xval = x[:]
            obj = sum(float(c[j]) * xval[j] for j in range(n))
            return {"status": LPStatus.OPTIMAL, "objective": obj, "x": xval}
        mu = DELTA * gamma / (n + m2)

        # Full Newton system (17.1)-(17.4), block-eliminated:
        # from (17.4): dw = Y^-1 (mu e - YWe) - Y^-1 W dy
        # from (17.2): dz = A^T dy - sigma
        # sub in (17.3): Z dx + X A^T dy = mu e - XZe + X sigma
        # from (17.1): A dx = rho - dw
        # -> [ Z  XA^T ; A  Y^-1 W ] [dx; dy] = [mu e - XZe + X sigma ;
        #                                        rho - Y^-1(mu e - YWe)]
        Wv = [w[i] / y[i] for i in range(m2)]
        rhs3 = [mu - z[j] * x[j] + x[j] * sigma[j] for j in range(n)]
        rhs4 = [rho[i] - (mu - y[i] * w[i]) / y[i] for i in range(m2)]
        size = n + m2
        K = [[0.0] * size for _ in range(size)]
        for j in range(n):
            K[j][j] = z[j]
        for i in range(m2):
            for j in range(n):
                K[j][n + i] = x[j] * rows[i][j]
        for i in range(m2):
            for j in range(n):
                K[n + i][j] = rows[i][j]
            K[n + i][n + i] = -Wv[i]
        sol = _gauss_solve(K, rhs3 + rhs4)
        dx = sol[:n]
        dy = sol[n:]
        dz = [sum(rows[i][j] * dy[i] for i in range(m2)) - sigma[j] for j in range(n)]
        dw = [(mu - y[i] * w[i]) / y[i] - Wv[i] * dy[i] for i in range(m2)]

        # step length (17.6)
        theta = 1.0
        for j in range(n):
            if dx[j] < 0:
                theta = min(theta, -x[j] / dx[j])
            if dz[j] < 0:
                theta = min(theta, -z[j] / dz[j])
        for i in range(m2):
            if dy[i] < 0:
                theta = min(theta, -y[i] / dy[i])
            if dw[i] < 0:
                theta = min(theta, -w[i] / dw[i])
        theta *= MARGIN
        x = [x[j] + theta * dx[j] for j in range(n)]
        z = [z[j] + theta * dz[j] for j in range(n)]
        y = [y[i] + theta * dy[i] for i in range(m2)]
        w = [w[i] + theta * dw[i] for i in range(m2)]
    raise ArithmeticError(f"IPM did not converge in {max_iter} iterations")
