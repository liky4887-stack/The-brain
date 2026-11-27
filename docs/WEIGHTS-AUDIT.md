# Setup / lateness weight audit (2026-11-27, results branch monolith-results, 123 raw JSON files)

Requirement (user, Nov 26 10:35 PM and 11:19 PM): the CG setup weight (50) and the monolith calibration setup weight (27 at the time) must not differ in any comparison; every comparison shows setup and lateness weights. A comparison with different weights measures the weights.

Method: every raw JSON on `monolith-results` scanned for `weights.*`, `calibration.setup_weight`, `*.late_weight`. Code defaults read from `two_level.py` (SETUP_W 50, LATE_W 1000, EARLY_W 0.001) and from the runners on main.

| Rows | Setup weight | Lateness weight | Source in the record |
|---|---|---|---|
| calib / rerun monolith rows (root dir 15 files, `rerun/` 5 files) | 2.30 to 24.83, a different value per row (EOQ-calibrated: S = TBO^2 x 0.001 x median daily demand / 2) | not recorded in these rows | `calibration.setup_weight`, `holding_weight` 0.001 |
| `mono-plan/` (12 of 18 files), `mpv2/` (6 of 12), 3 files in `codespace-results/` | 50 | 1000 (early 0.001, energy 0) | `weights` dict |
| `mono-plan/` (6), `mpv2/` (6), `opt/` (2) | NOT DETERMINABLE: the row has no weights field. The runner at that SHA used `SETUP_W x setup_scale` or the default (code path in monolith_scaling.py ~line 583-593), but the row does not say which `setup_scale` | not recorded | none |
| CG rows: `cgv2/` (6), `cgv2b/` (6), `mlt/` (3), `trace/` (19), `cg2-*` and other CG files in `codespace-results/` (17) | NOT RECORDED. Inferred, not measured: the CG runners at main call `column_generation` without `weights`, which then uses `DEFAULT_WEIGHTS` = 50 / 1000 / 0.001. Not checked at each historical SHA | `cgv2b/` and `tolb/` record `pool_bound.late_weight` = 1000 (the lateness bound, not the solver weight) | none for the solver weights |
| `revalidation/` (1) | not applicable (validation only) | n/a | n/a |

Findings (MEASURED from the records unless marked):
1. The monolith calibration rows used setup weights 2.3-24.8 (per-row), CG used 50 (inferred). Any CG-vs-calibration-monolith comparison made so far compared different weights. This is the 50 vs 27 defect.
2. Rows with `weights.setup` 50 / late 1000 (mono-plan, mpv2) are on the same weights as the CG default, so same-pool CG vs monolith comparisons on those rows (the three agreements on 100003, 200006, 700021) are weight-consistent IF the CG rows used the default (inferred).
3. No CG row recorded the weights it used.

Status of the fix:
- Done in this change: `cg_trace.py` passes `WEIGHTS` explicitly to the solver, seals them in the manifest (`weights`) and shows them in the class name ("weights setup 50/late 1000"). Test fails on the old runner, passes on the new. Applies to NEW rows only.
- Not done: old CG rows cannot be corrected (weights not recorded); `coupled_comparison.py`, `coupled_cg_scaling.py` do not yet record weights; the monolith calibration path still uses per-row EOQ setup weights, so a CG row and a calibration monolith row are still not comparable by construction. A guard that refuses a comparison with unequal weights does not exist. All CG numbers stay "pre weight-fix, not a claim".
