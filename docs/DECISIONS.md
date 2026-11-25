# Decisions to preserve

From the ground-zero blueprint (docs/notes-03-ground-zero-blueprint.txt) and
the user's notes. Do not relax these without an explicit instruction from
the repo owner.

1. Toy problem first. One machine, two orders, one objective, hand-computed
   answers. No scale work before Stage 4 gates pass.
2. frePPLe is the data and screens layer only. The optimization brain
   (compiler, solver routing, validation, explanation) is written here.
3. LLMs never decide plans. A future copilot drafts and answers; the solver
   decides; every drafted constraint passes tests before use.
4. License-check every dependency before it enters the tree. No AGPL in a
   paid product (Ultralytics, pm4py, OCA Odoo connector are out unless a
   commercial license is bought). Current dependencies: ortools
   (Apache-2.0), pydantic (MIT), numpy (BSD-3), scipy (BSD-3, bundles
   HiGHS MIT), pytest (MIT, dev only).
5. The validator is independent of the solver and checks every returned
   plan. A solver status is never taken on faith.
6. Honest statuses: infeasible, time-limited and errored runs are reported
   as such. No fabricated plans, no unexplained numbers.
7. Claims track tests. Nothing is said to "work" beyond what the test
   suite proves, and optimality claims cite the exhaustive baseline.

## Stage 2 deviation log

- 2026-11-25, ingestion (slice 3): the roadmap draft said "dlt +
  Pandera". Implemented with stdlib csv + pydantic instead
  (packages/brain-core/brain_core/ingest/csv_io.py). Reasons: pydantic
  is already a dependency and owns row-level validation; dlt is an
  EL(T) pipeline framework aimed at loading warehouses, not at
  tolerant row-by-row ERP export parsing with findings; Pandera would
  duplicate pydantic's row validation at this scale. No new
  dependencies added (decision 4 holds: license check trivially
  passes). Revisit if a real ERP connector (API pulls, schema
  drift tracking, incremental loads) becomes the requirement.

- 2026-11-25, cockpit (slice 4): the roadmap draft said "Next.js,
  Gantt on vis-timeline". Deferred the Next.js UI; shipped the data
  layer it would consume instead: a read-only stdlib http.server JSON
  API (/api/plan, /api/kpis, /api/late-orders) plus a zero-dependency
  SVG Gantt page (packages/brain-core/brain_core/cockpit/api.py).
  Reasons: no JavaScript toolchain or JS dependencies enter the tree
  without a license audit (decision 4); the API is the contract any
  future UI consumes, so no work is thrown away; every number served
  is recomputed by the independent validator. Revisit Next.js when a
  planner needs interactive editing, not just reading.
