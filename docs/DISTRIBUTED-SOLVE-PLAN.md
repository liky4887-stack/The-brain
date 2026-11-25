# Partitioning the 2M-variable workload across free CI runners

Status: REVISED PLAN v1 (2026-11-25). Research grounded in the sources
listed at the end and in measurements taken on this repo's own code.
Owner delegated implementation after the plan (voice note 2026-11-25).

## 1. What the workload actually is (measured)

The gate instance: 96 independent Makkook-scale plants (17 lines x
4001 SKUs, seeds 1000+i), each planned over 2 rolling 7-day windows
(freeze 3). Per plant-window, the level-1 bucket MILP measures
~25k-43k vars / ~9k-15k rows / ~3k-5k binaries (60,725 vars / 21,140
rows for a full 7-day demand window); aggregate across 192 windows:
~2.3M constraints / ~6.6M variables.

Measured on this 2-core box (11 plants, seeds 1000-1002, 1008-1015):
- per-plant wall 100-130 s (2 windows), bucket solves HiGHS-OPTIMAL
  (gap 0.0) in natural time - the wall is sequencing-dominated, not
  budget-capped;
- peak RSS ~650 MB per plant solve;
- 0 validation problems; every window optimal.

Runner-fabric measurements: see section 6 (updated from the Actions
runs' RESULT.json).

Structural finding that shapes everything below: within one plant the
lines share SKUs across families, so decompose.partition_plants PROVES
a Makkook plant is one coupled cell - a plant's window MILP cannot be
split exactly by SKU or line. Between plants the split is exact.
Time couples only through inventory carryover between windows.

## 2. The fabric (free tier, official limits)

- ubuntu-latest on public repos: 4 vCPU / 16 GB RAM / 14 GB SSD, free
  and unlimited for public repos (docs.github.com runners reference).
- 6 h per job; 256 jobs max per matrix; free-plan concurrency ~20
  jobs (docs.github.com Actions limits).
- Jobs are stateless VMs: NO job-to-job network. Coordination channels
  are artifacts, the dependency cache, and git. One coordination round
  (fan-out wave -> artifact -> merge job) costs minutes: pip install
  ~1-2 min uncached (~20-40 s cached), queue/scheduling ~10-60 s.
- No SLA on queue times; runner CPU speed varies run to run.
- HiGHS parallelism is memory-bound: threads beyond ~8 rarely help,
  and the MIP solver's parallel path is recent (HiGHS parallel docs).
  On 4 vCPUs a single solve gains little from threads; parallelism
  must come from decomposition, not from a fatter single solve.
- scipy.optimize.milp exposes HiGHS; ortools CP-SAT is NOT
  deterministic under num_workers > 1. Reproducibility requires
  threads=1/num_workers=1, or accepting solution diversity (every
  accepted plan is independently validated anyway, and objectives are
  recomputed from assignments - the honesty rules already cover this).

Memory bound for a monolith: the aggregate 2.3M-row model's sparse
matrix alone is ~12 GB before HiGHS presolve (extrapolated from
measured nnz per plant-window) - at the edge of one 16 GB runner.
The monolith is infeasible on the fabric AND unnecessary (below).

## 3. Decomposition options for one coupled model

Axes to split a single plant-window MILP (the case where one cell
outgrows one runner), and what each costs on THIS fabric:

A. Independent-cell sharding (STATUS: DONE, benchmarks/gate2m/).
   Exact (proven partition), zero communication during solves, one
   merge round. This carries the whole 96-plant gate.

B. Parallel LNS / seed shards (QUALITY lever, zero coupling).
   N runners run lns_improve with different destroy regions/seeds on
   the same incumbent; merge takes the recomputed best. Fits the
   fabric perfectly (one round). Improves objective, not feasibility
   or capacity.

C. Capacity-share partitioning (heuristic split of a coupled plant).
   Assign each line-day's minutes to SKU families a priori, solve
   families independently, repair overflows with LNS. Fast (one
   round), but the split is a guess: expect a measured optimality gap
   and occasional infeasibility. Honest role: fallback when a cell is
   too big AND iteration budget is tiny.

D. Logic-based Benders (master-worker over rounds).
   Master: bucket MILP (production quantities, setups). Subproblems:
   per-line-day CP sequencing (already solve_day_exact); infeasible
   subproblem -> combinatorial no-good cut back to the master.
   Literature: LBBD for parallel-machine / two-stage scheduling
   (IJOC 10.1287/ijoc.2021.1113; Annals OR 10.1007/s10479-026-07087-z).
   Rounds needed: tens. On this fabric each round is a wave (~3-5
   min cached) => ~1.5-4 h per coupled plant-window - inside the 6 h
   job limit with pip caching. The master fits any runner (bucket
   MILP is the 60k-var model we already solve). This is the ONLY
   exact method whose round count fits artifact latency.

E. Lagrangian relaxation of line-day capacity (Thizy & Van
   Wassenhove; Trigeiro et al.; MDPI 14(15):6517, 2024).
   Dualize capacity rows => per-SKU uncapacitated lot-sizing
   subproblems solvable by Wagner-Whitin DP in O(T^2); multipliers by
   subgradient. Massively parallel subproblems (thousands of SKUs,
   each milliseconds) BUT needs hundreds of multiplier updates =>
   hundreds of fabric rounds => impractical as a distributed loop on
   Actions. Viable single-runner (subproblems are cheap), where it
   gives bounds rather than our already-optimal incumbents.
   Verdict: research-grade here; not recommended on this fabric.

F. Dantzig-Wolfe / branch-and-price (OR 10.1287/opre.1070.0404).
   Per-line (or per-SKU) column subproblems, RMP with linking rows.
   Fewer rounds than subgradient (tens), small LP master - feasible
   on the fabric in principle, but implementing branch-and-price
   (branching compatible with column generation) is weeks of work and
   the payoff over D is unproven for our structure. Defer.

G. ADMM / consensus MIP (arxiv 1905.03309, 2205.00356).
   No general convergence guarantee for mixed-integer consensus;
   behaves as a heuristic with many rounds. Not recommended.

H. Temporal speculation (parareal-style window overlap).
   Windows are sequential through inventory carryover; solve window
   w+1 in parallel with ESTIMATED carryover, then correct. Expect 1-2
   correction rounds when carryover is light (measured: end backlog
   ~0, so carry is one-sided inventory). Cheap to try, bounded gain
   (window count is small).

## 4. Recommendation

1. Keep A as the gate path (exact, proven, already running).
2. Build B next (parallel LNS shards): small code, immediate quality
   lever, exercises the artifact-coordination pattern D needs.
3. Build C (capacity-share + LNS repair) as the pragmatic splitter for
   an over-sized cell, with its gap honestly measured per instance.
4. Build D (LBBD) as the exact splitter: driver-in-merge-job master,
   CP subproblem shards, cuts as artifacts, convergence + cut-count
   telemetry per round. Bound rounds (e.g. 40) and report best
   incumbent + bound honestly when the bound is unproven.
5. Skip E/F/G on this fabric (round latency); note E as a
   single-runner bound provider if ever needed.
6. Optional H after B: two-round speculative windows.

## 5. Validation plan (applies to every phase)

- Every shard uploads assignments + model-size provenance (vars, rows,
  binaries from the built MIP); never a solver-claimed objective
  alone.
- The merge job re-runs the independent validator from artifacts
  alone (pattern proven in benchmarks/gate2m, including a tamper
  test): capacity per line-day with matrix changeovers, per-SKU stock
  walk, KPIs recomputed.
- Objectives recomputed from returned assignments, never read from
  solver internals (standing rule).
- Determinism: seed everything; record threads/num_workers per job;
  identical inputs must reproduce identical aggregates, and any
  nondeterminism (CP-SAT workers) must leave validation unchanged.
- Every RESULT.json separates MEASURED from EXTRAPOLATED, with the
  extrapolation method written next to the number.
- Suite green (306 tests + 3 skipped) before every merge; no force
  pushes; merge --no-ff.

## 6. Runner-fabric measurements (filled from Actions runs)

- Run #1 (12:51): 11/12 shards OK; shard 1 exited 1 opaquely; all 8
  of its plants later reproduced CLEAN locally (seeds 1008-1015).
- Run #2 (13:35): 12/12 shards OK; merge failed after ~40 s because
  the publish step only ran on success; evidence was locked in
  signed-in logs. Fixed: RESULT.json is written and published on
  every outcome.
- Run #3 (13:56, RESULT.json on gate2m-results): all 96 plants solved
  and revalidated from artifacts. MEASURED: aggregate 6,639,962 vars /
  2,321,508 rows / 766,220 binaries over 192 windows (exceeds the
  2M/1.4M gate on both axes); 31,216 assignments validated; per-plant
  solve min/mean/max 132.9/160.4/189.7 s; shard walls 316.8-364.2 s;
  distributed wall 381.5 s; merge+validate 17.3 s; backlog ~0.
  EXTRAPOLATED single-32-core box: 586 s (< 1800 s budget) - labelled
  method in RESULT.json. Verdict OPEN for exactly 2 problems: plants
  14 and 82 each had ONE day whose CP-SAT sequencing returned UNKNOWN
  under 4-way process contention (default num_workers thrashing 4
  vCPUs against a 10 s limit). Both plants solve CLEAN on a
  single-threaded box, so the model is not at fault - the limit under
  contention is. Fix (this commit): UNKNOWN escalates the day limit
  x4 up to 120 s (INFEASIBLE, a proof, is never retried; the final
  message now says 'undecided, not disproven' instead of claiming the
  mix is unrealizable), and seq_num_workers is plumbed through
  rolling/decomposed so the fabric runs --seq-workers 1 (4 processes x
  1 worker = 4 cleanly used cores). Tests: escalation reports
  undecided; INFEASIBLE is not retried.

## 7. Implementation sequence (tests + merge per step)

1. benchmarks/gate2m RESULT landed + section 6 filled (this doc).
2. Phase B: lns_shards.py (seed/region-sharded lns_improve +
   merge-best), tests on the 6x400 gate instance, merge.
3. Phase C: capacity_split.py + repair via lns, gap measured on
   Makkook plant-windows vs the monolithic bucket optimum, merge.
4. Phase D: lbbd/ (master driver, cut serialization, subproblem
   shards, round telemetry), small-instance convergence tests vs
   solve_window optimum, then a fabric round-trip test, merge.
5. Optional Phase H.

## Sources

- GitHub Actions limits + runner specs (official):
  docs.github.com/en/actions/reference/limits,
  docs.github.com/en/actions/reference/runners/github-hosted-runners
- HiGHS parallelism (official): ergo-code.github.io/HiGHS/stable/parallel/
- Lagrangian relaxation for CLSP (per-SKU WW subproblems, subgradient):
  Thizy & Van Wassenhove; Trigeiro et al. (Mgmt Sci 35(3):353);
  MDPI Applied Sciences 14(15):6517 (2024).
- Branch-and-price for lot-sizing: OR 10.1287/opre.1070.0404.
- Logic-based Benders for two-stage/parallel-machine scheduling:
  IJOC 10.1287/ijoc.2021.1113; Annals OR 10.1007/s10479-026-07087-z.
- Consensus/ADMM MIP (limits): arxiv 1905.03309, arxiv 2205.00356.
- Measured: /tmp/gate2m-log.jsonl, /tmp/gate4-capstone.json, and the
  Actions RESULT.json (section 6).
