# Wright — "Recent Developments in Interior-Point Methods" (book chapter, ~2001)

Distilled 2026-11-25 from the user's copy (24 pages, digital text from
dvi, no OCR needed). Read twice. A survey chapter overlapping the
Potra-Wright 2000 paper; the distinctive parts are below.

- Infeasible-interior-point methods as the practical standard: start
  from any (x, y, s) with (x, s) > 0; infeasibilities are reduced at
  the same rate as the duality gap. This is the scheme our LP solver
  implements (Vanderbei ch.17 presents the same iteration).
- Mehrotra's predictor-corrector with Gondzio's higher-order
  corrections is the basis of most LP software; the chapter notes the
  same linear-algebra structure (partial elimination to the
  normal-equations form, sparse Cholesky, dense-column Schur-complement
  handling) as Potra-Wright.
- Special-structure interior-point methods: network-flow LPs solved
  with preconditioned conjugate gradient whose preconditioner comes
  from a spanning tree (Mehrotra-Wang); multicommodity flows and
  stochastic programs via block-angular Schur complements. Documented,
  NOT implemented (our network module uses Ahuja's combinatorial
  algorithms instead).
- Interior-point vs simplex: IPM is faster on large problems and
  parallelizes (the Cholesky dominates); it cannot warm-start, which is
  why simplex keeps its place inside branch-and-bound / branch-and-cut
  (relevant to The-brain's MIP ambitions: LP relaxations there would
  use the simplex, not IPM).
- Semidefinite programming and the KSH/HRVW/M, AHO and NT search
  directions (see the Nesterov-Todd skill); superlinear convergence for
  LP predictor-corrector (Ye et al., Kojima-Shida-Shindoh) requires
  strict complementarity conditions.

Nothing in this chapter adds a new implemented algorithm beyond the
Potra-Wright survey; it corroborates the same framework from a second
source.
