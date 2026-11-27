# Solver paths: what the code actually does

Checked against main by grep and reading (2026-11-27). This page describes
the code; it makes no "one solver per problem type" claim.

## Rolling plan (the production path)

`rolling/two_level.py`:

1. **Level 1, bucket MIP.** `solve_buckets` builds the bucket model and calls
   `solve_mip` (HiGHS through scipy `milp`, `solvers/highs_mip.py`) directly.
   The router is NOT consulted on this path.
2. **Level 2, day sequences and exact days.** `solve_day_sequences` and
   `solve_day_exact` use CP-SAT (`ortools.sat`) for sequencing and
   changeovers inside a day. Also direct, not routed.

The coupled column-generation path (`rolling/coupled_dw.py`) uses SciPy's
HiGHS LP for the master and the level 1 MIP for the pricing problems.

## The router (`compiler/router.py`)

`route(factory)` returns a `RouteDecision` with reasons. It is used by the
compiler templates and tests (`tests/test_compiler.py`), not by the rolling
plan. Its rules:

| Structure | Engine |
|---|---|
| one item, one source, one resource, no multi-step BOM | `lotsizing-dp` (Wagner-Whitin, exact) |
| shared resources or BOM chains | `cpsat` |
| no operations, or no demand for in-factory items, or no resource loads | `highs` (linear balance); no current template emits a pure LP |

## Other backends present in the repo

Own simplex and interior point (`lp/`), network flows (`network/flows.py`),
local re-solve (`reschedule/local.py`), scenario comparison
(`scenarios/compare.py`). Whether each maps to a product feature such as
intervention re-solve or strategy sandbox is not established by routing
code; each is exercised by its own tests only.

## Infeasibility explanations (what exists)

- CP-SAT single-machine scheduler: minimal set of conflicting hard
  deadlines (assumptions plus deletion filter), `solvers/cpsat_solver.py`.
- MIP: family-level slack amounts and minimal set of constraint families (the "setup linking" family is labelled "includes line capacity": its big-M is built from line capacity, so a capacity shortfall shows up there),
  `solvers/highs_mip.py::explain_infeasible_mip`. The shipped bucket MIP is
  elastic (late variables) and does not become infeasible; the explanation
  applies to hard-constraint MIPs.
- Pre-solve aggregate capacity arithmetic: `explain/why.py` (proves
  overload only).
