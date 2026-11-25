# Wright — Primal-Dual Interior-Point Methods (SIAM 1997)

Distilled 2026-11-26 from the user's full copy (the 1997 SIAM monograph,
digital text). Read targeted to the task: ch.1 (framework and KKT system),
ch.9 (detecting infeasibility), ch.10 (Mehrotra's predictor-corrector,
the algorithm modern codes are built on), ch.11 (implementation: step
equations, starting points, termination, hot starts). Math rederived and
restated; no text copied. Note: this book had been dropped from the list
earlier in the day; the user re-sent it at 1:29 AM as a book he was
missing.

## Relation to what was already here

- vanderbei-linear-programming.md covers the central path and a
  fixed-centering path-following method (implemented as
  brain_core.lp.interior_point.solve_lp_ipm). Wright 1997 is the
  deeper reference on the SAME primal-dual family: it explains why the
  fixed-centering step is slow and what production codes do instead.
- potra-wright-interior-point-methods.md (2000 survey) overlaps in
  scope; this book is the fuller algorithmic treatment.

## The framework (ch.1), in the repo's notation

Standard form min c^T x, Ax = b, x >= 0; dual max b^T y, A^T y + s = c,
s >= 0. Optimality = the three equality blocks: primal feasibility
Ax - b = 0, dual feasibility A^T y + s - c = 0, complementarity
XSe = 0, with (x, s) >= 0 the only inequalities. Primal-dual methods
apply Newton's method to the equalities and shorten each step so
(x, s) > 0 strictly throughout - the strictness is what keeps spurious
(non-complementary-sign) solutions out of the search region.

The step equations at barrier target sigma*mu reduce to three
equivalent linear systems (ch.11): the unreduced KKT block, the
augmented system (symmetric indefinite), and the normal-equations form
AD^2A^T with D = S^{-1/2}X^{1/2} (symmetric positive definite, sparse
Cholesky-friendly - what real codes factor once per iteration; the
augmented form is more stable when D's diagonal spreads to extremes).
The repo's teaching solver uses dense Gaussian elimination on the
block-eliminated KKT system; correct at its scale, not the production
path - HiGHS owns anything big.

## Mehrotra's predictor-corrector (ch.10, IMPLEMENTED)

Why fixed centering is slow: picking sigma before seeing the step means
every iteration pays for centering it may not need. Mehrotra's idea:

1. Predictor: solve the Newton system with complementarity target 0
   (pure affine-scaling direction).
2. Assess: take the hypothetical full step to the boundary along it and
   compute the resulting duality measure mu_aff. If mu_aff << mu, the
   direction is good - little centering needed; set
   sigma = (mu_aff / mu)^3. If the boundary is close, sigma -> 1.
3. Corrector: the linear model predicts the pairwise products x_i s_i go
   to their target after a full affine step, but the ignored quadratic
   term leaves dx_i^aff * ds_i^aff behind. Compensate by solving a
   second system, same matrix, complementarity target
   sigma*mu*e - D_aff products. Because the matrix is already factored,
   the correction costs one extra back-substitution.
4. Step: combined direction, separate primal and dual step lengths to
   the boundary (worth 10-20% per the book), fixed margin.

Implemented as brain_core.lp.interior_point.solve_lp_ipm_mpc in the
repo's max-form with slack pairs (x, z) and (w, y); two dense KKT
solves per iteration sharing the elimination.

Measured adoption gate (tests/test_interior_point.py): on the seeded
60-LP random set used for the path-following solver, MPC matches the
exact-rational simplex objective on every instance (worst error
5.4e-9 measured) and takes STRICTLY fewer iterations on every
instance: min/mean/max 7/8.75/13 vs 15/19.22/24 for fixed centering
(measured 2026-11-26, Python 3.10, dense algebra). The test asserts
per-instance dominance, not the averages.

## Termination (ch.11), adopted

Interior-point methods never reach an exact solution, so stop on
relative measures: primal residual / (1 + ||b||), dual residual /
(1 + ||c||), and relative duality gap |c^T x - b^T y| / (1 + |c^T x|),
all below tol (the book's typical epsilon ~ 1e-8). Adopted in
solve_lp_ipm_mpc; the older solver's absolute-gap test is unchanged.

## Detecting infeasibility (ch.9), adopted as diagnostic only

When no solution exists, infeasible-interior-point iterates cannot
drive the residuals to zero and ||(x, s)|| blows up. Codes detect the
blowup and diagnose infeasibility; there is theoretical support
(Kojima-Megiddo-Mizuno: large iterates localize an infeasible
region), but it is a heuristic. The book's rigorous route is the
homogeneous self-dual embedding (always solvable; its solution either
yields a solution of the original LP or flags which side is
infeasible) - recorded as a gap-list item, NOT implemented.
Adopted: a divergence guard in solve_lp_ipm_mpc that raises
ArithmeticError naming infeasibility as the consistent diagnosis -
never a certificate; the exact simplex owns certificates (unchanged).

## Starting points and hot starts (ch.11) - the CG-relevant finding

- Cold start: Mehrotra's heuristic solves two least-squares problems
  (minimum-norm x meeting Ax = b; minimum-norm (y, s) meeting
  A^T y + s = c) then shifts for positivity/centrality. Theory and
  practice agree a good start is well centered and not too infeasible.
  NOT yet implemented in the teaching solver (all-ones start today);
  gap-listed.
- Hot starts are worth little to an IPM: small data changes reroute
  the central path, so prior solutions buy at most a 2-3x iteration
  saving. The simplex exploits prior solutions far better. The book's
  prescription for solving a SEQUENCE of similar LPs: IPM + basis
  recovery (crossover) on the first, then hot-started simplex for the
  rest.

Consequence for coupled_dw.py (the CG restricted master LP, solved by
scipy/HiGHS): keep dual simplex. It re-optimizes between CG rounds,
which is exactly the sequence-of-similar-LPs case simplex owns. A
measured one-shot A/B on CG-master-shaped LPs (convexity rows +
linking rows, up to 8000 columns - far beyond the current 16-plant
masters) shows HiGHS dual simplex and HiGHS IPM within measurement
noise of each other (all <= 25 ms, same objective, measured
2026-11-26 on scipy 1.15.3). Revisit only if one-shot master solves
become a measured bottleneck at much larger masters.

## Bound quality and the MILP side

- The CG lower bound IS the master LP optimum (Farley bound already
  in coupled_dw.py); IPM vs simplex changes nothing about its value,
  only how it is computed - see the measurement above.
- For the bucket MILP's LP relaxation, HiGHS is the solver of record;
  the book's contribution there is the same sequence-of-solves
  guidance (branch-and-bound re-solves are simplex territory) and the
  conditioning cautions (normal-equations D spread) that HiGHS already
  handles internally.
- Finite termination / optimal-basis recovery (ch.7, BUN partition via
  primal-dual indicators, then crossover) is the route to an exact
  vertex from an IPM solution if one is ever needed; recorded as a
  gap-list item, not implemented.

## Adopted changes (all pushed with tests)

1. solve_lp_ipm_mpc: Mehrotra predictor-corrector with adaptive
   centering, second-order correction, separate primal/dual steps,
   relative termination, infeasibility blowup diagnostic. Measured:
   2.2x fewer iterations than the existing path-following solver on
   the shared seeded set, per-instance dominant, same optima.
2. Gap-list additions (docs/SCALE-UPGRADE-LIST.md): least-squares
   cold-start heuristic; HSD embedding for certified infeasibility;
   crossover/basis recovery for exact vertices.
3. CG master LP: NO solver change - dual simplex confirmed by the
   book's hot-start analysis plus a measured one-shot A/B.
