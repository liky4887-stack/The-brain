# Handbook of Constraint Programming (Rossi, van Beek, Walsh eds., Elsevier 2006)

Distilled 2026-11-25 from the user's full digital copy (969 pages, text
layer intact - no OCR needed). Read in two passes: full structure (all 25
chapters mapped), then a deep read of ch.22 (Baptiste, Laborie, Le Pape,
Nuijten, "Constraint-Based Scheduling and Planning"), the chapter that
governs The-brain's engine core.

## CP models for scheduling (sec. 22.1)

- Activities: non-preemptive (start, end, proc variables; proc = end -
  start), preemptive (set variables or 0-1 X(A,t)), elastic (energy).
- Resources: disjunctive/unary (capacity 1, "machines") vs cumulative.
  Resource constraint: at every time t, sum of demands <= capacity.
- Temporal constraints are linear: x - y <= d on start/end variables;
  sparse networks propagate with arc-B-consistency plus a Ford-variant
  inconsistency check; dense networks use Floyd-Warshall path consistency.
- Industrial extensions catalogued: alternative resources (constructive
  disjunction over per-resource fictive activities), setup times/costs
  (start(Aj) >= end(Ai) + setup(Ai,Aj) on the same machine), breakable
  activities and calendars/productivity profiles, optional activities,
  subcontracting.

## Propagation for resource constraints (sec. 22.3, implemented)

- Disjunctive constraint: maintain arc-B-consistency on
  [end(Ai) <= start(Aj)] or [end(Aj) <= start(Ai)]. When eet(Ai) >
  lst(Aj), Ai cannot precede Aj, so Aj precedes Ai and bounds tighten;
  neither possible means contradiction.
- Edge-finding: deduce that an activity must execute before (or after)
  all activities of a set Omega. With r_Omega the smallest earliest start,
  d_Omega the LARGEST latest end, p_Omega the sum of processing times:
      d_{Omega u {Ai}} - r_Omega < p_Omega + p_i  =>  Ai before all of Omega
      d_Omega - r_{Omega u {Ai}} < p_Omega + p_i  =>  Ai after all of Omega
  Adjustments: end(Ai) <= min over nonempty Omega' of (d_Omega' -
  p_Omega'), and the mirror for start. Only O(n^2) "task interval" sets
  need considering, giving a straightforward cubic algorithm (faster
  O(n^2) and O(n log n) variants exist in the literature).
- Not-first/not-last: negative counterparts; O(n^2) adjustments.
- Cumulative resources: timetable constraint (arc-B-consistency on the
  per-time-point capacity sum), disjunctive pairs when c_i + c_j > cap,
  and energy reasoning: left-shift/right-shift required energy
  WSh(Ai,t1,t2) = c_i * min(t2-t1, p_i^+(t1), p_i^-(t2)); slack
  C(t2-t1) - WSh must be >= 0, and energy tests adjust time bounds in
  O(n^3).

## Honesty notes for use in The-brain

- Propagation is sound but INCOMPLETE: it tightens bounds and detects
  some infeasibilities; it never proves feasibility. Claims about our
  implementation are limited to what brute-force permutation tests
  establish (soundness of every deduced bound; contradiction only when
  truly infeasible).
- Implementation caught a real bug during testing: the set aggregates
  were coded with the wrong extremum (min vs max); brute-force soundness
  tests flagged a false contradiction immediately. Fixed and locked.

## Rest of the handbook (structure read, not deep-read - do not cite details)

Ch.2 CSP foundations (Freuder/Mackworth); ch.3 propagation (Bessiere);
ch.4 backtracking search (van Beek); ch.5 tractable structure (Dechter);
ch.6 complexity of constraint languages; ch.7 global constraints (van
Hoeve/Katriel: alldifferent, cumulative, edge-finding filters); ch.8
local search; ch.9 soft constraints; ch.10-21 extensions (symmetry,
temporal CSPs incl. Allen's Interval Algebra, constraint logic
programming, distributed); ch.23 vehicle routing; ch.24 configuration;
ch.25 applications.

## Cross-book synthesis

Williams/Li/Wolsey give the MIP side (formulations, relaxations, valid
inequalities); Bertsimas & Tsitsiklis the LP/IP theory; this handbook
gives the CP side: the same scheduling problems attacked by domain
reduction instead of relaxation. The-brain's CP-SAT engine sits exactly
at this junction: interval variables + no_overlap (CP) over a
LP-relaxation-strength philosophy (MIP). Edge-finding is the CP analogue
of a strong valid inequality: it tightens bounds without branching.

## Code

packages/brain-core/brain_core/propagation/ implements the sec. 22.3
propagation algorithms:
- edge_finding.py: disjunctive propagation, cubic edge-finding, and
  not-first/not-last, iterated to a fixpoint;
- timetable.py: compulsory-part propagation for unary resources and the
  compulsory-profile overload check for cumulative resources;
- energy.py: left-shift/right-shift required energy (WSh) and the
  overload check (the book's Figure 22.6 example, WSh(A,2,7) = 8, is a
  locked unit test).
tests/test_edge_finding.py and tests/test_timetable_energy.py validate
soundness against brute-force search (permutations for unary, start-time
grids for cumulative): every deduced bound holds in every feasible
schedule, and contradictions fire only on truly infeasible instances.
STILL not implemented (do not claim them): the energy-based time-bound
ADJUSTMENT rules, and the cumulative timetable profile adjustments.
