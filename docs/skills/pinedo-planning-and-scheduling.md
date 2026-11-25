# Pinedo — Planning and Scheduling in Manufacturing and Services (Springer)

Distilled 2026-11-25 from the user's full digital copy (499 pages, text
layer intact - one stray byte, content clean). Read in two passes: full
structure (three parts: preliminaries; manufacturing ch.4-8; services
ch.9-12), then deep read of ch.4.2 (CPM) and ch.5.3 (job shop disjunctive
graph and disjunctive programming formulation).

## Critical Path Method (ch.4.2, implemented)

- Forward procedure (Alg. 4.2.1): S'_j = max over predecessors of C'_k,
  C'_j = S'_j + p_j; makespan = max C'_j. Yields an optimal schedule
  (unlimited resources): every job at its earliest start.
- Backward procedure (Alg. 4.2.2): from Cmax, C''_j = min over successors
  of S''_k, S''_j = C''_j - p_j. Verify min S''_j = 0.
- Slack (float) = S''_j - S'_j. Critical jobs have zero slack and form
  one or more critical paths from 0 to Cmax. The CP dispatching rule is
  the same idea used as a priority rule under resource constraints.
- Example 4.2.3 is locked in tests: 14 jobs, makespan 56, critical path
  1 -> 3 -> 6 -> 9 -> 11 -> 12 -> 14. The precedence set was reconstructed
  from Figure 4.4 and VERIFIED: it reproduces both the book's printed
  earliest and latest completion rows exactly.
- PERT (4.3): same algorithm on mean processing times
  (p_a + 4 p_m + p_b)/6; makespan estimate only, randomness changes the
  true optimum.

## Job shop as a disjunctive graph (ch.5.3, implemented)

- Each operation (i, j) (job j on machine i) is a node; conjunctive arcs
  follow job routes; each machine's operations form a disjunctive clique.
  Arc lengths = processing time of the operation the arc leaves.
- A selection D of one arc per disjunctive pair is a feasible schedule
  iff G(D) has no directed cycle (cycles can span cliques through
  conjunctive arcs, not only within one machine).
- Makespan = longest source-to-sink path in G(D) (the critical path);
  minimizing makespan = choosing disjunctive arcs to minimize it.
- Disjunctive programming formulation: min Cmax s.t. y_hj - y_ij >= p_ij
  on routing arcs, Cmax - y_ij >= p_ij, and for each machine pair
  y_ij - y_ik >= p_ik OR y_ik - y_ij >= p_ij.
- Example 5.3.1 (4 machines, 3 jobs) is the locked test instance: every
  acyclic machine sequencing's graph makespan equals direct simulation,
  and the enumeration minimum is the true optimum.

## Shifting bottleneck heuristic (ch.5.4, documented, NOT implemented)

Iteratively: solve the one-machine subproblem (1 | r_i | Lmax) for each
machine on the current partial graph, sequence the machine with the
largest Lmax (the bottleneck), fix its disjunctive arcs, reoptimize the
already-sequenced machines. The standard high-quality heuristic for job
shop makespan; needs the disjunctive graph (implemented) plus a 1|r_i|Lmax
solver (Carlier's algorithm - not yet built).

## Rest of the book (structure read, not deep-read - do not cite details)

Ch.1-3 preliminaries (models, frameworks); ch.4.4-4.7 time/cost
trade-offs and workforce-constrained projects; ch.5.2 single/parallel
machine models, 5.5 job shop CP, 5.6 LEKIN; ch.6 flexible assembly
(sequencing, Toyota mixed-model); ch.7 economic lot scheduling (ELSP,
rotation schedules - connects to Wolsey 14.4); ch.8 supply chain
planning (medium/short term models, Carlsberg case); ch.9 interval
scheduling, reservations, timetabling; ch.10 sports timetabling;
ch.11 transportation (tankers, aircraft, trains); ch.12 workforce
scheduling (days-off, shifts, cyclic staffing, crew, call centers).

## Cross-book synthesis

Pinedo supplies the scheduling domain model that the MIP books (Williams,
Li, Wolsey) and the CP handbook lack: the disjunctive graph is THE shared
representation - B&T's job shop LP (12.4) relaxes it, the handbook's
edge-finding propagates it, CP-SAT's no_overlap enforces it. CPM is the
free-resource backbone: every scheduling engine computes longest paths,
and here it is exact and tested.

## Code

packages/brain-core/brain_core/jobshop/: cpm.py (forward/backward
procedure, slack, critical path; cycle detection) and disjunctive.py
(JobShopInstance, makespan via longest path in G(D), CycleError on
infeasible selections). tests/test_jobshop.py: Example 4.2.3 locked
against the book's printed rows, CPM vs brute-force longest paths on 150
random DAGs, graph makespan vs direct simulation on all 144 machine
sequencings of Example 5.3.1, cycle detection. The shifting bottleneck
heuristic and Carlier's algorithm are documented but NOT implemented.
