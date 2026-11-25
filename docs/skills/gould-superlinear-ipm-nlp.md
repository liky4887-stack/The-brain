# Gould, Orban, Sartenaer & Toint — "Superlinear convergence of primal-dual interior point algorithms for nonlinear programming" (RAL-TR-2000-014, 2000)

Distilled 2026-11-25 from the user's copy (32 pages, digital, no OCR
needed). Read twice: structure, then deep read of sec. 2 (notation,
optimality conditions) and sec. 4 (Algorithm 4.1); sec. 5-6 (the
local analysis proving superlinear convergence) read for the parameter
requirements.

## The algorithm class (sec. 4, IMPLEMENTED)

- NLP: min f(x) s.t. Ax = b, c(x) >= 0 (f, c smooth, possibly
  nonconvex). Lagrangian L = f + (Ax-b)^T y - c^T z.
- Perturbed primal-dual KKT (2.6): grad_x L = 0, Ax - b = 0, Cz = mu e,
  (c(x), z) > 0; Jacobian (2.15) with blocks
  [L_xx, A^T, -J^T; A, 0, 0; ZJ, 0, C].
- Barrier-subproblem view: minimizing the log-barrier phi(x, mu) under
  Ax = b is equivalent to (2.6) with z = mu C^-1 e (the primal-dual
  correspondence (2.9)-(2.13)).
- Algorithm 4.1 (outer iteration): for mu_k, run an inner minimization
  - primal-dual Newton on (2.6) - stopping as soon as
  ||Cz - mu_k e|| <= eps_C(mu_k) and ||grad_x f - J^T z|| <= eps_D(mu_k)
  (forcing functions); then choose mu_{k+1} < mu_k and repeat.
  Iterates stay on the manifold Ax = b; multipliers y are recovered
  from (4.45) and never used by the algorithm itself.
- The block B(x,z) = J^T C^-1 Z J (4.37) and V = L_xx + B (4.39) are
  the curvature the Newton system acts on.

## Superlinear convergence (sec. 5-6, the paper's point)

- Under a second-order sufficiency condition, LICQ and strict
  complementarity (AS1-AS6), and forcing functions tied to mu (5.59),
  one Newton system per barrier parameter suffices asymptotically.
- The outer sequence {w_k} converges componentwise Q-superlinearly, and
  the rate may be chosen arbitrarily close to quadratic by making
  mu_{k+1} decrease nearly quadratically.

## Implementation (brain_core.nlp.solve_nlp_ipm)

Follows Algorithm 4.1 with eps_C(mu) = eps_D(mu) = 0.1 mu (infinity
norm of the full stationarity residual - the paper's preconditioned
seminorm (2.17) simplified, documented in the module docstring) and
mu_{k+1} = mu_k^1.5 (superlinear regime, close-to-quadratic allowed).
Fraction-to-boundary (margin 0.9) with backtracking on nonlinear c.
Honest scope: LOCAL method - needs c(x0) > 0 strictly (a violating
start raises ArithmeticError, verified by test); minimum-norm
correction finds a point on Ax = b (full row rank required); no trust
region / filter / global machinery; no infeasibility detection;
nonconvex problems may hit a local KKT point or fail loudly. Convex
problems with strictly feasible starts are the supported class.
Validated in tests/test_nlp_ipm.py: three locked convex problems with
known optima (linear equality, active linear inequality, nonlinear
inequality projection), agreement with brain_core.qp on 15 random
quadratic objectives, full KKT residual checks, and the loud rejection
of an infeasible start.
