# Reference material and honesty note

The user supplied a reading list as TITLES ONLY (docs/notes-01); books are
arriving as he sends them, and each one is distilled into a skill plus
reusable code before it is relied on.

Distilled skills derived from these books are versioned in docs/skills/ so
they survive as part of the project record.

Available to the build (full text provided by the user):
- Williams, Model Building in Mathematical Programming, 5th ed. (Wiley
  2013). Received 2026-11-25, read in two passes (full structure, then a
  deep read of ch.2, 3, 6, 9, 10). Distilled into the modeling patterns in
  packages/brain-core/brain_core/modeling/patterns.py - indicator links,
  fixed charges, soft constraints, disjunctions, minimax, disaggregation,
  symmetry breaking - each brute-force-verified in
  tests/test_modeling_patterns.py. Its formulation-strength rules (realistic
  big-M, disaggregate over aggregate, kill symmetry) are the standard every
  future model in this repo is held to.

- Li, Optimization Modeling for Supply Chain Applications (World
  Scientific). Received 2026-11-25, read in two passes (full structure,
  then deep read of ch.2, 3, 6, 8, 11 with structure review of 4, 7,
  12-14). Distilled into docs/skills/li-supply-chain-optimization.md.
  Its linear-ordering scheduling formulation (ch.11.2.3), generalized to
  weighted tardiness, is implemented as an independent second solver in
  packages/brain-core/brain_core/solvers/ordering_solver.py;
  tests/test_ordering_solver.py cross-validates it against the interval
  formulation AND the exhaustive baseline on every example and exhaustive
  golden scenario - three independent routes, one optimum.

Still titles only: Bertsimas & Tsitsiklis; Wolsey; Chen/Batson/Dang;
Apt; the CP Handbook; the CPAIOR volume; MO-Book.

Used instead, all public and lawful:
- Google OR-Tools documentation and examples (developers.google.com/
  optimization), specifically the CP-SAT scheduling guide (interval
  variables, AddNoOverlap, integer-only coefficients).
- The CP-SAT Primer, Dominik Krupke (d-krupke.github.io/cpsat-primer,
  public).
- Pyomo and HiGHS documentation (for the later MILP adapter).
- The user's own six research documents (docs/plan-beating-dios.txt,
  docs/notes-0*.txt), whose performance claims are treated as directional
  until verified against primary sources.

Every formulation decision in code cites the source it came from in a
header comment. Where a book is still titles-only, public docs are used and
flagged at the point of use instead of being silently borrowed.

- Bertsimas & Tsitsiklis, Introduction to Linear Optimization (Athena
  Scientific). Received 2026-11-25 as a 301-page scan without a text
  layer. Chapters 10-12 (IP formulations, IP methods, the art in linear
  optimization) read via OCR in two passes; per the user's instruction the
  OCR was verified against rendered page images before anything was relied
  on (Theorem 10.1, Theorem 12.1 WSPT, Theorem 12.2 separation, the 12.5
  job shop LP (12.4), the TSP dynamic program (11.3) - all confirmed;
  inline formula OCR is imperfect, so only image-verified content is
  cited). Chapters 1-9 identified from the TOC but not OCR'd. Distilled
  into docs/skills/bertsimas-linear-optimization.md. The single-machine
  results are implemented in
  packages/brain-core/brain_core/scheduling/single_machine.py and
  brute-force-validated in tests/test_single_machine.py (WSPT vs all
  permutations; separation vs all subsets).

- Wolsey, Integer Programming, 2nd ed. (Wiley 2021). Received 2026-11-25
  as a 360-page digital PDF (text layer intact, no OCR needed). Read in
  two passes: full structure, then deep read of ch.1, 5.2, 14.3-14.4 with
  ch.7-9 read for the reformulation method. Distilled into
  docs/skills/wolsey-integer-programming.md. The Wagner-Whitin
  uncapacitated lot-sizing DP (sec. 5.2) is implemented in
  packages/brain-core/brain_core/lotsizing/uls.py and validated in
  tests/test_uls.py against brute-force enumeration of all setup sets
  (which caught and fixed a zero-demand-period edge case the plain
  recursion mishandles). Chapters not deep-read are marked as such in the
  skill; their details are not cited anywhere in code.

- Handbook of Constraint Programming (Rossi, van Beek, Walsh eds.,
  Elsevier 2006). Received 2026-11-25 as a 969-page digital PDF (text
  layer intact). Read in two passes: full structure, then deep read of
  ch.22 (Constraint-Based Scheduling and Planning, Baptiste/Laborie/
  Le Pape/Nuijten). Distilled into
  docs/skills/handbook-constraint-programming.md. Disjunctive propagation
  and cubic edge-finding (sec. 22.3.1) are implemented in
  packages/brain-core/brain_core/propagation/edge_finding.py and
  soundness-tested against brute-force permutation search in
  tests/test_edge_finding.py - the brute force caught a min/max extremum
  bug before merge. Not-first/not-last, timetable and energy reasoning
  are documented in the skill but deliberately not yet implemented.

- Pinedo, Planning and Scheduling in Manufacturing and Services
  (Springer). Received 2026-11-25 as a 499-page digital PDF (text layer
  intact). Read in two passes: full structure (3 parts, 12 chapters),
  then deep read of ch.4.2 (CPM) and 5.3 (job shop disjunctive graph and
  formulation). Distilled into docs/skills/pinedo-planning-and-scheduling.md.
  Implemented in packages/brain-core/brain_core/jobshop/ (cpm.py,
  disjunctive.py), validated in tests/test_jobshop.py: Example 4.2.3
  reproduces the book's printed earliest and latest completion rows
  (precedences reconstructed and verified), CPM matches brute-force
  longest paths on 150 random DAGs, and the disjunctive-graph makespan
  matches direct simulation on all machine sequencings of Example 5.3.1.
  Shifting bottleneck (5.4) documented, not implemented.

- Hillier & Lieberman, Introduction to Operations Research, 7th ed.
  (McGraw-Hill). Received 2026-11-25 as a 1237-page digital PDF (text
  layer intact). Read in two passes: all 22 chapters mapped, then deep
  read of ch.4 (simplex) with ch.3 and 6 for framing. Distilled into
  docs/skills/hillier-introduction-to-operations-research.md. The
  two-phase primal simplex with Bland's rule (exact rational arithmetic)
  is implemented in packages/brain-core/brain_core/lp/simplex.py and
  validated in tests/test_simplex.py against brute-force vertex
  enumeration on 120 random LPs plus the locked Wyndor example - the
  brute force caught a missing negative-right-hand-side normalization
  (sec. 4.6) before merge. This gives The-brain in-house LP relaxations.

- Ahuja, Magnanti & Orlin, Network Flows: Theory, Algorithms, and
  Applications (Prentice Hall 1993). Received 2026-11-25 as an 863-page
  scan with a CVISION OCR text layer. Per the OCR gate, the algorithm
  pages relied on (Figure 6.17 labeling, Figure 9.9 successive shortest
  path, Theorems 6.3-6.5, Lemmas 9.11-9.12) were verified against the
  rendered page images. Read in two passes: structure, then deep read of
  ch.6.5 and 9.7. Distilled into docs/skills/ahuja-network-flows.md.
  Implemented in packages/brain-core/brain_core/network/flows.py:
  max_flow (labeling/Edmonds-Karp) and min_cost_flow (successive shortest
  paths with potentials). tests/test_flows.py uses the max-flow min-cut
  theorem itself as oracle (brute-force cuts over all subsets) and the
  repo's own simplex solver as an independent oracle for min-cost flow;
  the cross-check caught that SSP silently mis-optimizes negative-cost
  instances (outside the book's ch.9 nonnegativity assumption), so they
  are now rejected loudly. Cycle-canceling documented, not implemented.

- Vanderbei, Linear Programming: Foundations and Extensions, 2nd ed.
  (Springer 2001). Received 2026-11-25 as a 466-page pdfTeX digital PDF
  (no OCR gate needed). Read in two passes: structure, then deep read of
  ch.16 (central path) and ch.17 (path-following method, Figure 17.1,
  eqs 17.1-17.6). Distilled into
  docs/skills/vanderbei-linear-programming.md. Implemented in
  packages/brain-core/brain_core/lp/interior_point.py: solve_lp_ipm, a
  primal-dual infeasible-start path-following method with block-
  eliminated KKT Newton steps (delta=0.1, step margin 0.9). Honest
  scope: floats, near-optimal solutions on feasible+bounded instances
  only, no infeasibility/unboundedness certificates (simplex keeps that
  job). tests/test_interior_point.py locks Wyndor (Z=36 at (2,6)) and
  cross-checks 60 random feasible+bounded LPs against the exact simplex
  within 1e-4. A sign error in the eliminated KKT block (-Y^-1 W, not
  +Y^-1 W) was caught by numerically comparing the reduced system
  against the full 4-block Newton system before merge.

Five interior-point papers received together 2026-11-25 (all digital
text, no OCR gate needed; each read twice):

- Potra & Wright, "Interior-Point Methods" (J. Comput. Appl. Math.
  124, 2000). LP path-following survey; Mehrotra's predictor-corrector
  and the LCP/QP extensions. Distilled into
  docs/skills/potra-wright-interior-point-methods.md. Implemented from
  sec. 3 (problem 3.18): packages/brain-core/brain_core/qp/
  interior_point.py, solve_qp_ipm - infeasible-start primal-dual
  path-following for min (1/2)x'Qx + c'x s.t. Ax=b, x>=0, Q psd, with
  the QP rule of one step length for all variables.
  tests/test_qp_ipm.py locks two known-solution QPs, cross-checks 40
  random PSD QPs against an independent active-set enumeration oracle,
  and 20 Q=0 cases against the exact simplex.
- Wright, "Interior-Point Methods" (Simons Institute slides, 2017).
  Theory orientation: N2 neighborhoods, short/long-step path-following,
  Mizuno-Todd-Ye predictor-corrector, potential reduction. Distilled
  into docs/skills/wright-ipm-simons-slides.md. Nothing new implemented
  (MTY needs a strictly feasible start; our solvers are
  infeasible-start).
- Wright, "Recent Developments in Interior-Point Methods" (chapter,
  ~2001). Second-source corroboration of the same framework plus
  structure-exploiting linear algebra and the IPM-vs-simplex
  warm-start tradeoff (matters for future MIP work). Distilled into
  docs/skills/wright-recent-developments-ipm.md. Nothing implemented.
- Nesterov & Todd, "Primal-Dual Interior-Point Methods for Self-Scaled
  Cones" (SIAM J. Optim. 8, 1998). Theory of symmetric/self-scaled
  cones: the unique scaling point, the NT direction, symmetric
  primal-dual path-following for LP/QCQP/SDP. Distilled into
  docs/skills/nesterov-todd-self-scaled-cones.md. Documented, not
  implemented (conic linear algebra is out of current scope).
- Gould, Orban, Sartenaer & Toint, "Superlinear convergence of
  primal-dual interior point algorithms for nonlinear programming"
  (RAL-TR-2000-014). Algorithm 4.1: outer barrier-parameter decrease
  with an inner primal-dual Newton minimization under forcing
  conditions; componentwise Q-superlinear, arbitrarily close to
  quadratic. Distilled into docs/skills/gould-superlinear-ipm-nlp.md.
  Implemented as packages/brain-core/brain_core/nlp/interior_point.py,
  solve_nlp_ipm: min f(x) s.t. Ax=b, c(x)>=0 with user-supplied
  gradients/Hessians, eps = 0.1 mu forcing, mu <- mu^1.5. Honest
  scope: local method, needs a strictly feasible start (violations
  raise loudly), no global machinery or infeasibility detection.
  tests/test_nlp_ipm.py locks three convex problems with known optima,
  cross-checks 15 quadratic objectives against solve_qp_ipm, verifies
  full KKT residuals, and checks the loud infeasible-start rejection.
