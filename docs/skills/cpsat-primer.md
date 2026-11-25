# CP-SAT Primer

> Distilled from **"The CP-SAT Primer: Using and Understanding Google OR-Tools' CP-SAT Solver"** by Dominik Krupke et al. (github.com/d-krupke/cpsat-primer), licensed **CC-BY 4.0**. Read twice; chapter map and full text at /tmp/cpsat-primer.md during the session. Feeds The-brain's solver router (Stage 1), local re-solve and explanations (Stage 3).

## What CP-SAT is (and is not)

- A **CP** solver with **SAT**-style conflict learning (lazy clause generation) on an **integer** backend. Everything is integral: floats must be scaled (The-brain: `WEIGHT_SCALE = 1000`, already in `solvers/`).
- It *is* strong on: scheduling (no_overlap is its crown jewel), routing, assignment, packing, anything with disjunctive structure.
- It is *not* an LP/MIP solver: pure continuous linear models belong to HiGHS. The-brain's router (Stage 1) sends pure LP to HiGHS, disjunctive/integer to CP-SAT — matching the primer's guidance.
- **Stateless**: no learned clauses or incumbents carry between `solve()` calls. "Warm start" = hints only (below).

## The constraint vocabulary (with primer line anchors)

| Constraint | Use | Gotcha |
|---|---|---|
| `add_all_different` | assignment | fine |
| `add_circuit` / `add_multiple_circuit` (~L1951) | TSP/routing | arcs on literal-indexed edges; a circuit must cover all nodes in its subgraph |
| `add_no_overlap` (~L2295) | 1-machine / resource disjunctive | interval vars; optional intervals via `presence` literal |
| `add_no_overlap_2d` (~L2627-2785) | packing, two-resource-time | expensive; prefer decompositions for large n |
| `add_automaton` (~L2850) | sequence-dependent rules (changeovers!) | state machine over transition triples; good for F&B allergen sequencing |
| `add_reservoir` (~L2911) | cumulative stock over time (tank levels) | min/max level events; natural for silos/inventory |
| `add_cumulative` | resource capacity over time | the workhorse for multi-crew lines |
| `add_max_equality` etc. channeling | linking | **ortools 9.15 changed several signatures** — check `dir()` before assuming primer code runs |
| `add_piecewise_linear`? no — linearize manually (~L3083) | economies of scale | use only_enforce_if + big-M or convex hull |

## Hints and warm starts (~L3857, ~L5560)

- `model.add_hint(var, value)`: seeds search; **never constrains** — a wrong hint costs time, never correctness. Partial hints are fine.
- Stage 3 pattern: solve → user edits (a rush order, a machine down) → re-solve with the old solution as hint. Verified in `test_warm_start_after_change_matches_cold_solve`.
- **Verify a hint before trusting it**: `assert_hint_feasible` fixes the hinted vars on a *clone* via reified equalities + assumptions and checks feasibility. Faster than discovering a bad hint by a slow solve.

## Explanations: assumptions and unsat cores (~L4037)

- The recipe: guard each constraint `ct` with an indicator: `model.add(ct).only_enforce_if(ind)`; `model.add_assumptions(indicators)`; if `INFEASIBLE`, `solver.sufficient_assumptions_for_infeasibility()` returns assumption indices pointing into the conflict.
- **The returned set is a pointer, not a full core** (The-brain test: on the primer's own x+y≤4, x+z≤2, z≥4 example it returned {c3} alone, which is feasible in isolation!). `_minimal_core` in `brain_core/solvers/cpsat_tools.py` refines it by deletion filtering (toggle assumptions, keep dropping while still infeasible) → a true minimal infeasible subset by constraint *name*.
- Only **reifiable** constraints can be guarded (linear bounds, etc.). Global constraints (no_overlap, circuit) cannot take only_enforce_if directly.
- Stage 3's plain-words "why can't this plan work" = minimal core names → human-readable constraint descriptions.

## Decision strategies (~L4257) and parameters (~L3285)

- `add_decision_strategy`: hint variable ordering. Rarely beats default search; measure before keeping.
- Parameters that matter: `max_time_in_seconds`, `num_workers` (portfolio search, nondeterministic!), `log_search_progress`, `relative_gap_limit`, `random_seed`. Read the log (~L4327): #vars, #constraints, presolve removals, objective bounds trajectory.
- Nondeterminism with workers > 1: **never lock a solution's exact values in a test; lock the objective** (recomputed from the assignment, per The-brain honesty rules).

## Coding patterns (Part 2, ~L4954)

- Model in small functions returning (vars, constraints); keep indices in dicts, not parallel lists.
- Optional intervals + presence literals for alternative machines/modes (Stage 1's flexible job shop compiler uses this).
- Multi-objective: weighted sum with scaled integer weights, or lexicographic via solve-fix-resolve.

## Two real API traps verified in code (ortools 9.15)

1. **Bounded expressions are bound to their model object.** Adding `x + z <= 2` built on model A into model B silently binds wrong variable indices — produced a phantom infeasible "core". `explain_infeasibility` therefore takes the caller's model and works on a **clone** (clone preserves indices, original IntVar objects remain valid on it).
2. `get_variable_from_index` does not exist (9.15). To fix variables on a clone, use reified equality + assumptions (`assert_hint_feasible`).

## Code produced from this book

`packages/brain-core/brain_core/solvers/cpsat_tools.py` — `solve_with_hint`, `assert_hint_feasible`, `explain_infeasibility` (minimal core by deletion filtering). Tests in `tests/test_cpsat_tools.py` (5): the primer's locked unsat-core example, both hint-feasibility directions, wrong-hint-still-optimal, warm-start-after-change equals cold solve.

## Router rules The-brain keeps from this book

- Pure LP / large MIP with tight LP relaxation → HiGHS; disjunctive scheduling/routing/assignment → CP-SAT.
- Scale floats to ints at the compiler boundary, never inside solvers.
- Every plan re-validated independently; CP-SAT statuses reported honestly (OPTIMAL only with proven bound).
