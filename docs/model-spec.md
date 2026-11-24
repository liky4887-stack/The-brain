# Model spec (Stage 2): data semantics and formulation

## Data semantics

All times are integer minutes from a common epoch 0. All identifiers are
stable strings. All weights are positive numbers. Units are part of the spec,
not the field names, and there is exactly one unit (minutes) at this stage.

Validation happens BEFORE any model is built (blueprint layer 2). Every
error names the offending record and field; a problem that fails validation
never reaches a solver.

Rules:
- order ids unique, non-empty
- processing_time >= 0 (zero allowed: models an instant/bookkeeping step)
- due_date >= 0, deadline (if present) >= 0
- weight > 0
- a problem may contain 1..N orders and exactly one machine at this stage

## Solver-neutral representation

`SchedulingProblem` (packages/brain-core/brain_core/problem.py) is the only
object solver adapters receive. It carries validated orders and the machine.
No solver types leak into it (blueprint: solver-neutral problem
representation first).

## Formulation (CP-SAT path, first)

Per OR-Tools' CP-SAT scheduling documentation and the CP-SAT Primer
(Krupke, d-krupke.github.io/cpsat-primer):

- For each order i: interval variable (start in [0, horizon], size p_i).
  horizon = sum of processing times (tight: no reason to idle past it with a
  tardiness-only objective and no release dates).
- Machine rule: AddNoOverlap over all intervals.
- Tardiness: integer var T_i >= 0 with T_i >= end_i - due_i (linearized
  max(0, .) exactly; T_i is bounded by horizon).
- Deadline (hard): end_i <= deadline_i when present.
- Objective: minimize sum(w_i_scaled * T_i). Weights are scaled to integers
  (x1000, rounded) because CP-SAT requires integer coefficients; the scaling
  factor is recorded in solver diagnostics so reported objectives can be
  mapped back exactly.

## Why not MILP for this model

Sequencing with pairwise disjunctions in MILP needs big-M constraints whose
weak relaxations are a documented performance trap (notes-02, notes-04).
CP-SAT's native interval/no-overlap expresses the rule directly. HiGHS gets
its adapter later for linear planning/allocation models (Stage 3 exit note);
one formulation does not run unchanged on both (blueprint warning).

## Independent validation

The validator (packages/brain-core/brain_core/validation/validator.py)
shares no code with the solver. Given a problem and a plan it re-checks:
exactly-once assignment, start >= 0, end = start + p, pairwise no-overlap,
deadlines, and recomputes the objective from scratch (float weights,
tolerance 1e-6). It says nothing about optimality; optimality is proven only
against exhaustive enumeration in the test suite (Stage 4).

## Hand-checkable examples

data/examples/*.json: instances A (strict), B (tie), C (infeasible), plus
boundary cases (zero processing time, extreme times, 6-order case for the
exhaustive enumerator). Each carries its expected outcome as data, computed
by hand in docs/specs/stage0-tiny-problem.md.
