# RUNS log

Every run that produced, or was meant to produce, a number. Cancelled, broken and invalid runs stay listed with their status. Newest last. Format: id | what | SHA | status | note.

## Actions runs
- 45737026860 | ladder step 6 (2048 plants / 256 shards) | see scale_history | PASS | 0 validation problems
- 45858321122 | ladder step 7 block B (plants [2048, 4096), 256 shards, 4096 windows) | 2e4b75e81a64 | OPEN, one plant, one window, dense day (plant 2245, seed 3245, window 1, day 5; exact assignment+sequencing undecided after 600 s) | 256/256 shards, 665,979 assignments validated, 1 problem; run wall 27,916 s; per-plant solve min 125.8 / mean 577.6 / max 2,231.6 s; shard wall 2,370-2,959 s. Not a PASS; UNKNOWN is not infeasible.
- 45915490926 | ladder step 7 block A (plants [0, 2048), same SHA, pin/block-a-2e4b75e) | 2e4b75e81a64 | OPEN, one plant, one window, dense day (plant 1868, window 1, day 3; exact assignment+sequencing UNKNOWN after 120 s, undecided, not disproven) | 256/256 shards, 4,096 windows, 666,395 assignments validated, 1 problem; run wall 25,266 s (00:13:39Z to 07:14:45Z); per-plant solve min 123.3 / mean 571.1 / max 1,926.1 s; shard wall 901.7-2,672.4 s; window MIPs optimal 3,801, time-limited 295, max gap 0.0015; distributed_wall 3,244.1 s, merge_validate 571.7 s; extrapolated single 32-core box est. 123,842 s (estimate, not measured). Not a PASS. A and B hit DIFFERENT plants (1868 vs 2245): the dense-day UNKNOWN is not a single-plant accident.
- 45863417715 | coupled-crossover rerun | 2bc3e6b | QUEUED | needs ub_validation_problems == [] per replica
- 45861214473 | fail-fast probe | probe/failfast | INCONCLUSIVE | jobs ran serially; re-run after the queue is free

## Monolith / calibration runs (codespace, 4 cores, AMD EPYC 7763, 1 thread per solve, default MIP solver)
- calib v1 (min lot = 1 TBO) | INVALID | forced lateness; all v1 numbers discarded
- IPM "72 s" result | INVALID | solver=ipm on a MIP ignores integrality (nodes -1); retracted, guard flags INVALID-NOT-A-MIP
- hard512 | Time limit, gap 99.9996%, no certified bound; caps 1,036.8 s separate | valid failure record
- easy512 | Optimal | valid
- calib3 v2 pools 1.5x n=4 seeds 0, 1, 2 | valid; seed 0 independent, seed 1 light coupling, seed 2 forced lateness
- calib3 v2 pools 1.5x n=2 seed 0 | valid
- "calib3 2.0x" first attempt (10:47 to 11:15 EET) | INVALID | caps cache served the 1.5x caps (cache key ignored MS_CLASS_JSON); really 1.5x data. Fixed on main baa1233
- calib3 pools 2.0x n=4 seeds 0, 1, 2 (restart 11:15 EET) | RUNNING

## caps-v1 vs caps-v2 (2026-11-27)
- caps-v1 = pools from solo plans of the core bucket solver WITHOUT min-lot rows. On min-lot classes (calib*) this starved plant 204 (seed 2): late unit-days 6,715.082 at 1.5x, 2.0x and any single pool tightness in [1.5, 2.0]. All calib results before 2026-11-27 00:20 EET are caps-v1: valid as measured data, never compared with caps-v2 numbers.
- caps-v2 (MS_CAPS_V=2, main 8e51239) = pools from solo plans with the same weights and min-lot rows as the monolith. Test: calib3 1.5x seed 2 n=2 -> late 0.0.
- calib sweep (runner C) stopped at calib1 n=8; all its files are caps-v1. calib3 n=4 seeds 0-2 at 1.5x and 2.0x are caps-v1.
- Rerun plan: seeds 0-4, 1.5x and 2.0x, caps-v2.
- caps-v2 rerun, calib3 v2 pools 1.5x n=4 seeds 0-4: DONE 2026-11-27 01:37 EET. Combined plans valid vs real pools on all 5 seeds; late unit-days 0, 0, 0, 2,823, 9,275; min_lot_independent 0 violations on all; monolith (600 s) plan above the sum of optima by 0.32%, 0.93%, 0.72%, 0.002%, 0.004%.
- caps-v2 rerun, calib3 v2 pools 2.0x n=4 seeds 0-4: RUNNING.
- crossover class supplier 1.1x / labor 1.1x (separate class from 0.75x / 0.8x), 10 replicas, sizes 2, 4, 8, monolith limit 300 s: RUNNING (started 01:13 EET).
- dedupe full suite on codespace (fix/dedupe-lines-r2 at 19994c6): RUNNING (started 00:53 EET); the workspace run was killed (shell pauses between calls).

## Rules
- Class name carries pool tightness (1.5x and 2.0x are never compared).
- A combined plan counts as valid only if it passes validate_coupled_plan; otherwise the sum is a lower bound only.
- Every row: SHA, seed, time limit, machine, concurrency, caps time next to MIP time, bound (proven or estimated), plan, gap, validator result.

## Step 7 status (user decision 2026-11-27 12:35 EET)
- Step 7 is OPEN: one plant, one window, dense day (A: plant 1868, B: plant 2245, SHA 2e4b75e). No third structural attempt without a new idea. scale_ceiling stays at 2048 plants, not 4096, until resolved.
- Rows rebuilt from reports (raw JSON lost in the 2026-11-27 08:12 EET codespace reboot) are labeled "from report, raw JSON lost". Only rows that carry a claim are re-run. Results are synced to branch monolith-results (codespace-results/) as they finish.
- Main CI (ci.yml) has been cancelled at its 30 min timeout on every recent push (d1e7c52, a08b488, dc767a4, 8bcaa18, 1d0dd23, a3e1cbc, 9b4534c, c2e43a7): no result on main is called "passed" until CI is green. Pending core merges (dedupe, dense-day, CG master fix) wait.
