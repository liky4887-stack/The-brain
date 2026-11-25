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
