# The Brain

Factory planning engine: turns factory data (the Map), explicit rules (the
Rulebook) and one clear objective (the Goal) into a validated plan (the
Result). frePPLe holds data and screens; this repo is the optimization
brain. See docs/DECISIONS.md for the rules this build does not break.

## Status

Stages 0-4 of the ground-zero blueprint (docs/notes-03): the engine core,
plus modules distilled from the owner's reference books (see
docs/BOOKS.md): each book is read twice, distilled into a skill in
docs/skills/, and converted into tested code at the same craft standard.
No API, no UI, no database yet (Stage 5).

## Layout

- `docs/` - specs, model spec, decisions, honesty note, the owner's plan
  and research notes; `docs/skills/` holds the distilled book skills
- `packages/brain-core/` - the engine core (Python package `brain_core`)
  - `brain_core/domain.py` - validated input records (pydantic)
  - `brain_core/problem.py` - solver-neutral problem representation
  - `brain_core/solvers/` - two independent solver adapters (CP-SAT
    interval model and the Li linear-ordering model) that cross-validate
    each other
  - `brain_core/validation/` - independent plan validator
  - `brain_core/exhaustive.py` - brute-force baseline for optimality tests
  - `brain_core/modeling/patterns.py` - Williams' LP/MIP modeling patterns
  - `brain_core/scheduling/single_machine.py` - Bertsimas & Tsitsiklis:
    WSPT ordering and supermodular separation
  - `brain_core/lotsizing/uls.py` - Wolsey: Wagner-Whitin lot-sizing DP
  - `brain_core/propagation/` - Handbook of CP: disjunctive, edge-finding,
    not-first/not-last, timetable and energy overload checks
  - `brain_core/jobshop/` - Pinedo: CPM forward/backward and the
    disjunctive-graph job shop model
- `data/examples/` - hand-computed example instances
- `data/scenarios/` - locked golden scenarios (honesty: exhaustive-locked
  vs solver-locked is explicit in the file)
- `tests/` - the full suite: every module is checked against brute force
- `apps/`, `deploy/` - placeholders for the Stage 5 product layer

## Run the tests

```bash
pip install ortools pydantic pytest
pytest tests/ -q
```

## Honesty

What works is exactly what the test suite proves (see docs/DECISIONS.md).
Reference-material availability is stated in docs/BOOKS.md.
