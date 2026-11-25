# Bertsimas & Tsitsiklis — Introduction to Linear Optimization (Athena Scientific)

Distilled 2026-11-25 from the user's full scanned copy (301 PDF pages, no
text layer). Read via OCR of ch.10-12 (integer programming formulations,
integer programming methods, the art in linear optimization) in two passes;
every theorem, formulation, and algorithm cited below was verified against
the rendered page images, not trusted from raw OCR. Chapters 1-9 (geometry,
simplex, duality, sensitivity, large-scale methods, network flows,
complexity, interior point) were identified from the table of contents but
not OCR'd; do not cite them from this skill.

## Formulation strength (ch.10)

- Formulation A is at least as strong as formulation B if the LP-relaxation
  feasible set of A is contained in that of B (P_A subset of P_B). Strength,
  not model size, is what makes an integer program tractable.
- Ideal formulation: one whose LP relaxation is the convex hull of feasible
  integer solutions. Strong formulations can have exponentially many
  constraints and still be practical via separation (cutting planes).
- Theorem 10.1 (verified against page image): for the minimum spanning tree
  problem, the subtour elimination formulation (sum_{e in E(S)} x_e <=
  |S| - 1 for all S) is strictly stronger than the cutset formulation
  (sum_{e in delta(S)} x_e >= 1), and the cutset LP relaxation has
  fractional extreme points. An exponential family can be the strong one —
  constraint count is the wrong metric.

## Integer programming methods (ch.11)

- Branch and bound: exact, intelligent enumeration; LP relaxations give the
  bounds. Deep cuts accelerate it (branch and cut).
- Dynamic programming (Example 11.7, verified): TSP recursion
  C(S, k) = min over m in S\{k} of C(S\{k}, m) + c_mk, C({1},1) = 0;
  O(n^2 2^n) time — exponential but beats n! enumeration; practical to
  about 20 cities. Guidelines: view a solution as staged decisions; state
  summarizes the relevant past; recursion on optimal cost.

## Single-machine scheduling (sec. 12.5, all verified against page images)

- Problem: jobs i = 1..n, weights w_i > 0, processing times p_i > 0,
  nonpreemptive, minimize sum_i w_i C_i.
- Theorem 12.1 (WSPT): if w_1/p_1 >= w_2/p_2 >= ... >= w_n/p_n, the
  sequence 1,2,...,n is optimal (adjacent-interchange proof). Corollary:
  when w_i = p_i for all i, every nonidling schedule is optimal.
- The feasible completion-time vectors form a nonconvex union of
  polyhedra, but their convex hull is exactly described by the
  supermodular inequalities (12.1):
      sum_{i in S} p_i C_i >= 1/2 sum_{i in S} p_i^2
                            + 1/2 (sum_{i in S} p_i)^2    for all S.
  The RHS p(S) is supermodular. For n = 2 the hull is
  C_1 >= p_1, C_2 >= p_2, p_1 C_1 + p_2 C_2 >= p_1^2 + p_2^2 + p_1 p_2.
- Theorem 12.2 (separation, O(n log n)): sort jobs by increasing C_i and
  check only the n nested prefixes; the prefix maximizing
  p(S) - sum_{i in S} p_i C_i is the most violated set. Exponentially many
  inequalities, polynomial separation — this is why strong formulations are
  usable.
- With release times, deadlines, and precedence constraints the problem is
  NP-hard, but (12.3) — the same supermodular inequalities plus
  r_i <= C_i <= d_i and C_j >= C_i + p_j — gives a strong LP lower bound
  solvable by cutting planes with the Theorem 12.2 separator. Sorting the
  LP completion times into a real schedule is a 2-approximation
  (Z_LP <= Z_H <= 2 Z_LP, the best known bound for that problem; the
  book's OCR garbles the "2-approximation" label but the inequality chain
  is unambiguous on the page).

## Job shop scheduling (sec. 12.5, verified)

- Model: n jobs, m machines, k stages each; task (i,j) has processing time
  p_ij; machine r must process the set M_r; minimize sum_i w_i C_ik.
- LP lower bound (12.4): minimize sum_i w_i C_ik subject to the
  supermodular machine inequalities for every S subset of M_r and every r,
  and precedence C_ij >= C_{i,j-1} + p_ij. Separation runs in
  O(mn log n) via Theorem 12.2 per machine.
- Rounding heuristic: sort each machine's tasks by LP completion times,
  process in that order as tasks become available. Branch and bound on
  top: if tasks (i,j), (k,l) share machine r with C_kl < C_ij + p_ij and
  C_ij < C_kl + p_kl, branch on which task goes first.

## Cross-book synthesis (Williams, Li, Bertsimas & Tsitsiklis)

All three converge on the same law: LP-relaxation strength drives IP solve
time. Williams says disaggregate and use realistic big-M; Li uses strong
linear-ordering formulations; B&T prove why — the strong formulation
approximates the convex hull, and exponential families are fine when
separation is fast. The-brain applies this as: independent formulations
must agree with exhaustive enumeration on every golden scenario, and
single-machine subproblems use WSPT orderings and the Theorem 12.2
separator for bounds.

## Code

packages/brain-core/brain_core/scheduling/single_machine.py implements
WSPT ordering, completion-time evaluation, the supermodular inequalities
(exact integer arithmetic, doubled to avoid halves), and the Theorem 12.2
separation algorithm. tests/test_single_machine.py validates WSPT against
all permutations and separation against all 2^n subsets on randomized
instances; nothing is claimed beyond those tests.
