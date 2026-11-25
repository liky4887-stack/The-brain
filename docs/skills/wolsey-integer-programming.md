# Wolsey — Integer Programming, 2nd ed. (Wiley 2021)

Distilled 2026-11-25 from the user's full digital copy (360 pages, text
layer intact - no OCR needed). Read in two passes: full structure from the
contents, then a deep read of ch.1 (formulations), ch.5.2 (uncapacitated
lot-sizing), ch.14.3-14.4 (how to improve formulations; multi-item
single-machine lot-sizing), with ch.7-9 (branch and bound, cutting planes,
strong valid inequalities) read for their reformulation method.

## The formulation-strength method (ch.14.3, the book's applied core)

To improve a formulation, ask in order:
- Q1. Is optimization over the feasible set polynomially solvable? If yes,
  there is hope of an explicit convex-hull description (conv(X)).
- Q2. How can the current fractional LP point be cut off? Decompose the
  solution between successive integer-friendly points (for ULS: between
  periods with zero stock) and attack the small fractional core with known
  cutting planes (cover, flow cover inequalities).
- Q3. Are the cuts as tight as possible - can they be strengthened or
  decomposed?
- Q4. Is the separation problem easy? A separation heuristic is acceptable
  in practice.
This Q1-Q4 loop is the practical bridge between Bertsimas & Tsitsiklis'
theory (strength = containment of LP relaxations; exponential families are
fine with fast separation) and daily modeling work.

## Uncapacitated lot-sizing (sec. 5.2, implemented)

- ULS: min sum_t (p_t y_t + h_t s_t + f_t x_t) s.t. balance
  s_{t-1} + y_t = d_t + s_t, y_t <= M x_t, x in {0,1}^n.
- It is a fixed-charge network flow problem (Figure 5.2).
- Proposition 5.1: an optimal plan exists with s_{t-1} y_t = 0 (produce
  only with zero entering stock), and any production equals the demand of
  an exact run of periods. So the only choice is the set of setup periods.
- Observation 5.4: eliminate stocks; with c_t = p_t + sum_{i>=t} h_i the
  objective becomes sum_t c_t y_t + sum_t f_t x_t minus the constant
  sum_t h_t d_1t.
- Forward recursion: H(k) = min_{1<=t<=k} { H(t-1) + f_t + c_t d_tk },
  H(0) = 0; O(n^2). Equivalent to a shortest path on nodes 0..n.
- Example 5.1 (locked in tests): d=(2,4,5,1), p=(3,3,3,3), h=(1,2,1,1),
  f=(12,20,16,8) -> value 69, plan y=(6,0,6,0), x=(1,0,1,0).
- Implementation note (ours, not the book's): the recursion needs a guard
  for zero-demand periods (when d_k = 0, H(k) = H(k-1)); otherwise it
  forces a useless setup. Brute-force tests caught this.
- Ch.14.3 adds that ULS is polynomially solvable, so conv(X_ULS) is
  attainable, and fractional LP points are cut with flow cover
  inequalities between zero-stock points.

## Multi-item single-machine lot-sizing (sec. 14.4, The-brain's problem family)

Data per item i: demand d_it, holding h_i, start-up cost g_i, changeover
cost q_ij and time Delta_ij, production rate rho_i, min run-time alpha_i,
min down-time beta_i, capacity C_t per period. One item per period.
This is the exact shape of changeover-constrained production scheduling;
the book treats it via the ch.14.3 loop on its single-machine relaxation.

## Rest of the book (structure read, not deep-read - do not cite details)

Ch.2 relaxations and bounds; ch.3 well-solved problems (total
unimodularity, network flows, submodularity); ch.4 matchings and the
assignment problem; ch.5 other DPs (knapsack, cutting stock); ch.6
complexity and the optimization-separation equivalence; ch.7 branch and
bound incl. presolve; ch.8 cutting planes (Chvatal-Gomory, MIR, split
cuts, lift-and-project); ch.9 strong valid inequalities (cover and flow
cover families, separation); ch.10 Lagrangian duality; ch.11 column
generation and branch-and-price; ch.12 Benders; ch.13 primal heuristics
(tabu, simulated annealing, genetic, MIP-solver heuristics).

## Cross-book synthesis (Williams, Li, Bertsimas & Tsitsiklis, Wolsey)

Four books, one law: relaxation strength decides tractability. Wolsey adds
the working procedure (Q1-Q4) and the exact algorithms for the easy cores
(ULS, assignment, network flow) that recur as relaxations inside hard
scheduling problems. The-brain now has both sides: strong formulations
(Williams, Li), convex-hull theory and separation (B&T), and the
reformulation workflow plus the ULS algorithm (Wolsey).

## Code

packages/brain-core/brain_core/lotsizing/uls.py implements the
Wagner-Whitin forward recursion with the Observation 5.4 transformation;
reported costs are recomputed from the plan in the original (p, h, f)
costs and feasibility-checked. tests/test_uls.py locks Example 5.1 and
validates the DP against brute-force enumeration of all 2^n setup sets on
random instances, and checks the Proposition 5.1 structure of every
returned plan. Nothing is claimed beyond these tests.
