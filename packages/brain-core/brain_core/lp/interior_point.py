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
MPC_MARGIN = 0.99    # MPC step-to-boundary margin (Wright ch.10 practice)
TOL = 1e-9
MAX_ITER = 500
DIVERGENCE = 1e10    # Ch.9 blowup heuristic: ||(x,w)|| beyond this x (1+||b||)
                     # with stalled residuals reads as infeasibility (a
                     # diagnostic, never a certificate)


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


def _to_max_form(c, A, b, senses):
    """minimize c.x, A x <sense> b  ->  maximize (-c).x, rows x <= rhs.

    Shared by solve_lp_ipm and solve_lp_ipm_mpc.
    """
    rows: List[List[float]] = []
    rhs: List[float] = []
    for i in range(len(A)):
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
    return rows, rhs, [-float(v) for v in c]


def _fraction_to_boundary(pos, d):
    """Largest alpha <= 1 with pos + alpha*d >= 0 componentwise."""
    alpha = 1.0
    for p, dp in zip(pos, d):
        if dp < 0:
            alpha = min(alpha, -p / dp)
    return alpha


def _least_squares_start(rows, rhs, cmax, n, m2):
    """Mehrotra-style cold start (Wright 1997 ch.11, principle restated).

    The book's two requirements for a start: well centered (pairwise
    products x_i*s_i similar) and not too infeasible (residual norm not
    large relative to the duality measure). The heuristic it describes
    takes the minimum-norm solutions of the two least-squares problems
    (primal equalities; dual equalities) and shifts for positivity.
    In the max-form with slacks the equality matrix is [A' I], so the
    min-norm (x, w) with A'x + w = b is
        w~ = (A'A'^T + I)^-1 b,   x~ = A'^T w~
    and the min-norm (y, z) with A'^T y - z = c is
        y~ = A' (A'^T A' + I)^-1 c,   z~ = -(A'^T A' + I)^-1 c.
    Both normal matrices are SPD (identity shift), solved with the same
    dense elimination as the KKT systems. The unshifted min-norm point
    meets both equality blocks exactly; the positivity shifts then make
    every component strictly positive with a unit margin, leaving small
    controlled residuals (row i: dx*rowsum_i + dw) - the book's "not too
    infeasible" condition.
    """
    # primal min-norm: solve (A A^T + I) t = b ; w = t, x = A^T t
    M = [[sum(rows[i][k] * rows[j][k] for k in range(n)) + (1.0 if i == j else 0.0)
          for j in range(m2)] for i in range(m2)]
    t = _gauss_solve([row[:] for row in M], rhs[:])
    w0 = t[:]
    x0 = [sum(rows[i][j] * t[i] for i in range(m2)) for j in range(n)]
    # dual min-norm: solve (A^T A + I) u = c ; y = A u, z = -u
    N = [[sum(rows[i][j] * rows[i][k] for i in range(m2)) + (1.0 if j == k else 0.0)
          for k in range(n)] for j in range(n)]
    u = _gauss_solve([row[:] for row in N], cmax[:])
    y0 = [sum(rows[i][j] * u[j] for j in range(n)) for i in range(m2)]
    z0 = [-v for v in u]
    # positivity + centrality shifts (unit margin)
    dx = max([0.0] + [-v for v in x0]) + 1.0
    dw = max([0.0] + [-v for v in w0]) + 1.0
    dy = max([0.0] + [-v for v in y0]) + 1.0
    dz = max([0.0] + [-v for v in z0]) + 1.0
    x0 = [v + dx for v in x0]
    w0 = [v + dw for v in w0]
    y0 = [v + dy for v in y0]
    z0 = [v + dz for v in z0]
    return x0, w0, y0, z0


def solve_lp_ipm_mpc(c, A, b, senses, tol: float = TOL,
                     max_iter: int = MAX_ITER, return_iters: bool = False,
                     start: str = "mehrotra"):
    """Mehrotra predictor-corrector IPM (Wright, Primal-Dual Interior-Point
    Methods, SIAM 1997, ch.10 Algorithm MPC) - math rederived, no text copied.

    Same interface and honest scope as solve_lp_ipm (max-form internals,
    floats, feasible+bounded instances only, OPTIMAL or ArithmeticError).
    Differences from the Vanderbei path-following solver above:
      - affine-scaling predictor with target mu=0, then a combined
        centering+corrector step whose complementarity target is
        sigma*mu*e - DAff X/S products (second-order correction);
      - centering sigma chosen adaptively as (mu_aff/mu)^3;
      - separate primal (x,w) and dual (y,z) step lengths;
      - ch.11 least-squares cold start (start="mehrotra", default;
        start="ones" keeps the all-ones start for comparison);
      - relative termination tests (ch.11): residuals scaled by
        1+||b||, 1+||c||, and the relative duality gap;
      - ch.9 blowup diagnostic: diverging iterates with stalled residuals
        raise ArithmeticError mentioning infeasibility - a heuristic
        diagnostic, never a certificate (the exact simplex certifies).
    """
    rows, rhs, cmax = _to_max_form(c, A, b, senses)
    n, m2 = len(cmax), len(rows)
    size = n + m2
    nb = max(abs(v) for v in rhs) if rhs else 0.0
    nc = max(abs(v) for v in cmax) if cmax else 0.0
    scale_p, scale_d = 1.0 + nb, 1.0 + nc

    if start == "mehrotra":
        x, w, y, z = _least_squares_start(rows, rhs, cmax, n, m2)
    elif start == "ones":
        x = [1.0] * n
        w = [1.0] * m2
        y = [1.0] * m2
        z = [1.0] * n
    else:
        raise ValueError(f"bad start {start!r}")

    def kkt_solve(g1, rc, g2, rp, x, y, rows):
        """Solve [Z XA^T; A -Y^-1 W] [dx;dy] = [g1 + X rc; rp - Y^-1 g2]."""
        rhs3 = [g1[j] + x[j] * rc[j] for j in range(n)]
        rhs4 = [rp[i] - g2[i] / y[i] for i in range(m2)]
        K = [[0.0] * size for _ in range(size)]
        for j in range(n):
            K[j][j] = z[j]
        for i in range(m2):
            for j in range(n):
                K[j][n + i] = x[j] * rows[i][j]
                K[n + i][j] = rows[i][j]
        for i in range(m2):
            K[n + i][n + i] = -w[i] / y[i]
        sol = _gauss_solve(K, rhs3 + rhs4)
        return sol[:n], sol[n:]

    iters = 0
    for it in range(max_iter):
        iters = it + 1
        rho = [rhs[i] - sum(rows[i][j] * x[j] for j in range(n)) - w[i]
               for i in range(m2)]
        sig = [cmax[j] - sum(rows[i][j] * y[i] for i in range(m2)) + z[j]
               for j in range(n)]
        gamma = sum(z[j] * x[j] for j in range(n)) + sum(y[i] * w[i] for i in range(m2))
        mu = gamma / (n + m2)
        pobj = sum(cmax[j] * x[j] for j in range(n))
        dobj = sum(rhs[i] * y[i] for i in range(m2))
        rel_gap = abs(dobj - pobj) / (1.0 + abs(pobj))
        # ch.11 relative termination: scaled residuals + relative gap
        if (max((abs(v) for v in rho), default=0.0) / scale_p < tol
                and max((abs(v) for v in sig), default=0.0) / scale_d < tol
                and rel_gap < tol):
            xval = x[:]
            obj = sum(float(c[j]) * xval[j] for j in range(n))
            out = {"status": LPStatus.OPTIMAL, "objective": obj, "x": xval}
            if return_iters:
                out["iters"] = iters
            return out
        # ch.9 blowup diagnostic: iterates diverge when no solution exists
        if sum(abs(v) for v in x) + sum(abs(v) for v in w) > DIVERGENCE * scale_p:
            raise ArithmeticError(
                "IPM iterates diverging with stalled residuals: consistent "
                "with infeasibility (ch.9 blowup diagnostic, not a certificate)"
            )

        # --- affine-scaling predictor: complementarity target g = -XZe ---
        g1 = [-z[j] * x[j] for j in range(n)]
        g2 = [-y[i] * w[i] for i in range(m2)]
        dx_a, dy_a = kkt_solve(g1, sig, g2, rho, x, y, rows)
        dz_a = [sum(rows[i][j] * dy_a[i] for i in range(m2)) - sig[j]
                for j in range(n)]
        dw_a = [g2[i] / y[i] - (w[i] / y[i]) * dy_a[i] for i in range(m2)]

        # hypothetical mu after a full affine step to the boundary
        a_pri = _fraction_to_boundary(x + w, dx_a + dw_a)
        a_dual = _fraction_to_boundary(z + y, dz_a + dy_a)
        mu_aff = (sum((x[j] + a_pri * dx_a[j]) * (z[j] + a_dual * dz_a[j])
                      for j in range(n))
                  + sum((w[i] + a_pri * dw_a[i]) * (y[i] + a_dual * dy_a[i])
                        for i in range(m2))) / (n + m2)
        sigma_c = (mu_aff / mu) ** 3 if mu > 0 else 0.0
        sigma_c = min(max(sigma_c, 0.0), 1.0)

        # --- combined centering+corrector: target sigma*mu e - D_aff products ---
        t1 = [sigma_c * mu - dx_a[j] * dz_a[j] for j in range(n)]
        t2 = [sigma_c * mu - dy_a[i] * dw_a[i] for i in range(m2)]
        zero_n = [0.0] * n
        zero_m = [0.0] * m2
        dx_c, dy_c = kkt_solve(t1, zero_n, t2, zero_m, x, y, rows)
        dz_c = [sum(rows[i][j] * dy_c[i] for i in range(m2)) for j in range(n)]
        dw_c = [t2[i] / y[i] - (w[i] / y[i]) * dy_c[i] for i in range(m2)]

        dx = [dx_a[j] + dx_c[j] for j in range(n)]
        dz = [dz_a[j] + dz_c[j] for j in range(n)]
        dy = [dy_a[i] + dy_c[i] for i in range(m2)]
        dw = [dw_a[i] + dw_c[i] for i in range(m2)]

        # separate primal/dual steps to the boundary, with margin
        theta_p = MPC_MARGIN * _fraction_to_boundary(x + w, dx + dw)
        theta_d = MPC_MARGIN * _fraction_to_boundary(z + y, dz + dy)
        x = [x[j] + theta_p * dx[j] for j in range(n)]
        w = [w[i] + theta_p * dw[i] for i in range(m2)]
        z = [z[j] + theta_d * dz[j] for j in range(n)]
        y = [y[i] + theta_d * dy[i] for i in range(m2)]
    raise ArithmeticError(f"IPM (MPC) did not converge in {max_iter} iterations")
