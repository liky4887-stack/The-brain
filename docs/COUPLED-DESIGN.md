# Phase D: one COUPLED multi-plant problem with a proven global gap

Status: DESIGN (not yet implemented). This document pins the model, the
method, the fabric mapping, and exactly what will be claimed proven.

## Why

Every result so far is a SUM OF INDEPENDENT PROBLEMS: plants share
nothing, so 192 plants = 192 small solves. The user requirement: one
linked model where plants interact, solved by a real OR decomposition
with a PROVEN bound/gap on the whole coupled instance.

## The coupling (v1, real linking constraints)

Plants no longer live alone. Three shared pools link them, all at the
bucket (week/day-quantity) level, which is where production quantities
per day are decided (the day level only sequences inside a day and
cannot move quantity across days, so day-level decisions cannot violate
a per-day shared pool - proof obligation P4 below):

1. SHARED SUPPLIER CAPACITY. Raw material r has a per-day supply cap
   S[r,d] across ALL plants: sum over plants p, skus s of
   recipe[s,r] * prod[p,s,d] <= S[r,d].
2. SHARED LABOR/TRANSPORT POOL. Pool capacity L[d] minutes per day
   across all plants: sum over p,s of prod[p,s,d]/rate[p,s] <= L[d]
   (production minutes draw from one pool; changeovers stay per-plant).
3. (v2, stated not built) SHARED DEMAND ALLOCATION: each demand may be
   served by any eligible plant, each demand served once - assignment
   couples plants through set-partitioning constraints. v1 keeps the
   current static plant->demand assignment; this is a documented
   modeling limitation, not hidden.

So v1 is one model: minimize total cost over ALL plants subject to
per-plant constraints (as now) PLUS the two families of linking
constraints above. Plants are independent only after the linking
constraints are relaxed - which is exactly what the decomposition does.

## The method: Lagrangian relaxation of the linking constraints

Canonical pattern for capacitated multi-item lot sizing, taken from:
- Thizy & Van Wassenhove, "Lagrangean Relaxation for the Multi-Item
  Capacitated Lot-Sizing Problem: A Heuristic Implementation",
  IIE Transactions 17(4), 1985 (method as described in [MDPI] below).
- [MDPI] Chen & Wang, "Lagrange Relaxation for the Capacitated
  Multi-Item Lot-Sizing Problem", Applied Sciences 14(15):6517, 2024,
  https://www.mdpi.com/2076-3417/14/15/6517 (read in full, 2026-11-25):
  relax the capacity constraints with multipliers u >= 0; the relaxed
  problem decomposes into independent single-item problems; ANY u >= 0
  gives a valid LOWER bound; maximize the bound by subgradient ascent
  with the Polyak step s_k = eta_k (UB - z(u_k)) / ||g_k||^2, eta
  halved on stall; feasible upper bounds from a transportation-problem
  repair of the relaxed solution.
- Wolsey, Integer Programming, ch.10-12 (Lagrangian duality, column
  generation, Benders): STRUCTURE-READ ONLY in our library - used as a
  pointer, not cited for details (project rule).

Applied to us: relax the two linking families with multipliers
uS[r,d] >= 0 and uL[d] >= 0. The dual problem decomposes BY PLANT:
each plant solves its current two-level rolling plan with extra LINEAR
penalty terms in the bucket MIP objective:
    + sum_{r,d} uS[r,d] * recipe[s,r] * prod[p,s,d]
    + sum_d     uL[d]   * prod[p,s,d]/rate[p,s]
Linear penalties slot into the existing level-1 MIP as cost terms -
no structural change to the day level at all.

PROVEN: for any multipliers >= 0, sum over plants of the penalized
subproblem optima minus sum u*Cap is a valid global LOWER BOUND on the
coupled optimum (weak duality; the proof is one line of algebra and
will be re-verified numerically per run, obligation P2).

PRIMAL: the best per-plant plans repaired to satisfy the linking
constraints (capacity-feasible allocation of the scarce pools, pushing
overflow production earlier/later within the horizon at true inventory
/backlog cost) give a FEASIBLE coupled plan = valid UPPER bound.

GAP: (UB - LB) / |LB| reported with both bounds and the multiplier
history. This is a proven gap on the whole coupled problem, not a
per-plant average.

## Why not the alternatives (recorded decision)

- ADMM/consensus: no proven bound on the coupled MIP - rejected for
  the "proven gap" requirement (fine heuristic, wrong guarantee).
- Dantzig-Wolfe / column generation (Lasdon & Terjung pattern, cited
  in [MDPI]): also gives a proven bound, but needs a restricted master
  simplex + per-plant pricing MIPs + integrality restoration
  (branch-and-price) - much more machinery for the same guarantee.
  Recorded as the upgrade path if the Lagrangian gap stalls wide.
- Benders: fits when linking VARIABLES are few and continuous; ours are
  per-day capacities (many) - worse fit than dualizing them.

## Fabric mapping (free tier, runners cannot talk)

Subgradient iteration k needs all plant subproblem values at u_k before
computing u_{k+1}: rounds are SEQUENTIAL, plants within a round are
PARALLEL. One Actions run per round is far too slow (10+ min overhead
per round), so:

- COUPLED CLUSTER = the unit of coupling: 8-16 plants sharing pools,
  one runner job, plants in-process parallel (measured: 4 workers x
  seq_workers=1), ~20-50 subgradient rounds inside the 60-min job
  budget (per-round cost ~= one penalized bucket MIP per plant, the
  day level runs ONCE for the final primal, not per round).
- The 192-plant instance partitions into clusters; the COUPLED claim
  covers each cluster honestly ("one coupled problem of N plants with
  proven gap g"), never "192 plants coupled".
- The existing shard/wave/guard/merge machinery is reused as-is; the
  shard payload gains multipliers history, LB/UB series, gap.

## Proof and honesty obligations (the checklist every run must pass)

P1. The linking constraints are stated above and enforced EXACTLY in
    the primal feasible plan (validated numerically, all days).
P2. Weak duality re-verified per run: reported LB <= reported UB and
    LB <= any known feasible objective, to tolerance.
P3. Global material balance: raw material consumed = supplier pool
    usage, per day, summed over plants, validated independently of the
    solver (the existing independent-validator pattern).
P4. Day level cannot violate per-day pools: quantities per day are
    fixed by the bucket level and day sequencing only reorders within
    the day (argued above; asserted in code).
P5. Labels: LB = PROVEN lower bound (subgradient history recorded);
    UB = feasible plan (validation recorded); gap = derived. Cluster
    size, rounds, and wall time MEASURED. Literature gap ranges
    (~1-3% on classic CLSP instances, per [MDPI] and Thizy & VW) are
    CONTEXT, never claimed as ours.
P6. Deterministic: fixed seeds, pinned versions, multiplier history in
    the RESULT.

## What "largest coupled size truly solved to a stated gap" will mean

The headline number is (plants per cluster x clusters) with the WORST
cluster gap stated, e.g. "16 plants coupled, gap <= x% proven, wall y s
measured on the free fabric". Scaling out clusters is throughput, not
coupling depth; both numbers are reported separately.

## The makkook.ai reference (user-requested, read 2026-11-25 as
public untrusted content; patterns only, nothing run or signed up)

The user named "مكوك" = makkook.ai (Cairo/Manama industrial decision
vendor), NOT makko.ai (an unrelated AI 2D game studio; disregarded).

What makkook.ai publicly claims:
- DIOS platform: encode the whole operation (objectives, physical
  constraints, labor, demand, cost) into ONE structured decision
  model; compute "the mathematically provable best answer"; execute
  and re-optimize when reality changes; "decisions compose into
  systems" (forecast -> planning -> scheduling -> workforce ->
  logistics, continuously).
- Their glass-manufacturing case (the closest public detail): multiple
  SHARED furnaces and downstream lines; four engines under one
  Planning Cockpit - (1) Demand & Capacity Scenario Engine,
  (2) Multi-Horizon Production Planning Optimizer, (3) Changeover-
  Aware Sequencing Engine, (4) Execution-Aware Replanning Engine;
  frozen windows for plan stability; full audit/version history.
  Stated stack: "Constraint Optimization (MILP/CP-SAT),
  Multi-Horizon Planning, Execution-Aware Replanning".

What it does NOT show: any method detail, any bound/gap, any benchmark
numbers (their "Published Papers" counter reads 0; the "6.5 million
decisions" article 404s). Claims like "billions of permutations in
milliseconds" and "provable best answer" are marketing; our honesty
bar (proven gap, measured wall) is strictly higher and stays.

What we adopt, in our own way (their strategy, our guarantees):
1. SHARED ASSETS as the coupling: their shared furnaces/lines are our
   shared supplier capacity and shared labor/transport pool - the
   linking constraints above. This matches their operational strategy
   of planning across shared assets in one model.
2. SPECIALIZED ENGINES UNDER ONE COORDINATOR: their four engines map
   onto ours - scenario/generator, bucket-level multi-horizon
   optimizer, changeover-aware day sequencing, rolling replan with
   frozen windows (freeze_days already = 3). The new piece Phase D
   adds is exactly their "single cockpit": one coordinator (Lagrangian
   multipliers + primal repair) that keeps every engine's plan
   consistent with the shared assets, plus our independent validator
   (their "audit history", ours re-verifies numerically).
3. CLOSED LOOP: execution signals feed replanning - already our
   rolling-window design; the coupled cluster inherits it.
