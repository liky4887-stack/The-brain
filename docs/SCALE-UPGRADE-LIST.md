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

### 1. Lot-sizing cuts via an explicit state reformulation (REVISED)
Source: Wolsey ch.9 (cover and flow-cover families, separation;
skill: docs/skills/wolsey-integer-programming.md), sec. 14.4
multi-item lot-sizing (The-brain's own problem family).
Revision (honest finding, 2026-11-25, from reading build_bucket_mip):
the bucket model's coverage is SOFT - cumulative production rows with
lateness (lo) and earliness (e) slacks, no explicit inventory/backlog
state variables. With backlogging, a period's production can serve
ANY demand day (early or late), so the classic (l,S)/flow-cover
families (which assume demand intervals) have no bite as-is. The
correct first step is a reformulation: explicit inventory/backlog
balance s_t - s_{t-1} - b_t + b_{t-1} = X_t - dem_t (feasible set
provably unchanged, slacks eliminated), which then admits the
backlogging-aware (l,S) family. Both steps carry the repo-standard
proof: brute-force enumeration of tiny instances, every generated cut
checked against every feasible point; LP bound never weaker; fabric
wall measured before/after.
Effect (ESTIMATED, now with lower confidence): bucket level faster at
fixed size; keep only if the measured LP bound improves on a real
window. Cost: medium-high (reformulation + separation + proofs).
Fabric fit: pure CPU. Keeps rank 1 on expected value, with the
applicability caveat recorded.

### 2. Disaggregated per-line setup linking in the bucket MILP
Source: Williams ch.3 disaggregation rule + Wolsey ch.14.3
formulation-strength method (docs/skills/williams-model-building.md).
Mechanism: replace sum_l x_stl <= M_st y_st by per-line
x_stl <= cap_sl z_stl. Stronger relaxation, but more binaries.
Honest caveat: variable count GROWS; on a 16 GB runner the net effect
is uncertain - implement behind a flag, measure both ways, keep the
winner. That is why this is not rank 1.

### 3. Day-grain propagation to prune bucket-MILP variables (REVISED)
Source: Handbook of CP ch.22.3 (docs/skills/handbook-constraint-
programming.md); propagators already implemented and brute-force
tested: propagation/edge_finding.py, timetable.py, energy.py.
Revision (honest finding, 2026-11-25): the ORIGINAL framing - tighten
per-activity time windows inside solve_day_exact - does not map onto
the day model. Chunks there carry no individual time windows; the
model is chunk->line assignment plus a state circuit, and its UNKNOWNs
were runner contention, already fixed (seq-workers=1 + escalation).
Revised mechanism: apply timetable/energy reasoning at DAY grain -
activity = chunk, window = [earliest start day, due day] from demand
due dates, duration = production minutes (+ a sound changeover lower
bound) - to tighten each chunk's day window, then DROP (sku, day,
line) triples outside tightened windows from the bucket MILP. Fewer
variables in the LARGEST model in the stack. Soundness rule: only a
cumulative (all-lines) relaxation may prune; per-line arguments that
ignore load sharing across lines are unsound and are not used.
Effect (ESTIMATED): 10-30% fewer bucket binaries on due-date-tight
plants. Cost: medium. The day-level UNKNOWN class is closed by the
contention fix, not by this item.

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

Target note (user voice 2:46 PM): ~30M variables is ladder
step 3 (448 plants / 56 shards, ~31.0M EXTRAPOLATED from the
measured 69.2K mean vars/plant). The ladder reaches it after
S1/S2 confirm the fabric behaves; the upgrades above are what
make that scale faster and more accurate.

## Execution order

4 first (done: day-model symmetry breaking), then
1, then 3 in its revised day-grain form (the big formulation win), re-measure the fabric ceiling after each
landing, then 2 behind a flag, then 5/6. Each landing: full suite,
golden optima unchanged, LP bound not weaker, fabric benchmark
measured, verification-harness claim filed.
