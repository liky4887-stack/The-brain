# Alizadeh, Haeberly & Overton — "Primal-Dual Interior-Point Methods for Semidefinite Programming" (SIAM J. Optim. 8(3), 1998)

Distilled 2026-11-25 from the user's copy (23 pages, digital text, no
OCR needed). Read twice: structure, then deep read of sec. 2 (the
methods), sec. 4-5 (conditioning/stability) and sec. 7 (Mehrotra PC,
numerical results). IMPLEMENTED as brain_core.sdp.solve_sdp_ipm.

## The problem (1.2)-(1.3)

- Primal SDP: min C . X s.t. Ak . X = bk, X psd (A . B = tr AB, all
  matrices symmetric n-by-n). Dual: max b^T y s.t. sum yk Ak + Z = C,
  Z psd. LP is the block-diagonal special case with all block sizes 1.
- Central path (1.4): XZ = mu I; on it X and ZZ commute, with shared
  eigenvectors and lambda_i mu-omega_i -> complementarity (1.9)-(1.10).

## The methods (sec. 2)

- XZ method: Newton on XZ = mu I directly; iterates not symmetric,
  need explicit symmetrization; not strictly a Newton method.
- XZ+ZX method (IMPLEMENTED): symmetrized centering XZ + ZX = 2 mu I
  (2.2), equivalent to (1.4) when X psd; Newton system (2.10) with
  E = Z (sym-kronecker) I, F = X ~ I; Schur complement M = A E^-1 F A^T
  (2.15), nonsymmetric but nonsingular when XZ + ZX pd; the kth column
  of E^-1 F A^T is svec(Gk) with Gk solving the Lyapunov equation
  ZGk + Gk Z = XAk + AkX (2.16), solved in the eigenbasis of Z
  (Appendix: divide by wi + wj). Step lengths (2.18)-(2.19):
  fraction-to-boundary via alpha_hat^-1 = lambda_max(-L^-1 dX L^-T),
  L the Cholesky factor of X.
- NT and X^-1 methods: documented, not implemented (E^-1 F spd for
  those, but the centered function fails to exist at the solution -
  only XZ+ZX is a true Newton method for SDP, sec. 2).
- Mehrotra predictor-corrector (sec. 7, IMPLEMENTED): predictor with
  mu = 0, sigma = ((X+a dX).(Z+b dZ)/(X.Z))^3 (7.1), corrector with
  the dXdZ cross terms in Rc. The paper's experiments: XZ+ZX + PC is
  the most robust and accurate of the tested methods.

## Conditioning and stability (sec. 3-5, drives the stopping rule)

- The Jacobian is nonsingular at the solution under nondegeneracy for
  XZ+ZX and Q; the Schur complement M has UNBOUNDED condition number
  on the central path - float64 iterates cannot keep a numerically
  zero boundary eigenvalue positive forever. Our implementation
  therefore stops on the RELATIVE gap (paper's tables report digits of
  accuracy, not absolute mu) and treats a Cholesky failure at a
  numerically-zero eigenvalue (checked by the eigensolver) as the
  float boundary: small gap -> optimal, otherwise honest stall error.

## Validation (tests/test_sdp_ipm.py)

Locked rank-one 2x2 optimum (z = 1 at X = [[1,-1],[-1,1]]); 15 planted
strictly complementary KKT points (planted complementary X*, Z* are
optimal by convexity; worst relative objective error 4.8e-7); diagonal
SDP = LP cross-checked against the exact simplex; MAXCUT relaxation on
a 7-edge 5-node graph bounds the brute-force maximum cut; full KKT
residual checks (primal/dual feasibility, psd cones, complementarity).
