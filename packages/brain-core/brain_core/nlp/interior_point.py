"""Primal-dual interior-point method for nonlinear programming.

Source: Gould, Orban, Sartenaer & Toint, "Superlinear convergence of
primal-dual interior point algorithms for nonlinear programming"
(RAL-TR-2000-014 / SIAM J. Optim.), Algorithm 4.1 with the optimality
system (2.6), Jacobian (2.15) and the block B(x,z) = J^T C^-1 Z J of
(4.37).

Problem:  min f(x)  s.t.  A x = b,  c(x) >= 0
Lagrangian: L = f(x) + (Ax - b)^T y - c(x)^T z.
Perturbed KKT (2.6):  grad_x L = 0,  Ax - b = 0,  C z = mu e,
with (c(x), z) > 0.

Outer iteration (Algorithm 4.1): for the current barrier parameter mu,
take primal-dual Newton steps on the system above (fraction-to-boundary
steps keep (c(x), z) > 0) until the forcing conditions
    ||C z - mu e||_inf <= KAPPA * mu  and  ||grad_x L||_inf <= KAPPA * mu
hold (forcing functions eps_C(mu) = eps_D(mu) = KAPPA * mu; the paper
allows any forcing functions). Then mu <- mu^Q_RATE with Q_RATE = 1.5:
the paper's main result is that the decrease may be chosen arbitrarily
close to quadratic, giving componentwise Q-superlinear convergence.

Honest simplifications and scope:
- The paper measures the dual residual in a preconditioned seminorm
  ((2.17) with a second-order sufficient M_k); we use the plain
  infinity norm of the full stationarity residual, which is the
  M-independent practical choice and never weaker for convergence
  detection.
- This is a LOCAL method: it needs a starting point with c(x0) > 0
  (strictly); a point on the manifold Ax = b is found by a minimum-norm
  correction when A has full row rank. There is no global convergence
  machinery (no trust region, no filter, no merit line search beyond
  fraction-to-boundary) and no infeasibility detection: nonconvex f or
  c can converge to a local KKT point or fail loudly. Convex problems
  with a strictly feasible start are the supported class.
- Floats; no certificates.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

DELTA_Q = 1.5        # barrier decrease exponent (superlinear regime)
KAPPA = 0.1          # forcing constant: inner tolerance KAPPA * mu
MARGIN = 0.9         # fraction-to-boundary margin
TOL = 1e-9
MU0 = 0.1            # initial barrier parameter
MAX_OUTER = 100
MAX_INNER = 100


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


def solve_nlp_ipm(
    f: Callable[[Sequence[float]], float],
    grad_f: Callable[[Sequence[float]], List[float]],
    hess_f: Callable[[Sequence[float]], List[List[float]]],
    cons: Sequence[Callable[[Sequence[float]], float]],
    jac: Callable[[Sequence[float]], List[List[float]]],
    hess_c: Sequence[Callable[[Sequence[float]], List[List[float]]]],
    A: Optional[Sequence[Sequence[float]]] = None,
    b: Optional[Sequence[float]] = None,
    x0: Optional[Sequence[float]] = None,
    n: Optional[int] = None,
    tol: float = TOL,
    mu0: float = MU0,
) -> dict:
    """Minimize f(x) s.t. A x = b, c(x) >= 0 by Algorithm 4.1.

    cons is the list of inequality functions c_i(x) (need c(x) >= 0),
    jac(x) returns the p-by-n Jacobian J, hess_c[i](x) the Hessian of
    c_i. Returns {"status", "objective", "x", "y", "z"}.
    """
    Af = [[float(v) for v in row] for row in (A or [])]
    bf = [float(v) for v in (b or [])]
    m = len(Af)
    p = len(cons)
    if n is None:
        if x0 is None:
            raise ValueError("give x0 or n")
        n = len(x0)
    if x0 is None:
        x = [1.0] * n
    else:
        x = [float(v) for v in x0]
    if len(bf) != m:
        raise ValueError("A and b row-count mismatch")
    for row in Af:
        if len(row) != n:
            raise ValueError("every row of A must have n entries")

    # Minimum-norm correction onto Ax = b: x += A^T (A A^T)^-1 (b - A x).
    if m:
        res = [bf[i] - sum(Af[i][j] * x[j] for j in range(n)) for i in range(m)]
        if max(abs(v) for v in res) > 1e-10:
            G = [
                [sum(Af[i][k] * Af[r][k] for k in range(n)) for r in range(m)]
                for i in range(m)
            ]
            try:
                lam = _gauss_solve(G, res)
            except ArithmeticError as exc:
                raise ArithmeticError(
                    "A does not have full row rank - cannot find a "
                    "point on Ax = b"
                ) from exc
            x = [
                x[j] + sum(Af[i][j] * lam[i] for i in range(m))
                for j in range(n)
            ]

    cv = [float(g(x)) for g in cons]
    if any(v <= 0.0 for v in cv):
        raise ArithmeticError(
            "starting point is not strictly feasible for c(x) >= 0 - "
            "this is a local method needing c(x0) > 0"
        )
    y = [0.0] * m
    z = [mu0 / v for v in cv]  # on the central path at mu0
    mu = mu0

    def kkt_rows(xv, yv, zv, mu_t):
        """Residuals and Newton system blocks at (xv, yv, zv)."""
        g = grad_f(xv)
        J = jac(xv) if p else []
        Hf = hess_f(xv)
        # grad_x L = grad f + A^T y - J^T z
        gL = [
            g[j] + sum(Af[i][j] * yv[i] for i in range(m))
            - sum(J[i][j] * zv[i] for i in range(p))
            for j in range(n)
        ]
        cvals = [float(h(xv)) for h in cons]
        # H = hess f - sum_i z_i hess c_i
        H = [
            [
                Hf[r][cc] - sum(zv[i] * hess_c[i](xv)[r][cc] for i in range(p))
                for cc in range(n)
            ]
            for r in range(n)
        ]
        rp = [sum(Af[i][j] * xv[j] for j in range(n)) - bf[i] for i in range(m)]
        rc = [cvals[i] * zv[i] - mu_t for i in range(p)]
        return gL, rp, rc, J, H, cvals

    status: Optional[str] = None
    for _outer in range(MAX_OUTER):
        # Inner minimization: drive the mu-perturbed KKT residuals down.
        done = False
        for _inner in range(MAX_INNER):
            gL, rp, rc, J, H, cvals = kkt_rows(x, y, z, mu)
            res_stat = max(abs(v) for v in gL)
            res_comp = max((abs(v) for v in rc), default=0.0)
            res_prim = max((abs(v) for v in rp), default=0.0)
            if (
                res_stat <= KAPPA * mu
                and res_comp <= KAPPA * mu
                and res_prim <= max(KAPPA * mu, 1e-12)
            ):
                done = True
                break
            # Newton system (2.15). Eliminate
            # dz = C^-1 (mu e - C z) - C^-1 Z J dx, giving
            #   (H + J^T C^-1 Z J) dx + A^T dy = -gL + J^T (mu C^-1 e - z)
            #   A dx = -rp
            K = [[0.0] * (n + m) for _ in range(n + m)]
            rhs = [0.0] * (n + m)
            for r in range(n):
                for cc in range(n):
                    K[r][cc] = H[r][cc] + sum(
                        J[i][r] * z[i] * J[i][cc] / cvals[i] for i in range(p)
                    )
                rhs[r] = -gL[r] + sum(
                    J[i][r] * (mu / cvals[i] - z[i]) for i in range(p)
                )
            for i in range(m):
                for j in range(n):
                    K[j][n + i] = Af[i][j]
                    K[n + i][j] = Af[i][j]
                rhs[n + i] = -rp[i]
            try:
                d = _gauss_solve(K, rhs)
            except ArithmeticError as exc:
                raise ArithmeticError(
                    "singular KKT system in the inner iteration - "
                    "try a different starting point"
                ) from exc
            dx, dy = d[:n], d[n:]
            dz = [
                (mu - cvals[i] * z[i]) / cvals[i]
                - (z[i] / cvals[i]) * sum(J[i][j] * dx[j] for j in range(n))
                for i in range(p)
            ]
            # Fraction-to-boundary on (c(x), z); c is nonlinear, so
            # backtrack on the primal step until c stays positive.
            theta = 1.0
            for i in range(p):
                if dz[i] < 0.0:
                    theta = min(theta, -z[i] / dz[i])
            theta = min(1.0, MARGIN * theta)
            for _ls in range(60):
                xn = [x[j] + theta * dx[j] for j in range(n)]
                if all(float(g(xn)) > 0.0 for g in cons):
                    break
                theta *= 0.5
            else:
                raise ArithmeticError(
                    "backtracking failed - iterate left the feasible interior"
                )
            if theta <= 0.0:
                raise ArithmeticError("no positive step - stalled")
            x = xn
            y = [y[i] + theta * dy[i] for i in range(m)]
            z = [z[i] + theta * dz[i] for i in range(p)]
        if not done:
            raise ArithmeticError(
                f"inner iteration did not meet the forcing conditions "
                f"for mu={mu:g} within {MAX_INNER} Newton steps"
            )
        if mu <= tol:
            status = "optimal"
            break
        mu = mu ** DELTA_Q  # superlinear decrease (paper's main result)
        if mu < tol * 1e-3:
            mu = tol * 1e-3
    if status is None:
        raise ArithmeticError(f"no convergence in {MAX_OUTER} outer iterations")
    # Final full-KKT check at mu = 0 tolerance scale.
    gL, rp, rc, _, _, _ = kkt_rows(x, y, z, 0.0)
    if max(abs(v) for v in gL) > 1e-4 or max((abs(v) for v in rp), default=0.0) > 1e-6:
        raise ArithmeticError("final iterate failed the KKT residual check")
    return {
        "status": status,
        "objective": float(f(x)),
        "x": x,
        "y": y,
        "z": z,
    }
