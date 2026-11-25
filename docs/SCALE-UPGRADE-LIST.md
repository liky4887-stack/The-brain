# Scale upgrades beyond 6.6M variables - ranked, source-tied, honest

Assignment (2026-11-25, user voice): mine the books for mathematical
techniques that make the system stronger than the measured 6.6M-variable
aggregate (run #3: 6,639,962 vars / 2,321,508 rows over 96 plants,
MEASURED on the free fabric).

Scope assumption (stated because the user's instruction was loose):
the original 48 books are the engineering-craft base; their distilled
skills were not retained (their substance lives in the pulse app code),
so they set the code-quality bar here, not the math. The mathematical
techniques below come from the OR/optimization library, which IS
retained as distilled skills in docs/skills/ with tested code. If the
user meant something else by "master base", the ranking still holds -
it is sourced from the books we can actually cite.

Every expected effect below is ESTIMATED until measured on the fabric
benchmark; the verification harness (docs/COMPLETION-VERIFICATION.md)
gates each landing: goldens keep their optima, LP bounds never get
weaker, wall times measured, MEASURED vs ESTIMATED labels.

## The architecture these techniques must fit

Per plant, per rolling window (rolling/two_level.py):
- Level 1 `solve_buckets`: one MILP (HiGHS) over active SKU-day-line
  quantities + SKU-day setups. Tight per-SKU big-M already (Williams
  ch.3 rule applied: M = min(capacity x rate, total demand)). This is
  the LARGEST model in the stack (most of the ~60K vars / plant).
- Level 2 `solve_day_exact`: one CP-SAT per day: chunk-to-line
  assignment + circuit over setup states, exact changeover costing.
  Known weak spot under contention (the run #3 UNKNOWN class).
- Distribution: plants are independent -> shard across runners
  (fabric, done). The techniques below raise what ONE plant-window can
  absorb, which multiplies through every shard.

## Ranked list

### 1. Flow-cover and (l,S) valid inequalities in the bucket MILP
Source: Wolsey ch.9 (cover and flow-cover families, separation;
skill: docs/skills/wolsey-integer-programming.md), sec. 14.4
multi-item lot-sizing (The-brain's own problem family).
Mechanism: add separated flow-cover inequalities on the
production-inventory linking of build_bucket_mip. Tighter LP
relaxation => fewer HiGHS branch nodes inside the same 60 s budget.
Effect (ESTIMATED): bucket level 1.3-2x faster at fixed size, or
~1.5x bigger window at fixed time; multiplies across all shards.
Cost: medium (separation is O(T^2) per SKU, already understood).
Fabric fit: pure CPU, no memory growth. Rank 1: best effect/cost.

### 2. Disaggregated per-line setup linking in the bucket MILP
Source: Williams ch.3 disaggregation rule + Wolsey ch.14.3
formulation-strength method (docs/skills/williams-model-building.md).
Mechanism: replace sum_l x_stl <= M_st y_st by per-line
x_stl <= cap_sl z_stl. Stronger relaxation, but more binaries.
Honest caveat: variable count GROWS; on a 16 GB runner the net effect
is uncertain - implement behind a flag, measure both ways, keep the
winner. That is why this is not rank 1.

### 3. Propagation-based domain reduction before CP-SAT
Source: Handbook of CP ch.22.3 (docs/skills/handbook-constraint-
programming.md); propagators already implemented and brute-force
tested: propagation/edge_finding.py, timetable.py, energy.py.
Mechanism: CP-SAT accepts no custom propagators, so run edge-finding /
timetable / energy reasoning as PREPROCESSING on each day model:
shrink chunk-line eligibility and day windows, then hand CP-SAT the
reduced domains. Directly attacks the measured runner-only UNKNOWN
class (day-4 under contention).
Effect (ESTIMATED): fewer UNKNOWN escalations, 10-30% faster day
solves. Cost: low-medium. Rank 3: cheap, kills a real failure class.

### 4. Symmetry breaking among identical lines
Source: Williams ch.6 (pattern in modeling/patterns.py, brute-force
verified). Mechanism: order interchangeable lines (same eligibility,
rate, setup matrix) in both levels. Cost: low. Effect (ESTIMATED):
prunes factorial duplication where plants have symmetric line groups;
zero where they do not. Measure per plant.

### 5. LBBD / Benders window decomposition
Source: Wolsey ch.10 Lagrangian duality; LBBD evidence already cited
in docs/DISTRIBUTED-SOLVE-PLAN.md (IJOC 10.1287/ijoc.2021.1113,
Annals OR 10.1007/s10479-026-07087-z).
Mechanism: master MILP assigns chunk->day->line, CP subproblems
sequence each day, no-good cuts iterate. Raises the window size a
single plant can absorb. Cost: high. Rank 5: do after 1-4 land.

### 6. Shifting bottleneck for the day model
Source: Pinedo sec. 5.4 (documented in skill, NOT implemented).
Mechanism: sequence line-by-line with re-optimization instead of one
monolithic day model. Cost: medium. Alternative to item 5 for the day
level; measure both if 5 disappoints.

### 7. Lagrangian coordination of shared resources
Source: Wolsey ch.10; MDPI Mathematics 14(15):6517 (Lagrangian CLSP,
cited in the distributed plan). Mechanism: dualize energy/staffing
coupling, per-line subproblems - enables finer-grain distribution
than per-plant sharding. Cost: high. Pairs with distributed Phase C.

### 8. Network-flow extraction of the material balance
Source: Ahuja/Magnanti/Orlin ch.9 (network/flows.py, tested).
Mechanism: IF the raw-material/inventory block is a pure network,
min-cost flow solves it exactly in polynomial time; otherwise it is a
strong relaxation. Honest: needs a structure check first; may yield
nothing if the block is not pure. Low rank for uncertainty.

### 9. Dantzig-Wolfe / column generation
Source: Wolsey ch.11 (structure-read only - implement only after a
deep read, per the honesty rule). Highest ceiling for symmetric lines,
highest cost. Deferred behind 1-5.

## Honest negatives (NOT pursued, with reasons)

- In-house Gomory cuts (ilp/cutting_planes.py), in-house simplex and
  IPM (lp/): educational oracles, validated as such. HiGHS and CP-SAT
  already ship mature cut engines and IPMs; substituting ours would be
  SLOWER. No capacity gain. Their role stays cross-validation.
- Injecting propagators into CP-SAT: impossible (closed solver);
  item 3 uses them as preprocessing only.
- The reverse-engineered agent repos the user linked: not opened as
  instructions, not installed; pattern vocabulary only (see
  docs/COMPLETION-VERIFICATION.md).

## Execution order

3 + 4 first (cheap, low risk, attack a measured failure class), then
1 (the big formulation win), re-measure the fabric ceiling after each
landing, then 2 behind a flag, then 5/6. Each landing: full suite,
golden optima unchanged, LP bound not weaker, fabric benchmark
measured, verification-harness claim filed.
