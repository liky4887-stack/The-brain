# Hillier & Lieberman — Introduction to Operations Research, 7th ed. (McGraw-Hill)

Distilled 2026-11-25 from the user's full digital copy (1237 pages, text
layer intact - no OCR needed). Read in two passes: all 22 chapters
mapped, then deep read of ch.4 (the simplex method: algebra, tableau,
tie breaking, adapting to other model forms) with ch.3 (LP modeling) and
ch.6 (duality and sensitivity) for framing.

## The simplex method (ch.4, implemented)

- Geometry-to-algebra: move between adjacent basic feasible (corner)
  solutions; the optimality test stops when no entering variable improves
  Z (sec. 4.3). Entering variable: a negative reduced cost; leaving
  variable: the minimum ratio test.
- Tie breaking and degeneracy (sec. 4.5): entering ties are arbitrary;
  leaving ties create degenerate basic solutions and can in theory cycle.
  Bland's rule (Bland 1977, cited in the chapter) breaks both ties by
  smallest index and provably cannot cycle - that is why the
  implementation uses it instead of the book's "break arbitrarily".
- Unbounded Z (sec. 4.5): no leaving variable (every pivot-column
  coefficient <= 0) means the entering variable grows without bound.
- Other model forms (sec. 4.6): negative right-hand sides are multiplied
  through by -1 (skipping this produced a wrong "optimal" solution with a
  negative variable in testing - caught by brute-force vertex
  enumeration, fixed, and now covered); ">=" rows get surplus plus
  artificial variables; "==" rows get artificials; the two-phase method
  minimizes the sum of artificials first, and a positive phase-1 optimum
  proves infeasibility.
- Wyndor Glass Co. (the book's running example) is locked:
  max 3x1 + 5x2 s.t. x1 <= 4, 2x2 <= 12, 3x1 + 2x2 <= 18 -> Z = 36 at
  (2, 6).
- Duality (ch.6): every LP has a dual; shadow prices are the dual
  solution; the primal and dual optimal values agree (strong duality).
  Sensitivity analysis reads what changes in the data do to the optimal
  basis. Not implemented; the simplex tableau already carries the
  information when it is needed.

## Rest of the book (structure read, not deep-read - do not cite details)

Ch.1-2 the OR approach; ch.3 LP modeling and the Wyndor example; ch.5
simplex theory (revised simplex, fundamental insight); ch.7 dual simplex,
parametric LP, upper bounds, interior point; ch.8 transportation and
assignment; ch.9 network optimization (shortest path, min cost flow,
max flow); ch.10 PERT/CPM (overlaps Pinedo ch.4); ch.11 dynamic
programming; ch.12 integer programming (branch and bound, branch and
cut); ch.13 nonlinear programming; ch.14 game theory; ch.15 decision
analysis; ch.16 Markov chains; ch.17-18 queueing; ch.19 inventory;
ch.20-22 simulation, Markov decision processes, reliability.

## Cross-book synthesis

This is the generalist foundation under the specialists already in the
repo: Bertsimas & Tsitsiklis gives the LP/IP theory at graduate depth,
Williams/Li/Wolsey the modeling and reformulation craft, the CP handbook
and Pinedo the scheduling side. The simplex implementation closes a real
gap: The-brain can now compute LP relaxations and bounds in-house, with
exact rational arithmetic, which the Wolsey Q1-Q4 reformulation loop and
the B&T duality arguments both assume.

## Code

packages/brain-core/brain_core/lp/simplex.py: two-phase primal simplex
with Bland's rule, exact Fraction arithmetic, statuses optimal /
infeasible / unbounded. tests/test_simplex.py: Wyndor locked; 120 random
LPs cross-checked against brute-force enumeration of all basic solutions;
constructed infeasible, unbounded, degenerate and equality-only cases.
Nothing beyond these tests is claimed.
