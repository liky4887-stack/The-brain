# Nesterov & Todd — "Primal-Dual Interior-Point Methods for Self-Scaled Cones" (SIAM J. Optim. 8, 1998)

Distilled 2026-11-25 from the user's copy (35 pages, digital, no OCR
needed). Read twice: structure, then deep read of the introduction and
sec. 2 (definitions). Pure theory; nothing implemented from it.

## Content

- Conic programming: minimize a linear objective over the intersection
  of an affine subspace with a closed convex cone K, with the dual over
  the dual cone. LP (nonnegative orthant), convex quadratically
  constrained QP (Lorentz/second-order cones) and SDP (positive
  semidefinite cone) all fit.
- Self-scaled cones (= symmetric cones, a later result cited in the
  introduction): admit a nu-self-scaled barrier F. Given one point in
  the primal cone interior and one in the dual cone interior, there is
  a UNIQUE scaling point w at which the Hessian F''(w) maps one point
  to the other - the scalings come from Hessians at points of the cone
  itself, hence "self-scaled".
- That scaling gives a symmetric primal-dual Newton direction (the
  Nesterov-Todd direction): affine-scaling and centering directions
  generalized to any self-scaled cone (sec. 5).
- Algorithms: short- and long-step symmetric primal-dual path-following
  methods using several proximity measures (sec. 6, extending
  Monteiro-Adler and Kojima-Mizuno-Yoshise; an MTY-style
  predictor-corrector with adaptive step size), and a
  functional-proximity predictor-corrector variant (sec. 7). Efficiency
  estimates match the LP bounds; two of the algorithms take steps going
  a large fraction of the way to the boundary.
- Third-derivative properties of self-scaled barriers give good
  approximations valid up to a constant fraction of the distance to the
  boundary (not just in unit local-norm balls) - the analytic engine
  behind the long steps.

## Status for The-brain

Documented, NOT implemented. A conic/SDP solver needs symmetric-cone
linear algebra (scaling point, spectral functions) well beyond the
dense float Gaussian elimination in the repo. If SDP ever enters scope,
this paper plus the Wright survey's sec. 4 are the starting points.
