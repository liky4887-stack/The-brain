# Potra & Wright — "Interior-Point Methods" (J. Comput. Appl. Math. 124, 2000)

Distilled 2026-11-25 from the user's copy (21 pages, digital text from
dvi, no OCR needed). Read twice: structure, then deep read of sec. 2
(LP path-following and Mehrotra) and sec. 3 (QP and monotone LCP).

## LP framework (sec. 2)

- Primal-dual central path for LP in standard form; Newton on the
  perturbed KKT system (2.8)-(2.10) with centering sigma and target mu.
- Infeasible-interior-point methods: residuals of the equality rows are
  driven to zero alongside complementarity - the practical variant, and
  the one our LP solver (Vanderbei ch.17) implements.
- Mehrotra's predictor-corrector (sec. 2, after (2.11)): adaptive sigma
  chosen by first solving the pure affine (sigma = 0) direction; small
  sigma when it makes good progress, more centering otherwise. Gondzio's
  higher-order corrections reuse the factorization with extra right-hand
  sides. Documented, NOT implemented (the paper sketches it; our crisp
  source for LP path-following remains Vanderbei ch.17).
- Linear algebra (2.16)-(2.17): eliminate ds for the bordered system,
  or ds and dx for the normal-equations form A S^-1 X A^T dy = t with
  sparse Cholesky; ill-conditioning as mu -> 0 is expected and patched.

## Convex QP (sec. 3, IMPLEMENTED)

- Problem (3.18): min c^T x + (1/2) x^T Q x s.t. Ax = b, x >= 0, Q psd.
- Search-direction system identical to the LP one with Q added to the
  stationarity block; SAME step length for primal and dual variables
  (unlike LP, where they usually differ).
- Implemented as brain_core.qp.solve_qp_ipm (infeasible-start path
  following, delta = 0.1, fraction-to-boundary margin 0.9, one step
  length). Cross-validated in tests/test_qp_ipm.py against an
  independent active-set enumeration oracle (40 random PSD QPs) and
  against the exact simplex when Q = 0 (20 random LPs).

## Monotone LCP (sec. 3, documented not implemented)

- My + Nz = q, (y,z) >= 0, y^T z = 0 with the monotonicity property;
  KKT conditions of LP and convex QP are mixed monotone LCPs.
- Central path My + Nz = q, YZe = mu e; same algorithmic framework.
- Sufficient-matrix extension P*(kappa): complexity depends on kappa;
  Potra-Sheng large-step infeasible IPM. Not implemented.

## Rest (structure read, do not cite details)

Sec. 4 semidefinite programming; sec. 5 self-concordant barriers and
nonlinear problems; complexity: O(sqrt(n) L) short-step, probabilistic
O(sqrt(n) ln n) (Anstreicher et al.).
