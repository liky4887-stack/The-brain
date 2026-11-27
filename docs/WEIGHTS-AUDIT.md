# Setup / lateness weight audit (2026-11-27, results branch monolith-results, 123 raw JSON files)

Requirement (user, Nov 26 10:35 PM and 11:19 PM): the CG setup weight (50) and the monolith calibration setup weight (27 at the time) must not differ in any comparison; every comparison shows setup and lateness weights. A comparison with different weights measures the weights.

Method: every raw JSON on `monolith-results` scanned for `weights.*`, `calibration.setup_weight`, `*.late_weight`. Code defaults read from `two_level.py` (SETUP_W 50, LATE_W 1000, EARLY_W 0.001) and from the runners on main.

| Rows | Setup weight | Lateness weight | Source in the record |
|---|---|---|---|
| calib / rerun monolith rows (root: `cs-calib*` 15 files; `rerun/` 5 files) | 2.30 to 24.83, a different value per row (EOQ-calibrated: S = TBO^2 x 0.001 x median daily demand / 2) | not recorded in these rows | `calibration.setup_weight`, `holding_weight` 0.001 |
| root `cs-easy-*`, `cs-hard-*`, `exp-hard128-*` (14 files) | NOT DETERMINABLE: no weights field and no calibration block; the runner default of the day is not recorded in the row | not recorded | none |
| `mono-plan/` mp-v1-*, mp-v2-* (12 files), `mpv2/` mp-* (6 files): the 18 retained-plan rows | 50 | 1000 (early 0.001, energy 0) | `weights` dict |
| `mono-plan/` mp-caps*, `mpv2/` caps-* (12 files), `opt/` (2) | `mp-caps*`, `caps-*`: pool-caps records, no solve, weights not applicable. `opt/`: NOT DETERMINABLE, no weights field | n/a / not recorded | none |
| CG rows `cgcb-s*` (3 files) | 50 | 1000 (early 0.001, energy 0) | `weights` (nested in a list entry) |
| CG rows `cg2-*` to `cg7-*` (17 files), `cgv2/` (6), `cgv2b/` (6), `mlt/` (3), `trace/` (19) | NOT RECORDED. Inferred, not measured: the CG runners at main call `column_generation` without `weights`, so `DEFAULT_WEIGHTS` = 50 / 1000 / 0.001 applies. Not checked at each historical SHA | `cgv2b/` and `tolb/` record `pool_bound.late_weight` = 1000 (the lateness bound, not the solver weight) | none for the solver weights |
| `revalidation/` (1) | not applicable (validation only) | n/a | n/a |

Findings (MEASURED from the records unless marked):
1. The monolith calibration rows used setup weights 2.3-24.8 (per-row), CG used 50 (inferred). Any CG-vs-calibration-monolith comparison made so far compared different weights. This is the 50 vs 27 defect.
2. Rows with `weights.setup` 50 / late 1000 (mono-plan mp-v1/mp-v2, mpv2 mp-*) are on the same weights as the CG default, so same-pool CG vs monolith comparisons on those rows (the three agreements on 100003, 200006, 700021) are weight-consistent IF the CG rows used the default (inferred).
3. Of the CG rows, only the 3 `cgcb-*` files recorded the weights they used (50/1000); the other CG rows (51 files) did not.

Status of the fix:
- Done in this change: `cg_trace.py` passes `WEIGHTS` explicitly to the solver, seals them in the manifest (`weights`) and shows them in the class name ("weights setup 50/late 1000"). Test fails on the old runner, passes on the new. Applies to NEW rows only.
- Not done: old CG rows cannot be corrected (weights not recorded); `coupled_comparison.py`, `coupled_cg_scaling.py` do not yet record weights; the monolith calibration path still uses per-row EOQ setup weights, so a CG row and a calibration monolith row are still not comparable by construction. A guard that refuses a comparison with unequal weights does not exist. All CG numbers stay "pre weight-fix, not a claim".

## Choice made (2026-11-27, decided by the agent under the user's standing rule "results, not decisions"; reversible)

- New CG-vs-monolith comparison rows use the SAME weights on both sides, the defaults 50 / 1000 / 0.001 (early), the same as the 18 retained plans. All three CG runners and `coupled_comparison.py` now pass them explicitly and record them.
- Old calibration monolith rows (per-row EOQ setup weight 2.3-24.8) are kept as they are and labelled NON-COMPARABLE with CG. The guard `brain_core/guards/weights_guard.py` returns `calibration_weights_not_comparable` for them, `weights_differ_not_comparable` for two rows that declare different weights, and `weights_not_recorded` (never a silent pass) when a row declares none.
- Reason: it keeps the 18 validated plans and every same-pool agreement usable without re-running the calibration rows, and it needs no new runs (no spend).
- To reverse: run CG at the calibration row's S (pass `ObjectiveWeights(setup=S)` in the runner) and compare only rows whose `weights` match; the guard needs no change.
- Not wired: no code path compares a CG row with a monolith row automatically (the comparisons are made in reports), so `compare_weights` is a helper to call before filing a comparison, not an automatic stop. Tested on real raw rows from the results branch (the retained plan compares clean with a CG row at the defaults; a calibration row is flagged) when that branch is checked out locally; skipped in CI.
- `coupled_dual` (Lagrangian) has no weights argument and uses solver defaults; recorded in its row as `weights_note`.

## Same-pool CG rerun with recorded weights (2026-11-28, MEASURED)

Class: pools 0.9/0.9, n=2, 7 days, linking-M v2 (caps-v2 pools), CG wall 900 s, cap 400 iterations, concurrency 3, codespace 4 cores. CG code SHA 9615471 (ci green), weights 50/1000/0.001 sealed in each row. Monolith rows: `codespace-results/mpv2/mp-SEED.json`, SHA 821b8ed, weights 50/1000/0.001, limit 300 s, Optimal, gap 0. Each pair was compared through `benchmarks/compare_cg_monolith.py`: `weights_verdict: weights_comparable`, `pools_verdict: pools_same` (CG pools_hash equals the hash computed from the monolith caps file). Raw: monolith-results `codespace-results/wfix/`.

| Seed | CG status | Iter | CG wall | CG value | Monolith objective | Monolith minus CG | Relative |
|---|---|---|---|---|---|---|---|
| 100003 | converged (exact pricing) | 116 | 257.9 s | 134,176,888.217 (converged master LP) | 134,177,450.883 | 562.67 | 4.19e-6 |
| 200006 | stalled, bound flat (progress guard) | 247 | 460.9 s | 152,746,440.316 (last valid bound, NOT converged) | 152,747,200.117 | 759.80 | 4.97e-6 |
| 700021 | converged (exact pricing) | 203 | 413.3 s | 147,326,980.061 (converged master LP) | 147,327,889.439 | 909.38 | 6.17e-6 |

Worst row: 700021, relative 6.17e-6 (mean of the three 5.1e-6). In all three the CG value is not above the monolith optimum (valid bound), and none of the 3 runs had pool findings.

What this settles, and what it does not:
- The CG numbers with recorded weights are identical to the old unrecorded cgv2b rows (same 134,176,888.217 / 152,746,440.316 / 147,326,980.061 values to 3 decimals). So for these three seeds the inference "the old CG rows ran at the default weights 50/1000/0.001" is now consistent with a measurement: the same code path at recorded 50/1000/0.001 reproduces them. It is not proven for the other old rows (other seeds, sizes, pool factors).
- Agreement with the monolith at the same weights holds for these 3 seeds only (CG LP below the integer optimum by 4-6e-6 relative, consistent with an integrality gap, not a weight effect).
- 200006 stalls again at the same bound; it is the seed `tol_rel` handled (explicit option, not default).
- The old cgv2 / cgv2b / mlt / trace / cg2-cg7 rows still carry no weights and still do not count as results. Only rows from SHA 9615471 or later with weights in the manifest count.
- No weight difference was found for these seeds, so no old CG comparison is removed on this evidence. The calibration monolith rows (per-row EOQ setup weights 2.3-24.8) stay non-comparable with CG.
