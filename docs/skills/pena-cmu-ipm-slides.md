# Pena — "Primal-Dual Interior-Point Methods" (CMU 10-725/36-725 Convex Optimization lecture slides)

Distilled 2026-11-25 from the user's copy (26 Beamer pages, pdfTeX
digital, no OCR needed). Read twice. Javier Pena's lecture slides.

## Content

- Setup: min f(x) s.t. Ax = b, h(x) <= 0, convex and differentiable,
  strong duality; KKT: grad f + grad h u + A^T v = 0, U h(x) = 0,
  u, -h(x) >= 0.
- Barrier problem min f(x) + tau phi(x) with
  phi(x) = -sum log(-h_i(x)); optimality U h(x) = -tau 1; the
  central-path point has duality gap exactly m*tau.
- Barrier vs primal-dual: one Newton step per iteration (no inner
  centering loop), iterates not necessarily feasible, typically more
  efficient, better-than-linear convergence under suitable conditions -
  this is precisely the Gould et al. Algorithm 4.1 our
  brain_core.nlp.solve_nlp_ipm implements (same central-path equations,
  same Newton system, up to sign conventions: our Cz = mu e is their
  Uh(x) + tau 1 = 0).
- Newton step for the central-path equations, then the LP special case
  and an SDP extension outline.

Status: corroborates the implemented NLP and LP solvers; nothing new
implemented.
