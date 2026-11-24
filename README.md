# The Brain

Factory planning engine: turns factory data (the Map), explicit rules (the
Rulebook) and one clear objective (the Goal) into a validated plan (the
Result). frePPLe holds data and screens; this repo is the optimization
brain. See docs/DECISIONS.md for the rules this build does not break.

## Status

Stages 0-4 of the ground-zero blueprint (docs/notes-03): the tiny engine
core. One machine, weighted-tardiness scheduling, CP-SAT, independent
validator, exhaustive-baseline tests. No API, no UI, no database yet
(Stage 5).

## Layout

- `docs/` - specs, model spec, decisions, honesty note, the owner's plan
  and research notes
- `packages/brain-core/` - the engine core (Python package `brain_core`)
  - `brain_core/domain.py` - validated input records (pydantic)
  - `brain_core/problem.py` - solver-neutral problem representation
  - `brain_core/solvers/` - solver adapters (CP-SAT first)
  - `brain_core/validation/` - independent plan validator
  - `brain_core/exhaustive.py` - brute-force baseline for optimality tests
- `data/examples/` - hand-computed example instances
- `tests/` - Stage 4 test suite (runs the exhaustive baseline)
- `apps/`, `deploy/` - placeholders for the Stage 5 product layer

## Run the tests

```bash
pip install ortools pydantic pytest
pytest tests/ -q
```

## Honesty

What works is exactly what the test suite proves (see docs/DECISIONS.md).
Reference-material availability is stated in docs/BOOKS.md.
