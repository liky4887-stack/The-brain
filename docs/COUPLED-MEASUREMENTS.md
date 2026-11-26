# Phase D coupled-cluster scaling (MEASURED, 2026-11-25, workspace box)

Clusters of N plants (seeds 101..1601, n_lines=4, n_skus=12, 7-day horizon,
supplier pools at 0.75x uncoupled usage = binding). Full data: the RESULT
JSON is reproduced below; regenerate with `python3 benchmarks/coupled_scaling.py`.

| plants | primal wall s | primal status | dual wall s | dual rounds |
|---|---|---|---|---|
| 2 | 3.613 | optimal | 4.518 | 20 |
| 4 | 10.003 | optimal | 13.855 | 20 |
| 8 | 62.865 | optimal | 24.93 | 20 |
| 16 | 240.084 | TIME LIMIT | 61.364 | 20 |

Findings (all measured):
- The ONE coupled MIP (HiGHS, 240 s limit) solves 2/4/8 plants to
  optimality (3.6/10.0/62.9 s) but hits the time limit at 16 plants:
  monolithic coupling stops scaling there on this class of instance.
- The decomposition (dual side) scales linearly with plants (4.5 ->
  61.4 s) because rounds x per-plant solves dominate; this is why the
  master-worker architecture is the path to larger coupled sizes.
- The repair-heuristic UB from the dual side is loose (heavy
  lateness after cuts); the Dantzig-Wolfe integer restricted master
  (coupled_dw.py) is the tighter UB path - measured separately in
  benchmarks/coupled_cg_scaling.py.

## Column-generation (master-worker) scaling - MEASURED same day

Same clusters/seeds; regenerate with `python3 benchmarks/coupled_cg_scaling.py`.

| plants | CG wall s | iters | converged | CG LB | IM wall s | IM UB | proven gap |
|---|---|---|---|---|---|---|---|
| 2 | 6.9 | 28 | yes | 60,940,576 | 0.0 | 246,925,353 | 75.3% |
| 4 | 23.3 | 33 | yes | 118,762,678 | 0.4 | 185,060,220 | 35.8% |
| 8 | 52.7 | 26 | yes | 231,949,488 | 2.3 | 251,472,976 | 7.8% |
| 16 | 59.9 | 17 | yes | 457,113,182 | 240.0 (limit) | 470,224,889 | **2.79%** |

Findings (all measured, LB and UB computed independently):
1. The CG master LP bound is TIGHT: within 0.0004% of the monolithic
   optimum at 2/4/8 plants (60,940,576 vs 60,940,849; 118,762,678 vs
   118,763,029; 231,949,488 vs 231,949,665). The convexification bound
   on this instance class is essentially exact.

CERTIFICATION (re-measured 2026-11-26 after an outside review):
a DW master LP value is a certified bound ONLY when the final pricing
round solved every subproblem to proven optimality - a time-limited
incumbent can fake "no negative reduced cost". coupled_dw.py now
checks this explicitly: DWResult.bound_certified is True only under
exact final-round pricing; inexact rounds no longer contribute Farley
bounds, and a run that cannot certify says so instead of reporting a
bound. Re-run with the certificate: ALL FOUR sizes (2/4/8/16)
converged with certified exact pricing and bit-identical LBs
(60,940,575.55 / 118,762,677.7 / 231,949,488.2 / 457,113,182.24), so
the tightness claim above stands, now with a certificate. (IM at 16
plants unchanged code path; the 240 s-limited UB 470,224,889 is
carried over from the run above, labeled as such.)
2. At 16 plants the monolithic MIP hit the 240 s limit (incumbent
   457,113,347, not proven optimal) while CG converged in 59.9 s with
   LB 457,113,182 - the decomposition scales where the monolith fails,
   exactly as designed.
3. The WEAK side is the UB: the integer restricted master only sees
   generated columns (UB 2.79% over LB at 16 plants, far worse at 2-8
   where few columns exist). Next lever: branch-and-price-lite
   (restricted master re-solved after adding repair-generated columns)
   or repair of the fractional master solution.
4. Gap narrows with cluster size (75% -> 36% -> 7.8% -> 2.79%) as the
   column pool per plant grows: more plants = more smoothing.
5. Sequential wall = iters x sum of plant solves (measured). Parallel
   fabric wall = iters x slowest plant (EXTRAPOLATED, dispatch
   overhead excluded) - recorded per run in the RESULT JSON.

## Convergence work (2026-11-26, n=2, days=7, supplier 0.75x + labor 0.8x binding)

All measured on the same instance; monolith optimum 321,859,494.66
(HiGHS, OPTIMAL, ~3s); uncoupled reference sum 4,457,322.67 (labeled
throughput reference, not a coupled bound). Costs are minimized; LB <=
optimum <= UB.

| config | iters | converged | certified LB | best plan (UB) | CG wall |
|---|---|---|---|---|---|
| baseline (no seed, no stab) | 60 | no | 258,263,743.67 | 2,594,680,000 | 57.9s |
| monolith-seeded | 60 | no | 251,249,173.92 | 321,859,494.66 | 77.0s |
| seeded + Wentges a=0.3, exact 1/5 | 60 | no | 4,457,322.67 | 321,859,494.66 | 70.2s |
| seeded, 90 iters | 90 | no | 300,791,511.58 | 321,859,494.66 | 106.6s |

Findings (measured, this instance only):
- Warm start from the monolith plan makes the integer master's best
  plan EQUAL the monolith optimum from iteration 0 (UB 321,859,494.66,
  validated clean). Plan quality is solved when a monolith seed is
  available; at 60 iters the certified LB slightly worsens (251.2M vs
  258.3M) because the seed shifts the master dual path.
- Wentges dual smoothing as implemented (alpha 0.3, exact pricing 1
  round in 5) HURTS certification: only 12 exact rounds, and none
  beat the uncoupled reference LB (4,457,322.67). Smoothed rounds are
  correctly excluded from the Farley certificate. Not adopted as a
  default; knob retained (stab_alpha, exact_every).
- Raising the iteration cap 60 -> 90 improves the certified LB
  monotonically: 251.2M -> 300.8M (gap vs optimum 21.9% -> 6.5%).
  Convergence is iteration-limited here, not pricing-limited; the
  bound keeps tightening with iterations.
- Lagrangian relaxation (coupled_dual, subgradient, 40 rounds,
  31.6s): best LB 4,457,322.67 = the round-0 uncoupled bound, never
  improved. Measured: the bounded geometric step (no primal UB yet)
  does not attain the CG bound on this instance. CG's Farley bound is
  far stronger; LR stays as the alongside reference, never mixed into
  the CG certificate.

## Review-3 fixes, re-measured (2026-11-26, same n=2 instance)

Two real bugs found and fixed (outside review #3 was right to push):

1. Wentges center update used the MAXIMIZATION improvement test on a
   MINIMIZATION master (obj > best instead of obj < best), so the
   stability center never moved after iteration 0. Combined with only
   12 exact rounds in 60, the certificate collapsed to the round-0
   Farley value. That value exactly equals the uncoupled reference
   sum (4,457,322.67) by arithmetic identity: with one seed column per
   plant the linking rows are slack (u=0) and
   obj + sum(min(0, rc_p)) telescopes to sum of uncoupled costs.
   Fixed test: center moves when the master objective decreases.
2. Lagrangian subgradient step was scale-blind (eta/(k+1) with
   objective ~1e8 and usages ~1e5): multipliers jumped to their cap in
   one step and never recovered, so the LB never moved off the round-0
   uncoupled bound. Fixed to a self-scaled Polyak-style step
   eta*|LB|/||g||^2 when no primal UB exists yet. Measured after fix:
   LB 9,346,048.60 after 40 rounds (2.1x the uncoupled bound, still
   far below CG's Farley bound - subgradient attainment is slow, as
   theory predicts; the asymptotic bound is the same).

Re-measured with fixes (heuristic/uncoupled seed ONLY - never the
monolith - per the crossover protocol):

| config | iters | wall | certified LB | best plan (UB) | gap LB-opt |
|---|---|---|---|---|---|
| fixed Wentges a=0.3, exact 1/5, 300-iter cap, 100s wall guard | 112 | 104.3s | 309,677,407.77 | 2,594,680,000 | 3.8% |

- Stabilization now helps: 3.8% bound gap in 104s vs 6.5% at 90 iters
  unstabilized in 106.6s. Adopted as the default for coupled runs
  (alpha 0.3, exact 1/5) with the wall guard.
- Heuristic-seeded plan quality: the end-of-run restricted integer
  master still returns 2,594,680,000 (~8.06x optimum) even with the
  112-iteration pool. Measured: thin per-plant column sets give the
  integer master little to combine; improving the primal side (more
  columns per iteration, integer master re-run cadence) is open work.
- Misprice fallback (already in): a smoothed round that finds no
  column forces an exact re-price before any convergence decision.
- Per-iteration times are now logged (DWResult.iter_times); mean
  iteration ~0.93s at n=2, so iteration caps of 300-500 are feasible
  under a wall guard.

## Review-4 LR attainment study (2026-11-26, same n=2 instance)

Both methods relax exactly the same linking constraints (shared
supplier (material, day) caps + shared labor day caps) and solve the
same per-plant bucket subproblems (solve_buckets with linear price
terms) - verified by reading coupled_dual and the coupled_dw pricing
worker; the asymptotic DW bound is identical. The difference is
attainment, measured with three subgradient step rules (40 rounds
each, same subproblem time limits):

| step rule | best LB after 40 rounds |
|---|---|
| old scale-blind eta/(k+1) | 4,457,322.67 (stuck at round-0) |
| self-scaled eta*|LB|/||g||^2 | 9,346,048.60 |
| Polyak with loose UB target 2,594,680,000 | 4,457,322.67 (overshoots) |
| Polyak with ORACLE UB target 321,859,494.66 | 123,457,697.93 |

CG Farley bound on the same instance: 309,677,407.77 (112 iterations).

Conclusion (measured): LR attainment is limited by UB-target quality
and iteration count, not by a formulation difference. 40 subgradient
rounds do not attain the CG bound even with the oracle target. CG
with exact pricing is the certified-bound workhorse; LR remains an
alongside cross-check. LR is NOT described as a weaker method
anywhere in the docs - only its measured attainment is reported.

Primal side (review 4): periodic restricted integer master added
(column_generation im_every parameter, best UB tracked in ub_series);
harness knob CMP_IM_EVERY. Allocate-then-solve-exactly and diving are
designed but not yet implemented - next work item, measured before
any claim.

## Review-5 primal side: allocate-then-solve-exactly (2026-11-26)

allocate_solve: per-plant shares of every shared pool from the master
LP convex combination become HARD limits (new mat_cap/lab_cap rows in
build_bucket_mip), each plant re-solves alone exactly, union is a
feasible coupled plan and a valid UB (shares sum <= caps in the
master). Runs on exact rounds when the master uses no artificial
columns, on an alloc_every cadence. integer_master no longer
displaces a better UB (measured bug: it overwrote 399.9M with
2.59e9). Time to first plan is recorded (first_ub_s).

Measured (heuristic/uncoupled seed ONLY, stabilization a=0.3,
alloc_every=5, im_every=25, wall guard ~90s local; bound and plan
numbers reported separately per the protocol - allocate rounds steal
iterations from the bound, so a single run trades one for the other):

| n | monolith optimum (wall) | best plan (UB) | plan x optimum | first plan at | certified LB (iters) |
|---|---|---|---|---|---|
| 2 | 321,859,494.66 (3.1s) | 345,895,669.61 | 1.075x | 13.0s | 212,024,538.28 (56 it, 34.1% gap) |
| 4 | 739,426,055.28 (7.1s) | 885,851,042.33 | 1.198x | 17.3s | 62,122,488.93 (36 it, 91.6% gap) |

- n=2 plan goal (<1.1x) MET: 1.075x, improving steadily with
  iterations (ub_series monotone 399.9M -> 345.9M).
- n=4 at 1.198x with only 36 iterations: not yet at goal; needs the
  larger time limit (review 5: 600s) which local 120s bash calls
  cannot host - runs go to Actions runners.
- LB in these runs is iteration-starved (allocate competes for wall);
  bound-focused configs (alloc off) measured 309.68M at n=2 (3.8%).
  Crossover reports both configs per size, same limit, both methods.
- Diving (fix near-1 LP columns, re-solve): not yet implemented.

## Block A retro provenance (review-8 point 7, 2026-11-26)

Block A = step-6 run 45737026860 at SHA 53bf65c. The integer_master
UB-overwrite bug lived in coupled_dw.py; the ladder solve path
(benchmarks/gate2m/common.py) imports only rolling.solve_rolling and
two_level - never coupled code - so block A's measured numbers are
unaffected. Its merge verified 2048/2048 plants present with 0
problems (completeness + de-duplication at merge time). The coupled
UB figures reported while the bug existed (n=2 UB 2,594,680,000)
were CONSERVATIVE (a better UB could be displaced by a worse one,
never the reverse); certified bounds were untouched.


## 2026-11-26 crossover sweep, run 45842450508 (SHA 7142397): UB PLANS INVALID

Protocol: n = 2,4,8,16,32,64 plants, 5 replicas each, 7-day instances, 600 s limits for both methods, CG without monolith seed, integer master only (no allocate-then-solve), 40 CG iterations. All numbers MEASURED from the six artifacts.

**Headline: the distributed upper-bound plans in this run are NOT valid coupled plans.** The independent validator (validate_coupled_plan) reports shared supplier-pool cap violations in 30 of 30 replicas (3 to 49 violations each). In 27 of 30 replicas the reported UB is below the certified LB, which a feasible plan cannot be. The "plan_vs_monolith" ratios in the artifacts' per_size field (0.61 to 0.99) are therefore meaningless as plan quality and must not be quoted. Registered as known failure (see benchmarks/registry/known-failures.json, root cause OPEN). The harness now counts a UB only if its plan validates (invalid ones reported as invalid_ub_replicas).

What the run does support (monolith side and the certified bound):

| n | monolith status (5 reps) | monolith mip_gap mean/worst | CG certified LB vs monolith incumbent gap mean/worst | CG UB plans valid | CG UB violations (min-max) | first UB s (mean) |
|---|---|---|---|---|---|---|
| 2 | OPT,time-limit | 1.52e-02 / 7.59e-02 | 0.0189 / 0.0945 | 0/5 | 3-9 | 7 |
| 4 | OPT,time-limit | 1.33e-02 / 6.67e-02 | 0.0145 / 0.0717 | 0/5 | 4-16 | 16 |
| 8 | OPT,time-limit | 1.49e-02 / 7.43e-02 | 0.0169 / 0.0415 | 0/5 | 10-19 | 45 |
| 16 | OPT,time-limit | 3.17e-08 / 1.58e-07 | 0.0376 / 0.0879 | 0/5 | 18-29 | 69 |
| 32 | OPT,time-limit | 3.48e-09 / 1.74e-08 | 0.0642 / 0.1095 | 0/5 | 21-35 | 92 |
| 64 | OPT,time-limit | 6.39e-08 / 3.20e-07 | 0.2383 / 0.2891 | 0/5 | 28-49 | 215 |
certified-LB flags per size: {2: [True, False, False, False, True], 4: [False, False, False, False, False], 8: [False, False, False, False, False], 16: [False, False, False, False, False], 32: [False, False, False, False, False], 64: [False, False, False, False, False]}

The monolith plans all validate (0 problems in 30/30). The certified-LB gap column compares the monolith incumbent with the CG Farley bound; the bound was marked certified in only 2 of 30 replicas (n=2), so most of that column is "best certified Farley value at iteration 40, not converged". At n=64 the CG bound is 24% below the monolith incumbent after 40 iterations.
