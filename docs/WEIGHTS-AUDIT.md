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
