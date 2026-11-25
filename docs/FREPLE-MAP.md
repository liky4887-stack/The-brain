# frePPLe feature mapping (2026-11-25)

frePPLe is MIT-licensed since 2026-11-25 (verified live, COPYING, v8+
dual MIT/commercial), so reading docs + code and adopting patterns is
allowed; vendoring needs a DECISIONS.md entry first.

Sources verified live today:
- Table index: frepple.com/docs/current/model-reference/index.html
- Sales orders: frepple.com/docs/current/model-reference/sales-orders.html
- Buffers: frepple.com/docs/current/model-reference/buffers.html

## Status: records vs solver semantics

Our records (records/models.py) already mirror frePPLe tables
(docstrings cite them). The gap is solver-side: the rolling stack
(rolling/two_level.py) ignores most of these fields today (verified
by grep: no references to priority/minshipment/maxlateness/buffer
.minimum in the rolling code).

| frePPLe semantic (verified) | records/models.py | rolling solver |
|---|---|---|
| demand.priority (lower = more important) | present | IGNORED |
| demand.maxlateness (hard lateness bound; 0 = cancel-if-late) | present | IGNORED (lateness is soft LATE_W only) |
| demand.minshipment (limit partial deliveries; default allows ~10) | present | IGNORED |
| demand.policy (independent / alltogether / inratio[unimplemented upstream]) | absent | absent |
| demand.batch (make-to-order pegging to a batch/order) | absent | absent |
| demand.status (inquiry/open/closed/canceled/quote) | absent | absent |
| buffer.minimum = safety stock, SOFT, problem reported when breached | present | IGNORED (no safety-stock term in objectives) |
| buffer.minimum_calendar (time-varying safety stock) | absent | absent |
| buffer tool flag (affects pegging/criticality) | absent | absent |
| demand.constraints: export-only list of WHY late/short | n/a | partial - problems[] strings exist, not per-demand pegged |
| pegging (upstream/downstream order traceability) | n/a | absent |
| setup matrices / rules | present | used (day model) |
| resource skills | absent | absent |
| operation alternates/routing/split/dependencies | partial (loads = alternate lines) | partial |
| shelf life | absent (frePPLe gates it to Enterprise) | absent |

## Candidate adoption order (all ESTIMATED until measured)

1. maxlateness as a HARD bound (forbid assignments past due+maxlateness
   in the bucket model; today a demand can be arbitrarily late at
   LATE_W cost - frePPLe's hard bound is the more honest business
   rule). Cheap: one RHS change per demand-day row. Measure: gate-2M
   feasibility + objective unchanged when maxlateness is unset.
2. priority-weighted lateness (LATE_W scaled per demand; domain.py
   already has the weight concept). Cheap; needs goldens rerun.
3. safety stock: soft penalty on end-of-day inventory below
   buffer.minimum (one slack + weight per buffer-day). Medium:
   touches bucket objective and validator KPIs.
4. minshipment (delivery granularity). Medium-hard: interacts with
   chunking; defer until a use case appears.
5. policy=alltogether, batch pegging, status, skills, shelf life:
   defer - no measured need, keep watching.

Deliberately NOT adopted from frePPLe: its heuristic solver
architecture (we are exact/decomposition-based); the inratio policy
(upstream itself marks it unimplemented).
