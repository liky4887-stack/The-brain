# Roadmap: Stage 0 consolidation, then Stages 1-4

Frame set by the owner (2026-11-26): everything built so far is the
**Stage 0 foundation**. Four stages remain. This document consolidates
Stage 0 and defines what each later stage contains, what is already
built toward it, and its concrete next step. Later stages do not start
until the owner says go. Sources: docs/notes-03-ground-zero-blueprint.txt
(Stages 0-5), docs/plan-beating-dios.txt (Phases 0-3), docs/DECISIONS.md
(rules that do not relax), docs/BOOKS.md (full book log).

## Stage 0 - the consolidated foundation (current state)

### The engine core (ground-zero Stages 0-4, complete)

One bounded planning problem built to the blueprint's exit gates:
`domain.py` (validated input records), `problem.py` (solver-neutral
representation), two independent solver adapters (CP-SAT interval
model, Li linear-ordering model) that cross-validate each other,
`validation/` (independent plan validator), `exhaustive.py`
(brute-force optimality baseline), locked golden scenarios with
explicit exhaustive-vs-solver-locked status. 149 tests, all passing.

### The book-derived library (20 skills, docs/skills/)

| Area | Module | Source |
| --- | --- | --- |
| Modeling patterns | `modeling/patterns.py` | Williams |
| Single-machine scheduling | `scheduling/single_machine.py` | Bertsimas & Tsitsiklis |
| Lot sizing (Wagner-Whitin) | `lotsizing/uls.py` | Wolsey |
| CP propagation | `propagation/` (edge-finding, timetable, energy) | Handbook of CP |
| Job shop | `jobshop/` (CPM, disjunctive) | Pinedo |
| Exact simplex + LP interior point | `lp/` (returns optimal tableau) | Hillier, Vanderbei |
| Network flows | `network/flows.py` | Ahuja |
| QP / NLP / SDP interior point | `qp/`, `nlp/`, `sdp/` | Potra-Wright, Gould et al., Alizadeh-Haeberly-Overton (+ Nesterov-Todd, Dadush, Pena, Wright as skills) |
| ILP idioms | `ilp/idioms.py` | Gusfield |
| Bio-ILP models | `bio/` (species, cliques, density, RNA) | Gusfield |
| Cutting planes, branch-and-bound, TSP | `ilp/cutting_planes.py`, `ilp/branch_and_bound.py`, `ilp/tsp.py` | Fischetti |
| Puzzle modeling craft | `puzzles/` (10 models) | Hürlimann |

Every module: locked on the book's own worked answers, re-checked by
independent validators or brute-force baselines, exact rational
arithmetic where the book is exact. See docs/BOOKS.md per book.

### Stage 0 gaps and known overlaps (honest inventory)

- Missing from the blueprint's Stage 2 reading list: Chen-Batson-Dang
  (Applied Integer Programming), the CP-SAT Primer (Krupke), the
  Pyomo book, Principles of Constraint Programming. Wright's 1997
  SIAM book is covered only via slides and a survey chapter; the full
  PDF is still awaited from the owner.
- No API, UI, database, or frePPLe integration: deferred by design
  (DECISIONS 2; old Stage 5), now distributed into Stages 1-4 below.
- Deliberate overlaps (cross-validation, not waste): LP solved three
  ways (exact simplex / Vanderbei IPM / CP-SAT); integer solving via
  CP-SAT vs the new exact branch-and-bound - the book modules are the
  inspectable reference implementations behind the engine choices.
- `puzzles/` and `bio/` are craft exercises per the owner's book
  pipeline, not engine code; they stay out of the engine path.

## Stage 1 - Product engine core and data foundation

Corresponds to plan-beating-dios Phase 0 remainder plus ground-zero
Stage 1 (environment) and the data side of Stage 5.

- Contains: canonical factory model as pydantic records mapped to the
  frePPLe tables; Postgres with migrations; the model compiler with
  two templates (capacitated lot sizing with setup times; flexible
  job shop with changeovers); a solver router (HiGHS for MILP lot
  sizing, CP-SAT for sequencing); reproducible dev environment
  (Docker); one sample dataset loaded and read back.
- Already built toward it: solver-neutral `problem.py`; the two
  cross-validating adapters; Wagner-Whitin lot sizing and the
  disjunctive job shop model as the mathematical cores of the two
  templates; the exact LP/MILP reference stack; the validation and
  honesty machinery the gates require.
- Gate (from the plan): Taillard ta01-ta10 within 5% of best-known
  makespans in 60 s; a 20-instance MIPLIB subset as a solver
  regression suite; same small plant data gives the same feasible
  plan in frePPLe and in the compiler.
- Concrete next step: write the canonical-record schema (products,
  operations, resources, calendars, orders, inventory, setup times)
  mapped to frePPLe's data model, with the validator rules from
  ground-zero Stage 2. Everything else in Stage 1 builds on it.

## Stage 2 - MVP: one food plant, weekly plan

Corresponds to plan-beating-dios Phase 1. **In progress** (started
2026-11-25, owner go-ahead by voice note): slice 1 merged - the
synthetic Makkook-scale F&B generator
(`packages/brain-core/brain_core/synthetic/fnb_factory.py`): 17 lines,
96 x 15-minute slots per line-day, 4,001 SKUs, sequence-dependent
changeovers with allergen washdowns, feasible-by-construction ground
truth checked independently. Slice 2 merged: the rolling-horizon
two-level solve (bucket MILP by HiGHS + exact per-day CP-SAT state
sequencing + independent validator; gate passed at Makkook scale:
feasible plan, 0 late, 238.5s solve wall vs the 900s gate). Slice 3
merged: CSV ingestion of the canonical records with a data-quality
score (stdlib csv + pydantic; dlt/Pandera deviation recorded in
DECISIONS.md). Slice 4 merged: the
cockpit data API (read-only JSON + SVG Gantt; Next.js deferral
recorded in DECISIONS.md). Slice 5 merged: the back-test harness
(optimizer vs the documented EDD first-fit naive baseline, both
scored by the same independent validator). Stage 2 gates: (1)
Makkook-scale synthetic instance (17 lines, 96 x 15-min slots, 4,001
SKUs, 7 days) - feasible plan, 0 late units, 0 validation problems,
238.5s solve wall vs the 900s gate; (2) 12-week back-test (6 lines,
400 SKUs, 7 days, seeds strided 1000+7919w) - optimizer beats the
naive baseline on changeover minutes in all 12 weeks, 27.7% fewer
changeover minutes in total (37,950 vs 52,470), 0 late units vs
10,202 naive, all plans valid. STAGE 2 COMPLETE.

- Contains: ingestion (dlt + Pandera) from an Odoo/CSV export with a
  data-quality score; rolling-horizon solve - daily buckets by MILP
  (HiGHS), then line sequencing by CP-SAT; a planner-readable web
  cockpit (Next.js, Gantt on vis-timeline, KPI cards, late-order
  explanations); back-test against 12 weeks of plant history.
- Already built toward it: the compiler templates from Stage 1;
  single-machine and job-shop scheduling modules; lot sizing; the
  explanation hooks (independent validator findings, solver status).
- Gate: synthetic instance at Makkook's published size (17 lines, 96
  slots, 4,001 SKUs) - feasible plan under 15 minutes, gap logged;
  back-test beats the plant's actual changeover hours or late orders.
- Concrete next step (after Stage 1's gate): the ingestion pipeline
  and the synthetic Makkook-size instance generator, both testable
  without any UI.

## Stage 3 - v1: the features DIOS sells

Corresponds to plan-beating-dios Phase 2.

- Contains: event-triggered local re-solves (machine down, rush
  order) with a plan-stability score; objective weight sliders
  (cost, on-time, energy, changeovers) and side-by-side scenarios;
  forecasts with ranges feeding safety stock; audit log and
  decision-latency timestamps; binding-constraint and infeasibility
  explanations in plain words.
- Already built toward it: Williams' objective-trade-off patterns;
  the exact LP duals for binding-constraint explanation on linear
  parts; the validator that localizes which rule a change touches.
- Gate: single-machine breakdown on the Stage 2 instance - new plan
  under 60 s, under 5% of orders moved, cost within 2% of a full
  overnight re-solve; forecasts beat seasonal-naive; four-week shadow
  pilot with both plans scored.
- Local re-solve mechanic MERGED (2026-11-25,
  packages/brain-core/brain_core/reschedule/local.py): freeze outside
  scope, re-solve event days with the line blacklisted, absorber days
  build ahead, forward activation, pool never dropped, stability
  metric + same independent validator. Gate PASSED at Makkook scale
  (LINE-01 down day 2, known at horizon start): local re-solve 0.4s
  (gate 60s), 0.968% of units moved (gate 5%), proxy cost +0.015% vs
  the full overnight re-solve honoring the event (gate 2%), 0 late.
- Objective weight sliders + side-by-side scenarios MERGED
  (2026-11-25): ObjectiveWeights (setup/late/early/energy sliders)
  threaded through BOTH the bucket MILP and the day model;
  solve_scenarios runs variants and compares them on a common
  default-proxy scale so numbers stay comparable; the validator
  reports production_minutes and energy_proxy KPIs.
- Forecasts with ranges feeding safety stock MERGED (2026-11-25,
  packages/brain-core/brain_core/forecast/holt_winters.py): a model
  ZOO - Holt-Winters (additive + multiplicative, smoothing grid,
  classical-decomposition init), seasonal-naive, and
  seasonal-naive-with-drift - selected per SKU at each decision time
  by measured rolling-origin MAE over the history's own recent folds.
  The naive baselines stay in the zoo so the selector falls back to
  them when HW genuinely loses; the model family is never assumed to
  win. Gate PASSED on 6 synthetic SKUs x 156 weeks (trend + growing
  seasonal amplitude, 10% noise): zoo never meaningfully worse than
  seasonal-naive per SKU (worst +1.7%), 17.3% better overall;
  forecast ranges' coverage measured and reported per SKU. Safety
  stock = Z_95 * one-step residual sigma feeds buffer.minimum,
  never lowering an existing minimum.
- Audit log + decision-latency timestamps MERGED (2026-11-25,
  packages/brain-core/brain_core/audit/log.py): append-only stdlib
  JSONL, one line per committed decision - trigger, event/decision
  timestamps, measured wall time and decision latency, sha256 plan
  digest over canonical assignments, validator KPIs.
- Plain-words explanations MERGED (2026-11-25,
  packages/brain-core/brain_core/explain/why.py): binding line-days
  (FULL at measured minutes, the validator's own threshold),
  per-SKU lateness (due vs made by due day + measured capacity use
  on eligible line-days), aggregate infeasibility (required vs
  available minutes, per sole-eligible line). Every sentence is
  recomputed from records + returned plan; no solver claims, no LLM.
- Four-week shadow pilot GATE PASSED (2026-11-25, evidence
  /tmp/shadow4.json): 4 weekly instances at 6 lines x 400 SKUs x 7
  days, optimizer and naive both scored by the independent validator
  and both written to the audit log. All 8 plans valid; changeovers
  12,600 vs 17,730 min (-28.9%); lateness 0 vs 0 (dust < 1e-9);
  measured optimizer decision latency ~60.3s per week.
- STAGE 3 COMPLETE (2026-11-25): all six slices merged.

## Stage 4 - Beat DIOS at scale

Corresponds to plan-beating-dios Phase 3.

- Contains: decomposition by plant and time (mpi-sppy / Ray), MILP
  neighbourhood search; a simulation twin with a per-plan robustness
  score; the LLM copilot over the API (drafts and answers, never
  decides - DECISIONS 3); routing (PyVRP/OSRM) and staffing
  (Timefold); multi-tenant deployment with an on-prem installer;
  optional commercial solver pass-through for the biggest clients.
- Already built toward it: the solver-neutral architecture (the
  router keeps commercial solvers pluggable); the SDP/QP/NLP
  interior-point stack for future nonlinear cost curves; the honesty
  and test standards the copilot's drafted constraints must pass.
- Gate: synthetic 2M-constraint / 1.4M-variable plan feasible in
  under 30 minutes on one 32-core server, gap logged; routing within
  1% of CVRPLIB X best-known; copilot answers 50 real planner
  questions against solver output.
- Plant decomposition MERGED (2026-11-25,
  packages/brain-core/brain_core/decompose/): union-find partition
  into SKU-closed line cells (independence PROVEN from the records;
  unassignable demands are reported, never dropped), parallel cell
  solves via stdlib ProcessPoolExecutor (no Ray/mpi-sppy dependency
  yet), merged plan validated on the FULL factory by the same
  independent validator. Gate PASSED (evidence
  /tmp/gate4-decompose.json): 2 plants x (6 lines x 400 SKUs) x 7
  days - decomposed wall 60.5s bounded by the slowest cell (60.4s)
  vs the 120.8s sequential lower bound; 0 late; 6,240 vs naive 8,280
  changeover minutes (-24.6%); both plans valid.
- Remaining Stage 4: time decomposition at scale + MILP
  neighbourhood search; simulation twin with per-plan robustness
  score; LLM copilot over the API (drafts/answers, never decides);
  routing (PyVRP/OSRM) and staffing (Timefold); multi-tenant
  deployment with an on-prem installer; optional commercial solver
  pass-through.

## Working rules across all stages

- DECISIONS.md holds: toy-first gates, frePPLe as data/screens only,
  LLMs never decide, license checks (no AGPL), independent
  validation, honest statuses, claims track tests.
- The book pipeline continues in parallel: each new reference book is
  read twice, distilled to docs/skills/, converted to tested code at
  the 48-books craft standard, logged in docs/BOOKS.md, and merged.
