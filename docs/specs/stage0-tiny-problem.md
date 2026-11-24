# Stage 0 spec: one machine, two orders

The smallest planning problem with real factory shape. Written before any
solver code, per the ground-zero blueprint (docs/notes-03).

## Entities

- **Machine M1.** One resource. Available from time 0, no calendar breaks.
  It cannot process two orders at the same time (no-overlap).
- **Order.** An order has:
  - `id` (string, unique)
  - `processing_time` (integer minutes, >= 0)
  - `due_date` (integer minutes from time 0, soft: lateness is penalized)
  - `weight` (positive number: priority multiplier on lateness)
  - `deadline` (optional integer, hard: completion after it is not allowed)

## Decisions

For each order: its start time on M1. Equivalently: the sequence of orders
on M1 (with no idle time benefit in this objective, an order starts as soon
as the machine and its predecessor allow).

## Rules (constraints)

1. Every order is processed exactly once, non-preemptively.
2. No two orders overlap on M1.
3. Start times are >= 0.
4. If `deadline` is set, completion time <= deadline.

## Objective (one only)

Minimize **total weighted tardiness**: sum over orders of
`weight * max(0, completion_time - due_date)`.

No other goals are mixed in until this one is proven correct (blueprint rule).

## Example instances and hand-computed answers

### Instance A (strict optimum)

- O1: p=3, due=5, w=2
- O2: p=2, due=3, w=1

Sequence O2,O1: C2=2 (tardy 0), C1=5 (tardy 0) -> objective 0. **Optimal: 0.**
Sequence O1,O2: C1=3 (tardy 0), C2=5 (tardy 2, weighted 2) -> objective 2.

### Instance B (tie - two optimal sequences)

- O1: p=3, due=4, w=2
- O2: p=2, due=3, w=1

Sequence O1,O2: C1=3 (tardy 0), C2=5 (tardy 2, weighted 2) -> objective 2.
Sequence O2,O1: C2=2 (tardy 0), C1=5 (tardy 1, weighted 2) -> objective 2.
**Optimal: 2, either order.** A returned sequence different from a reference
answer is NOT a failure if feasibility and objective match (blueprint rule).

### Instance C (infeasible)

- O1: p=5, due=10, w=1, deadline=3

Completion cannot beat 5 > 3. **Expected: INFEASIBLE**, reported as an honest
status, never as a plan.

## What "solved" means here

- The solver returns a status (OPTIMAL / FEASIBLE / INFEASIBLE / TIME_LIMIT /
  ERROR), never a silent number.
- A plan is accepted only if the independent validator (which shares no code
  with the solver) confirms every rule and recomputes the objective.
- Optimality claims come only from comparison with exhaustive enumeration of
  all sequences, at Stage 4.
