# RUNS log

Every run that produced, or was meant to produce, a number. Cancelled, broken and invalid runs stay listed with their status. Newest last. Format: id | what | SHA | status | note.

## Actions runs
- 45737026860 | ladder step 6 (2048 plants / 256 shards) | see scale_history | PASS | 0 validation problems
- 45858321122 | ladder step 7 block B (plants [2048, 4096), 256 shards, 4096 windows) | 2e4b75e81a64 | OPEN, one plant, one window, dense day (plant 2245, seed 3245, window 1, day 5; exact assignment+sequencing undecided after 600 s) | 256/256 shards, 665,979 assignments validated, 1 problem; run wall 27,916 s; per-plant solve min 125.8 / mean 577.6 / max 2,231.6 s; shard wall 2,370-2,959 s. Not a PASS; UNKNOWN is not infeasible.
- 45915490926 | ladder step 7 block A (plants [0, 2048), same SHA, pin/block-a-2e4b75e) | 2e4b75e81a64 | OPEN, one plant, one window, dense day (plant 1868, window 1, day 3; exact assignment+sequencing UNKNOWN after 120 s, undecided, not disproven) | 256/256 shards, 4,096 windows, 666,395 assignments validated, 1 problem; run wall 25,266 s (00:13:39Z to 07:14:45Z); per-plant solve min 123.3 / mean 571.1 / max 1,926.1 s; shard wall 901.7-2,672.4 s; window MIPs optimal 3,801, time-limited 295, max gap 0.0015; distributed_wall 3,244.1 s, merge_validate 571.7 s; extrapolated single 32-core box est. 123,842 s (estimate, not measured). Not a PASS. A and B hit DIFFERENT plants (1868 vs 2245): the dense-day UNKNOWN is not a single-plant accident.
- 45863417715 | coupled-crossover rerun | 2bc3e6b | COMPLETED success | ub_validation_problems == [] on every replica; numbers in docs/COUPLED-MEASUREMENTS.md (crossover rerun after the UB heal)
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
- Main CI (ci.yml) was cancelled at its 30 min timeout on every push up to d1e7c52 and earlier (a08b488, dc767a4, 8bcaa18, 1d0dd23, a3e1cbc, 9b4534c, c2e43a7). Causes found and fixed on 2026-11-27: missing pyvrp and git identity, and a serial-run deadlock in decompose/parallel.py (fork pool; spawn context now). First green main CI: run 45991767618 on 3bf67b7 (399 passed, 3 skipped). Later merges, each green on the same SHA: 81f1216 dedupe, ade6822 CG master LP retry, guards 90d272c / 3ab84ed / ae575aa / b3d80bc. Results recorded before these commits were not backed by a green main CI. Dense-day stays unmerged (OPEN). repo-hygiene fails closed (branch-protection API returns 403 until a BRANCH_GUARD_TOKEN secret exists).

## Expectation under linking-M v2 (2026-11-27) - EXPECTATION, NOT MEASURED
- Measured (single plants, pools unlimited, calib3 n=4 seeds 3 and 4, plant 3, SHA 839f4da): under v1 the LP relaxation bound is 2,824,575 and 9,276,849 (all lateness penalty) and the MIP is Optimal with late 2,823 and 9,275 unit-days; under v2 the LP bound is 874.99 and 1,543.24 and the 40 s incumbents are 1,192.27 and 1,937.88 with late 0.
- Expectation (not measured for coupled or CG runs): where v1 forced lateness, objectives of order 1e6 to 1e8 drop to order 1e3 under v2. Certified relative gaps are then expected to GROW, because the LP bound is weak on cheap instances (e.g. 875 vs 1,192). That would be a regime change, not a regression. v1 and v2 numbers are never compared.
- All existing CG numbers stay "pre weight-fix, not a claim" and carry linking-M v1.

### Measured since (calib3 n=4, caps-v2 1.5x, 1 thread, code 9f765de; v1 and v2 are never compared)
- Coupled 600 s rows: v1 seed 3 Time limit, gap 1.11e-4, late 2,822.988 unit-days; v1 seed 4 Optimal, late 9,274.741; v2 seed 3 Time limit, gap 10.96%, late 0; v2 seed 4 Time limit, gap 8.32%, late 0. The v2 rows ran with one other probe, so wall and node counts are not comparable to the next row.
- v2 seed 3, 1,800 s, alone: Time limit, 99,739 nodes, incumbent 6,615.97, bound 5,986.18, gap 9.52%. The incumbent is flat from 42 s to about 1,198 s; the bound rises 5,501 to 5,986. The gap closes through the bound only (bound-limited). No claim about what stronger formulations would do.

### KPI naming
- `late_unit_days` counts NEW shortfall only. `backlog_unit_days` is the model's lateness term (cumulative shortfall charged every day). Compare a plan with the model objective through `backlog_unit_days`.
- End shortfall (units) and the lateness term (shortfall unit-days x weight) are different quantities and stay in separate columns.

### Pools 0.9 (CG cluster, n=2, 7 days, linking-M v1 rows)
- The v1 monolith lateness overstates the physical minimum (pool plus plant-minutes LP bound) by 0%, 0.2%, 14.5%, 10.3%, 1.0%, 3.1% on the six late seeds (100003, 200006, 400012, 500015, 700021, 800024). The v1 label is kept; rows are not averaged.
- The linking-M v2 monolith lateness equals that bound to 1e-8 on all six. The 1e8-scale objectives measure how the model distributes shortfall that the pools make unavoidable; they are not a measure of plan quality.

### CG numerics and tolerances (2026-11-27, MEASURED; pre weight-fix, not a claim)
- Master LP tolerance: with the HiGHS default 1e-7 on the scaled master, the restricted master rose (up to +57.9 on 1e8-scale columns) and a Farley bound sat above a later master on 3 of 6 v2 seeds. With `MASTER_LP_TOL = 1e-10` (code 069dbd0) the same six seeds (pools 0.9/0.9, n=2, 7 days, caps-v2 pools, 900 s, 400 cap, concurrency 3, unseeded) show max master rise 2.9e-6, 2.4e-3, 1.1e-5, 4.6e-5, 1.9e-4, 2.3e-5 (seeds 100003, 200006, 400012, 500015, 700021, 800024). That is float rounding at the stated scale, not "zero". Farley above the same-iteration master: 0 iterations on all six. Five converged (certified, exact pricing at 1e-6 absolute); 200006 stalled with bound = master to 1e-12. The earlier six-seed rows (cgv2) are superseded: noise-affected, not results. Scope: these six seeds only.
- Pools identity: rows carry `pools_hash`. caps-v1 and caps-v2 pools of the same seed differ per entry (seed 400012: same totals, 35 entries differ), so a seed number is not an instance. A different hash is its own finding (`pools_differ_not_comparable`), never a comparison.
- Pricing tolerance option `CG_TOL_REL` (`tol_rel` in `column_generation`, default 0 = unchanged absolute tol 1e-6). With it the pricing tolerance is max(tol, tol_rel x |master|) in original cost units. Measured on one seed only: 200006 (cost 1.5e8) without it stalled at 247 it; with 1e-10 and with 1e-9 (identical) it converged in 148 it, same value to about 2e-14 relative (code eb04108, concurrency 2). Status then means "certified up to 0.015 absolute", NOT exact convergence (exact would need pricing with no absolute tolerance). It is an explicit per-run option, not a default. OPEN: needs more seeds of the same class that stall before it could become a default. 1e-9 vs 1e-10 giving identical results points to a scale gap, not a tuning question.

## Rows without a retained plan: reason per group (2026-11-27)

A row with no plan cannot be re-validated by the independent validator. Reason per group:

| Group | Plan retained | Reason | Status |
|---|---|---|---|
| rerun/, calib3 | no | `monolith_scaling.py` keeps only `plan_keys` and only for n<=4 (about line 695) | by design |
| CG rows | no | bounds-only result schema (LB, UB, status), no plan field | by design |
| opt/ (e.g. `mono-opt-0.9-s300009.json`, added in monolith-results 8c01d6e) | no | no plan field in the JSON. The script that wrote it was not found. Reason it keeps no plan: NOT ESTABLISHED | not established |
| rows from the 08:12 EET reboot | no | raw JSON lost in the reboot | lost |
| mono-plan/, mpv2/ (18 plans) | yes | saved on purpose by `mono_plan.py`; 0 validator problems, 0 guard findings (validated with `BRAIN_LINKING_M` set per row) | validated |

Scope of the opt/ check, so it can be repeated: `git grep -l "mono-opt\|mono_opt"` over the whole tree of all 152 remote branches (the only hits are the result and `.guard.json` files on `origin/monolith-results`, no script, none on main); `git log --all -S"mono-opt"` (only the results sync commit 8c01d6e); local `/tmp` and `/downloads` in the working sandbox. Not searched: the codespace filesystem outside its git worktrees, and any machine other than the sandbox and the codespace.
