"""Primal-dual interior-point method for semidefinite programming.

Source: Alizadeh, Haeberly & Overton, "Primal-Dual Interior-Point
Methods for Semidefinite Programming: Convergence Rates, Stability and
Numerical Results" (SIAM J. Optim. 8(3), 1998). Implements the XZ+ZX
method (their recommended variant - "more robust ..., converges more
rapidly, and achieves higher accuracy") with Mehrotra's
predictor-corrector rule (their eq. 7.1, exponent 3).

Problem (1.2)/(1.3):
    primal: min C . X  s.t.  Ak . X = bk (k=1..m),  X psd
    dual:   max b^T y  s.t.  sum_k yk Ak + Z = C,   Z psd
(A . B = tr AB; all matrices symmetric n-by-n.)

Central path (1.4): XZ = mu I, symmetrized as XZ + ZX = 2 mu I (2.2),
equivalent when X psd. Newton system (2.10) solved via the Schur
complement (2.12)-(2.15): the kth column of E^-1 F A^T is svec(Gk)
with Gk the solution of the Lyapunov equation ZGk + Gk Z = XAk + AkX
(2.16). Step lengths by fraction-to-boundary (2.18)-(2.19): the bound
is the reciprocal of the largest eigenvalue of -L^-1 dX L^-T with L
the Cholesky factor of X. Mehrotra predictor-corrector: predictor with
mu = 0, sigma = ((X+a dX).(Z+b dZ) / (X.Z))^3 (7.1), corrector with
the dXdZ cross terms in Rc.

Numerical kernels are pure Python (no numpy in brain-core): Jacobi
eigenvalue iteration for symmetric matrices and a Cholesky
factorization. The Lyapunov equation ZG + GZ = B with Z pd is solved
in the eigenbasis of Z (paper's Appendix): denominators wi + wj > 0.

Honest scope: dense, small-to-moderate n (each iteration costs
O(m n^3 + m^2 n^2)); floats; feasible-and-bounded instances with a
strictly feasible dual start built internally (X = eta I, Z = eta I);
no infeasibility certificates. LP is the diagonal special case
(paper's remark): cross-validated against brain_core.lp.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

TAU = 0.9            # fraction-to-boundary margin (2.18)
TOL = 1e-7           # relative duality-gap tolerance
MAX_ITER = 100


# ---------- small dense matrix kernels ----------

def _matmul(A, B):
    n, p, q = len(A), len(B), len(B[0])
    out = [[0.0] * q for _ in range(n)]
    for i in range(n):
        Ai = A[i]
        oi = out[i]
        for k in range(p):
            a = Ai[k]
            if a != 0.0:
                Bk = B[k]
                for j in range(q):
                    oi[j] += a * Bk[j]
    return out


def _transpose(A):
    return [list(col) for col in zip(*A)]


def _dot(A, B):
    """Frobenius inner product A . B = tr AB for same-shape matrices."""
    return sum(a * b for ra, rb in zip(A, B) for a, b in zip(ra, rb))


def _cholesky(A):
    """Lower Cholesky factor of a positive definite matrix."""
    n = len(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s <= 0.0:
                    raise ArithmeticError("matrix not positive definite")
                L[i][j] = math.sqrt(s)
            else:
                L[i][j] = s / L[j][j]
    return L


def _jacobi_eig(A, sweeps: int = 100, eps: float = 1e-15):
    """Eigenvalues and eigenvectors of a symmetric matrix (Jacobi).

    Returns (evals, Q) with A = Q diag(evals) Q^T, evals ascending.
    """
    n = len(A)
    a = [row[:] for row in A]
    Q = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(sweeps):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off < eps:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < eps * 0.1:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(1.0 + theta * theta))
                c = 1.0 / math.sqrt(1.0 + t * t)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(n):
                    qkp, qkq = Q[k][p], Q[k][q]
                    Q[k][p] = c * qkp - s * qkq
                    Q[k][q] = s * qkp + c * qkq
    evals = [a[i][i] for i in range(n)]
    order = sorted(range(n), key=lambda i: evals[i])
    evals_s = [evals[i] for i in order]
    Q_s = [[Q[r][i] for i in order] for r in range(n)]
    return evals_s, Q_s


def _lyapunov(Z, B, z_eig=None):
    """Solve Z G + G Z = B for symmetric G, Z positive definite.

    Uses the eigenbasis of Z (paper's Appendix): with Z = Q W Q^T,
    G = Q C Q^T where C_ij = (Q^T B Q)_ij / (w_i + w_j).
    """
    n = len(Z)
    if z_eig is None:
        w, Q = _jacobi_eig(Z)
    else:
        w, Q = z_eig
    QtB = _matmul(_transpose(Q), B)
    QtBQ = _matmul(QtB, Q)
    C = [
        [QtBQ[i][j] / (w[i] + w[j]) for j in range(n)]
        for i in range(n)
    ]
    return _matmul(_matmul(Q, C), _transpose(Q))


def _step_bound(L, D):
    """sup{alpha : X + alpha D psd} with L the Cholesky factor of X.

    alpha_hat^-1 = lambda_max(-L^-1 D L^-T) (2.19); infinite if D psd.
    """
    n = len(L)
    # T = L^-1 D by forward substitution on columns
    T = [[0.0] * n for _ in range(n)]
    for j in range(n):
        for i in range(n):
            s = D[i][j] - sum(L[i][k] * T[k][j] for k in range(i))
            T[i][j] = s / L[i][i]
    # M = T L^-T: solve M L^T = T by substitution on rows
    M = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            s = T[i][j] - sum(M[i][k] * L[j][k] for k in range(j))
            M[i][j] = s / L[j][j]
    Msym = [[0.5 * (M[i][j] + M[j][i]) for j in range(n)] for i in range(n)]
    evals, _ = _jacobi_eig(Msym)
    lam_max = -evals[0]  # lambda_max(-M) = -lambda_min(M)
    if lam_max <= 1e-14:
        return float("inf")
    return 1.0 / lam_max


def _gauss_solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-300:
            raise ArithmeticError("singular Schur complement")
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


# ---------- the solver ----------

def solve_sdp_ipm(C, A_list, b, tol: float = TOL, max_iter: int = MAX_ITER) -> dict:
    """Minimize C . X s.t. Ak . X = bk, X psd (XZ+ZX, Mehrotra PC).

    Returns {"status", "objective", "dual_objective", "X", "y", "Z"}.
    Only "optimal" is returned on success; failures raise
    ArithmeticError (no certificates - see the module docstring).
    """
    n = len(C)
    m = len(A_list)
    if len(b) != m:
        raise ValueError("A_list and b length mismatch")
    Cf = [[float(v) for v in row] for row in C]
    if any(len(row) != n for row in Cf):
        raise ValueError("C must be square")
    As = []
    for k, A in enumerate(A_list):
        if len(A) != n or any(len(row) != n for row in A):
            raise ValueError(f"A[{k}] must be {n}x{n}")
        # symmetrize: only the symmetric part matters for A . X
        As.append([[0.5 * (float(A[i][j]) + float(A[j][i]))
                    for j in range(n)] for i in range(n)])
    bf = [float(v) for v in b]

    # Strictly positive start; residuals carried (infeasible start).
    X = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    y = [0.0] * m
    Z = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    def residuals(X, y, Z, mu, dX=None, dZ=None):
        Rd = [[Cf[i][j] - Z[i][j] - sum(y[k] * As[k][i][j] for k in range(m))
               for j in range(n)] for i in range(n)]
        rp = [bf[k] - _dot(As[k], X) for k in range(m)]
        XZ = _matmul(X, Z)
        ZX = _matmul(Z, X)
        Rc = [[mu * (1.0 if i == j else 0.0) - 0.5 * (XZ[i][j] + ZX[i][j])
               for j in range(n)] for i in range(n)]
        if dX is not None and dZ is not None:
            cross1 = _matmul(dX, dZ)
            cross2 = _matmul(dZ, dX)
            for i in range(n):
                for j in range(n):
                    Rc[i][j] -= 0.5 * (cross1[i][j] + cross2[i][j])
        return Rd, rp, Rc

    def newton_step(X, y, Z, mu, dX=None, dZ=None):
        """One Newton step of (2.10) via (2.12)-(2.15)."""
        Rd, rp, Rc = residuals(X, y, Z, mu, dX, dZ)
        z_eig = _jacobi_eig(Z)
        # Schur complement M (nonsymmetric for XZ+ZX), (2.15)-(2.16)
        Gcols = []
        for k in range(m):
            XAk = _matmul(X, As[k])
            AkX = _matmul(As[k], X)
            B = [[XAk[i][j] + AkX[i][j] for j in range(n)] for i in range(n)]
            Gcols.append(_lyapunov(Z, B, z_eig))
        M = [[_dot(As[l], Gcols[k]) for k in range(m)] for l in range(m)]
        # rhs of (2.12): rp + A E^-1 (F rd - rc)
        XRd = _matmul(X, Rd)
        RdX = _matmul(Rd, X)
        W = [[XRd[i][j] + RdX[i][j] - Rc[i][j] for j in range(n)] for i in range(n)]
        G = _lyapunov(Z, W, z_eig)
        rhs = [rp[k] + _dot(As[k], G) for k in range(m)]
        try:
            dy = _gauss_solve(M, rhs) if m else []
        except ArithmeticError as exc:
            raise ArithmeticError(
                "Schur complement singular - constraints may be "
                "linearly dependent or the problem degenerate"
            ) from exc
        # (2.14): dZ = Rd - sum dyk Ak
        dZ = [[Rd[i][j] - sum(dy[k] * As[k][i][j] for k in range(m))
               for j in range(n)] for i in range(n)]
        # (2.13): Z dX + dX Z = Rc - (X dZ + dZ X)
        XdZ = _matmul(X, dZ)
        dZX = _matmul(dZ, X)
        B = [[Rc[i][j] - XdZ[i][j] - dZX[i][j] for j in range(n)] for i in range(n)]
        dX = _lyapunov(Z, B, z_eig)
        # symmetrize (numerical noise)
        dX = [[0.5 * (dX[i][j] + dX[j][i]) for j in range(n)] for i in range(n)]
        return dX, dy, dZ

    def lengths(X, Z, dX, dZ):
        # On a Cholesky failure the iterate has reached a numerically
        # zero eigenvalue (expected on the boundary of the psd cone):
        # check with the eigensolver whether it is truly indefinite
        # (raise) or just numerically semidefinite (bound 0).
        def floor_check(M):
            evals, _ = _jacobi_eig(M)
            scale = 1.0 + max(abs(M[i][i]) for i in range(len(M)))
            if evals[0] < -1e-9 * scale:
                raise ArithmeticError("iterate not positive definite - stalled")
            return 0.0
        try:
            LX = _cholesky(X)
            a_hat = _step_bound(LX, dX)
        except ArithmeticError:
            a_hat = floor_check(X)
        try:
            LZ = _cholesky(Z)
            b_hat = _step_bound(LZ, dZ)
        except ArithmeticError:
            b_hat = floor_check(Z)
        alpha = min(1.0, TAU * a_hat)
        beta = min(1.0, TAU * b_hat)
        return alpha, beta

    status: Optional[str] = None
    scale_r = 1.0 + max(abs(v) for v in bf) if m else 1.0
    scale_d = 1.0 + max(abs(v) for row in Cf for v in row)
    for _ in range(max_iter):
        gap = _dot(X, Z)
        obj = _dot(Cf, X)
        dobj = sum(bf[k] * y[k] for k in range(m))
        Rd, rp, _ = residuals(X, y, Z, 0.0)
        res_d = max(abs(v) for row in Rd for v in row)
        res_p = max((abs(v) for v in rp), default=0.0)
        rel_gap = gap / (1.0 + abs(obj) + abs(dobj))
        if rel_gap <= tol and res_d <= 1e-6 * scale_d and res_p <= 1e-6 * scale_r:
            status = "optimal"
            break
        # Predictor (mu = 0)
        dX_p, dy_p, dZ_p = newton_step(X, y, Z, 0.0)
        alpha_p, beta_p = lengths(X, Z, dX_p, dZ_p)
        if (alpha_p <= 0.0 or beta_p <= 0.0) and rel_gap > 100 * tol:
            raise ArithmeticError("no positive step - stalled far from optimal")
        Xp = [[X[i][j] + alpha_p * dX_p[i][j] for j in range(n)] for i in range(n)]
        Zp = [[Z[i][j] + beta_p * dZ_p[i][j] for j in range(n)] for i in range(n)]
        gap_aff = _dot(Xp, Zp)
        sigma = (gap_aff / gap) ** 3 if gap > 0.0 else 0.0  # (7.1)
        mu = sigma * gap / n
        # Corrector with the dXdZ cross terms in Rc
        dX, dy, dZ = newton_step(X, y, Z, mu, dX_p, dZ_p)
        alpha, beta = lengths(X, Z, dX, dZ)
        if alpha <= 0.0 or beta <= 0.0:
            # At the float boundary of the psd cone: if the relative
            # gap is already small, that is the best float64 can do.
            if rel_gap <= 100 * tol:
                status = "optimal"
                break
            raise ArithmeticError("no positive step - stalled far from optimal")
        X = [[X[i][j] + alpha * dX[i][j] for j in range(n)] for i in range(n)]
        y = [y[k] + beta * dy[k] for k in range(m)]
        Z = [[Z[i][j] + beta * dZ[i][j] for j in range(n)] for i in range(n)]
    if status is None:
        raise ArithmeticError(f"no convergence in {max_iter} iterations")
    obj = _dot(Cf, X)
    dobj = sum(bf[k] * y[k] for k in range(m))
    return {
        "status": status,
        "objective": obj,
        "dual_objective": dobj,
        "X": X,
        "y": y,
        "Z": Z,
    }
