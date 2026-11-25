# Vanderbei — Linear Programming: Foundations and Extensions, 2nd ed. (Springer 2001)

Distilled 2026-11-25 from the user's full copy (466 pages, pdfTeX digital
text — no OCR gate needed; text extracted cleanly). Read in two passes:
structure from contents, then deep read of ch.16 (the central path) and
ch.17 (the path-following method, Figure 17.1 and equations 17.1-17.6),
with the simplex chapters already covered via Hillier.

## Standard form and duality (ch.5, ch.16 framing)

- The book's canonical form is a MAXIMIZATION with inequality rows:
  max c^T x  s.t.  Ax + w = b, (x, w) >= 0 (w = slack variables).
  Dual: min b^T y  s.t.  A^T y - z = c, (y, z) >= 0.
- Complementary slackness: x_j z_j = 0 and y_i w_i = 0 at optimality.
  Strong duality: optimal primal and dual objectives coincide.

## The central path (ch.16)

- Replace the complementarity equalities by the perturbed system:
  Ax + w = b,  A^T y - z = c,  XZe = μe,  YWe = μe
  (X, Z, Y, W diagonal matrices of the vectors; e the all-ones vector).
- For each μ > 0 with a feasible interior region, this system has a
  unique solution; the set of solutions over μ > 0 is the central path,
  and it converges to an optimal solution as μ → 0.
- μ = (x·z + y·w) / (n + m) measures the current duality gap: the
  primal-dual objective gap at the μ-point is exactly (n + m) μ.

## The path-following method (ch.17, implemented)

One Newton step per iteration from any strictly positive start
(x, w, y, z) > 0 (feasibility of the equality rows is NOT required —
the residuals ρ = b − Ax − w and σ = c − A^T y + z are driven to zero
alongside complementarity; this is the "infeasible-start" variant the
book presents as practical):

1. Current barrier parameter μ = (x·z + y·w)/(n+m); target μ' = δμ with
   δ = 0.1 (the book's practical choice; eq. 17.5).
2. Newton system for the step (Δx, Δw, Δy, Δz) (eqs 17.1-17.4):
     A Δx + Δw           = ρ
          A^T Δy − Δz    = σ
     Z Δx      + X Δz    = μ'e − XZe
          W Δy + Y Δw    = μ'e − YWe
   Eliminate Δz = X⁻¹(μ'e − XZe) − X⁻¹Z Δx and
   Δw = Y⁻¹(μ'e − YWe) − Y⁻¹W Δy to get the reduced (n+m) × (n+m)
   KKT system in (Δx, Δy):
     (A^T Y W⁻¹ ... in the book's normal-equations form; we keep the
     symmetric 2×2 block form)
       [X⁻¹Z]  Δx − A^T Δy = −(σ + X⁻¹(μ'e − XZe))    — sign care here
       A Δx − Y⁻¹W Δy      = ρ − Y⁻¹(μ'e − YWe)       — sign care here
3. Step length (eq. 17.6): θ = r · min over all components of the largest
   step keeping x, w, y, z strictly positive, with margin r = 0.9.
4. Update (x, w, y, z) += θ(Δx, Δw, Δy, Δz); stop when the gap
   (x·z + y·w) < tol.

### Bug caught during implementation (kept as a warning)

Block elimination has TWO sign traps. The eliminated row for Δy picks
up −Y⁻¹W Δy (because Δw = Y⁻¹(μ'e − YWe) − Y⁻¹W Δy), so the (i,i)
block of the reduced system is −Y⁻¹W, not +Y⁻¹W. A first version had
the wrong sign: iterates looked plausible for ~10 steps, then diverged
(max residual to 1e19). Cross-checking the reduced system against the
full 4-block Newton system at one iterate exposed it. Lesson applied:
verify an eliminated system against the uneliminated one numerically
before trusting it.

## Honest scope of the implementation (packages/brain-core/brain_core/lp/interior_point.py)

- Floats only; no exact arithmetic is possible for Newton iterations.
- Claims a near-optimal solution ONLY on feasible, bounded instances.
  No infeasibility or unboundedness certificates — use the exact
  two-phase simplex (simplex.py, Hillier) for classification.
- Validated: locked Wyndor problem (Z=36 at (2,6)); 60 random
  feasible+bounded LPs agree with the exact simplex within 1e-4 on the
  objective and return points feasible within 1e-5.

## Rest of the book (structure read, not deep-read — do not cite details)

Part I simplex method (ch.1-8: duality, sensitivity, degeneracy,
revised simplex); Part II network-type problems (ch.13-15:
transportation, assignment, network simplex); Part III interior-point
(ch.16-18: central path, path-following, affine-scaling and
homogeneous/self-dual methods); Part IV extensions (ch.19-24:
quadratic programming via the same KKT-Newton machinery, convex
analysis, game theory, regression, financial portfolio optimization —
Markowitz via QP). Ch.18 and Part IV are documented but not
implemented.
