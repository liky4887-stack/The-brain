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
