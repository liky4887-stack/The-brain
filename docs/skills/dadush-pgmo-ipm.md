# Dadush — "Primal-Dual Interior Point Methods" (PGMO Lectures, 2025)

Distilled 2026-11-25 from the user's copy (14 pages, pdfTeX digital,
no OCR needed). Read twice. Daniel Dadush's lecture on primal-dual
IPMs and the geometry of LPs.

## Content

- LP duality refresher: strong duality, gap formula <c,x> - <y,b> =
  <s,x>, complementary slackness x_i s_i = 0; IPMs relax this to
  x_i s_i = mu > 0 and drive mu to 0.
- Primal-dual central path as optimal solutions of the parametric
  barrier problems; the beta-neighborhood of the path.
- Algorithm 1: feasible-start Predictor-Corrector IPM (MTY-style;
  requires an initial iterate in the beta-neighborhood) with
  convergence analysis (Theorem 6). Documented, NOT implemented: our
  LP solver (Vanderbei ch.17) is the infeasible-start variant, which
  needs no known centered starting point - the lecture's initialization
  section (sec. 4) discusses exactly this gap.
- Straight-line complexity: a combinatorial measure of LP complexity
  from the geometry of the central path; basis of the first
  strongly-polynomial algorithm for LPs with at most two variables per
  inequality (ADL+22, DKN+24) and of examples where IPMs need
  exponentially many iterations in the dimension (ABGJ18, AGV22).
  Theory only - no algorithm within The-brain's current scope.

Status: corroborates the implemented LP path-following stack from a
modern geometric viewpoint; nothing new implemented.
