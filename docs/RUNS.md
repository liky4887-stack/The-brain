# RUNS log

Every run that produced, or was meant to produce, a number. Cancelled, broken and invalid runs stay listed with their status. Newest last. Format: id | what | SHA | status | note.

## Actions runs
- 45737026860 | ladder step 6 (2048 plants / 256 shards) | see scale_history | PASS | 0 validation problems
- 45858321122 | ladder step 7 block B | 2e4b75e81a64 | IN PROGRESS (queued/running) | merge gate: no PASS claim without full 0..4095 shard coverage; otherwise OPEN with the number of missing shards
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

## Rules
- Class name carries pool tightness (1.5x and 2.0x are never compared).
- A combined plan counts as valid only if it passes validate_coupled_plan; otherwise the sum is a lower bound only.
- Every row: SHA, seed, time limit, machine, concurrency, caps time next to MIP time, bound (proven or estimated), plan, gap, validator result.
