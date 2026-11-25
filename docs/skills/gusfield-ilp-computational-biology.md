# Skill: ILP in Computational and Systems Biology (Gusfield)

Source: Dan Gusfield, "Integer Linear Programming in Computational and
Systems Biology" - tutorial deck (BCB, Niagara Falls, September 2019),
101 slides, adapted from his Cambridge University Press 2019 book.
PDF received from the user 2026-11-26 (digital text via Quartz, clean
extraction, no OCR gate needed). Read in two passes: full sequential
read of all 101 slides, then a focused re-read of the five modeling
parts to lock the concrete instances. Note: the slide table for the
Species-Protection toy has typos (beta row, cost of region E); the
book's own equations (2)-(3) are the consistent source - they
reproduce the book's stated optimum exactly, and are what the code
implements.

This is The-brain's reference for ILP modeling idioms (how to turn
logic into linear inequalities) and for the computational-biology
model family (cliques, near-cliques, density, RNA folding, set-cover-
style conservation). Implemented in
packages/brain-core/brain_core/ilp/idioms.py and
packages/brain-core/brain_core/bio/ (species.py, networks.py, rna.py);
tests in tests/test_gusfield_bio.py.

## 1. The modeling loop (Part I)

- Concrete formulation (all data explicit) -> solver -> abstract
  formulation. LP first, then ILP by requiring integrality; binary
  when regions are all-or-nothing. The LP relaxation's optimum is
  never worse for the objective - it bounds the ILP optimum.
- Species-Protection toy (the running example): 5 regions, 2 species,
  min cost s.t. abundance sums >= targets and X <= 1. Exact rational
  optimum 45072/415 = 108.607 (book: "108.7 after rounding up"), with
  XA = 69/83, XD = 112/415, XE = 1, XB = XC = 0.
- "What-if" questions are the payoff of a formulation: swap the
  objective (max XB s.t. cost <= 108.7 -> 0.00296), or add a
  constraint (XB >= 0.1 -> cost 111.7). Build models so these are
  one-line changes. Our species_protection() takes extra= and
  maximize= for exactly this.

## 2. Cliques and density (Parts II-III)

- Max clique: C(i) + C(j) <= 1 for every NON-edge. The formulation
  only lists what's forbidden; nothing forces C to 0. Book's 5-node
  example (non-edges (1,4),(2,3),(2,5),(4,5)): optimum 3.
- Weighted nodes: just change the objective to sum w(i) C(i).
- Near-clique (allow k added edges): replace the hard exclusion with
  C(i) + C(j) - V(i,j) <= 1 and sum V <= k. The asymmetry is fine:
  nothing forces V(i,j)=0 when the pair isn't both selected, because
  the budget constraint does the work. Per-node variant: one budget
  inequality per node.
- High-density subgraph (density >= d): three variable families -
  C(i) selection, P(i,j) "potential edge" (If-Then:
  C(i)+C(j)-P(i,j) <= 1), E(i,j) "edge in subgraph" (Only-If:
  2E(i,j)-C(i)-C(j) <= 0) - plus sum E >= d * sum P. In CP-SAT scale
  d by 1000. Add sum C >= 1 to exclude the vacuous empty subgraph
  (the book's formulation admits it; density 0/0 is undefined).

## 3. The idioms (Part IV) - the reusable core

For a linear function L of bounded variables and threshold b:
- If-Then (17): L - M*z <= b - 1 forces z=1 when L >= b. M = upper
  bound on L. (Not M*(1-z): the z-side multiplier is M itself.)
- Only-If (18): L + m*z >= m + b with m = s - b, s = lower bound on
  L. The naive L + z >= b + 1 has the classic bad side-effect at
  z = 0.
- Indicators compose: NAND (z1+z2 <= 1), OR (z1+z2 >= 1), XOR
  (z1+z2 = 1), implied-satisfaction (z1 <= z2). Build them from
  If-Then/Only-If per inequality, then relate the z's.
- NOT-EQUAL for bounded integers in [1,n] (27):
  Z1 - Z2 - n(z-1) >= 1 and Z2 - Z1 + n*z >= 1 with one binary z.
  For binary X,Y an indicator that they differ: z >= X-Y, z >= Y-X
  (book's (25)), completed with z <= X+Y and z <= 2-X-Y.
- Every idiom test in The-brain enumerates ALL assignments and checks
  the logic universally, not on sample points.

## 4. RNA folding (Part V)

- Simple model: binary P(i,j) per position pair; disallow
  non-complementary pairs (fix to 0); each position in at most one
  pair (28); nesting = forbid crossings i < i' < j < j' (29);
  maximize matched pairs. Toy S=ACUGU -> 2 pairs.
- The power of the ILP approach: each biological refinement is a
  local edit - min stem distance (bound i-j), weights (AU=2, CG=3
  hydrogen bonds) in the objective, stacked quartets via Q(i,j) with
  If-Then (30) + Only-If (31), then max sum(P) + sum(Q); quartet
  weights and first-quartet-in-stack variables extend further.
  Crossing pairs and pseudoknots are exercises in the same style.
- Independent oracle for tests: the Nussinov DP recurrence gives the
  same max-pair count; ILP and DP must agree on every sequence.

## 5. Lessons

- "What" is easier than "How": state the optimum's shape with many
  simple inequalities and let the solver search.
- Typos survive in slides; validate every concrete instance against
  the author's own stated solution before locking it.
- The empty subgraph satisfies a density constraint written without a
  nonemptiness clause - exclude it explicitly.
