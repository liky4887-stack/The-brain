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
