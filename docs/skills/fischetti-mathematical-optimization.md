# Skill: Introduction to Mathematical Optimization (Fischetti, 5th ed.)

Source: Matteo Fischetti, "Introduction to Mathematical Optimization",
5th English edition, September 2019, Kindle Direct Publishing, 232 pp.
PDF received from the user 2026-11-26 (digital pdfTeX text, clean
extraction, no OCR gate needed). Read in two passes: full structure
(ch.1-2 models, ch.4 simplex, ch.5 duality, ch.6 ILP: cutting planes,
Gomory, branch-and-bound, branch-and-cut, ch.7-8 complexity and
graphs, ch.9+ NP-hard models incl. TSP), deep read of ch.6 (the
branch-and-cut core, Fischetti's signature topic) and the TSP model
(8.2). Worked tableaux in ch.10 extract poorly from the PDF; all
locked numbers come from the chapter bodies instead.

This is The-brain's reference for exact ILP solution methods:
Gomory's cutting planes, branch-and-bound, and the DFJ TSP model with
constraint generation. Implemented in
packages/brain-core/brain_core/ilp/ (cutting_planes.py,
branch_and_bound.py, tsp.py); tests in tests/test_fischetti_bc.py.
The exact rational simplex (lp/simplex.py) was extended to return the
optimal tableau and basis - cut generation needs B^-1 A, and exact
Fractions make every cut exact.

## 1. Gomory's fractional cuts (sec 6.3)

- From an optimal tableau row t with fractional basic value (6.2):
  the integer form (6.3) floors every coefficient and the RHS;
  subtracting gives the fractional form (6.4):
  sum_{j non-basic} phi(a_tj) x_j >= phi(b_t), phi(r) = r - floor(r).
- (6.4) has all coefficients >= 0, is valid for every integer point,
  and is violated by the current LP optimum (LHS = 0, RHS > 0) -
  that pair of properties is what makes it a cut.
- Fractional parts of NEGATIVE numbers: phi(-3/8) = 1 - phi(3/8) =
  1/3. floor, not truncation.
- Implementation: keep the working LP in equality form (one
  slack/surplus per row, added by us) so each cut appends one surplus
  column; re-solve with the exact simplex (the book uses dual
  simplex - same optima, our re-solve is simpler and exact).
- Locked example (sec 6.3 Example 1): min -x2 s.t. 3x1+2x2 <= 6,
  -3x1+2x2 <= 0. Relaxation z = -3/2 at (1, 3/2); two cuts reach the
  integer optimum (1,1), z = -1.

## 2. Branch-and-bound (sec 6.4)

- Branching splits on a fractional variable: xh <= floor / xh >=
  ceil. The disjunction is not linear, so it cannot be a cut - it
  defines two subproblems instead.
- Three fathoming criteria: relaxation integer (update incumbent),
  relaxation infeasible, bounding LB >= incumbent.
- Bounds never decrease from parent to child; if c is integer,
  strengthen LB to ceil(c.x*) - cheap and often prunes a level
  earlier.
- Branching variable: fractional part nearest 0.5 is the book's
  simple rule; it notes modern estimators (max product of child bound
  increases) do better, but 0.5 is the teachable default.
- Node selection: DFS (deep, local, early incumbents) vs best-bound
  (fewer nodes, shallow work). We implement both; exact arithmetic
  means no tolerances anywhere in the tree.
- Example 1 needs 5 nodes, not 3: the x2 <= 1 child's LP optimum is
  the fractional vertex (2/3, 1) - an objective-value tie with the
  integer optimum is NOT integer-feasibility; only the vertex check
  decides.

## 3. TSP by constraint generation (sec 8.2)

- Model (8.2): min circuit cost; one arc entering (8.2b) and one
  leaving (8.2c) each vertex; connectivity (8.2d): every S containing
  vertex 1 has an arc leaving it. (8.2b)-(8.2c) alone give disjoint
  circuits covering all vertices; (8.2d) kills the short ones.
- The family is exponential: never write it down. Generate
  lazily - solve, find a violated S, add its constraint, repeat
  (branch-and-cut; the book separates over the fractional relaxation
  by min-cut, we separate over integer solutions where subtours are
  directly visible - the same (8.2d) constraints).
- Hand-checked 5-city instance locked at 67 (tour 0-1-3-4-2-0);
  random 6/7-city instances cross-checked against permutation brute
  force.

## 4. Lessons

- Exact rational arithmetic changes the character of these
  algorithms: no epsilon-integrality checks, no cut tolerances, no
  pruning mistakes - a fractional value is a Fraction with
  denominator != 1, period.
- The three-way split of the ILP toolkit (cutting planes,
  branch-and-bound, constraint generation for exponential families)
  covers most of what a practical solver does; CP-SAT remains the
  first choice for The-brain's engine work, and these modules are the
  exact, inspectable reference implementations behind it.
