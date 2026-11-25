# Competitive notes: makkook.ai (public sources only)

Compiled 2026-11-25. Rules: public pages only; no sign-up, no contact,
nothing run of theirs. FACT = stated on a cited public page; INFERENCE
= our reading. Nothing here claims superiority without a measured
basis; that basis lives in benchmarks/, not in this file.

## Sources read

1. makkook.ai home, /dios/, /cases/multi-horizon-production-planning-
   for-high-complexity-glass-manufacturing/ (rendered pages).
2. Kleverz, "Makkook on Shark Tank Egypt: operations research vs AI",
   2026-11-20 (review of the Shark Tank Egypt S5 episode, with
   founder-attributed figures flagged as unverified by that outlet).
3. makkook.ai/sitemap.xml (their "6.5 million decisions in one hour of
   F&B production planning" article 404s; several sitemap URLs 404).

## How they work (publicly verifiable)

FACT: DIOS = "Decision Intelligence Operating System": encode the
whole operation (objectives, physical constraints, labor, demand,
cost) into ONE structured decision model; compute and execute the
decision; re-optimize when reality changes; on-premise deployment;
integrations with ERP/MES/SCADA/WMS.
FACT: stated stack on the glass case: "Constraint Optimization
(MILP/CP-SAT), Multi-Horizon Planning, Execution-Aware Replanning".
FACT: four engines under one Planning Cockpit (demand/capacity
scenario, multi-horizon production planning optimizer, changeover-
aware sequencing, execution-aware replanning); frozen windows for
stability; audit logging; shared furnaces/lines in the glass case.
FACT (Kleverz, attributed to the founder, unverified): 50+ families of
operational decisions; ~600 people worldwide can build such systems,
three on his team; no Middle-East competitor, ~5 worldwide (press
named Kinaxis and o9 Solutions); 6 delivered contracts EGP 14M; team
"published dozens of research papers".
FACT: their site shows "Published Papers: 0" and no benchmark numbers,
no bounds, no gaps, no reproducibility statement. Marketing claims
include "billions of permutations in milliseconds" and "mathematically
provable best answer".
FACT (Kleverz's own analysis, not makkook): "optimal" means optimal
for the model and its data; a solver may stop at a plan whose distance
from best is reported - i.e., honest OR practice states a gap.
INFERENCE: their product is a configured-per-client MILP/CP-SAT
application with a cockpit UI; the durable moat is modeling +
integration + domain engines, not a novel solver. Their public
materials show no decomposition method, no bound machinery, and no
evidence of solving anything beyond commercial CP/MIP solver defaults.

## Where The-brain is already stronger (measured basis in repo)

1. PROVEN BOUNDS: we publish measured gaps (bucket-relaxation gap
   today; global Lagrangian LB/UB gap in Phase D). They publish none.
2. INDEPENDENT RE-VALIDATION: 62,747 assignments re-checked by a
   validator independent of the solver in the 13.3M-var run. Their
   audit log records decisions; it does not re-verify them.
3. DETERMINISTIC REPRODUCIBILITY: pinned solver versions, env stamps,
   cross-shard drift check. They publish nothing reproducible.
4. MEASURED SCALE WITH EVIDENCE: 13,301,659 vars / 4,650,891 rows /
   wall 580.3 s, all published in RESULT.json. They publish no
   measured instance.
5. HONEST STATUS DISCIPLINE: UNKNOWN = undecided, never claimed
   infeasible or optimal; known-failure registry with root causes.
   "Provably optimal on every run" is not a claim a time-limited
   solver at scale can back; we do not make it.

## Where we are NOT stronger (honest)

1. REAL DATA: our instances are synthetic; they run on live client
   data. Real-world accuracy is unproven for BOTH sides publicly, but
   they operate there and we do not yet.
2. INTEGRATION + UX: cockpit, ERP/MES links, execution triggers.
   Outside our current scope.
3. CLAIM LIMIT: we cannot claim better SOLUTION QUALITY than them;
   they publish nothing to compare against. The claim available today
   is stronger verifiability, and (after item 1 below) accuracy
   measured against published literature optima.

## How we beat them on measured results (ranked build order)

1. PUBLIC BENCHMARK SWEEP (top priority of this list): solve published
   CLSP / multi-item lot-sizing instance sets (OR-Library; Trigeiro,
   Thizy & Van Wassenhove sets - all free) and report our objective vs
   PUBLISHED optima / best-known gaps, instance by instance. This is
   the only honest route to "more accurate": a number against the
   literature, which makkook has never published.
2. PHASE D COUPLED MODEL with proven global gap (docs/COUPLED-
   DESIGN.md): shared supplier + labor pools, Lagrangian LB/UB.
   "One coupled problem with a proven gap" exceeds their public
   "one model, trust us" posture.
3. DETERMINISTIC REPLAY GOLDENS: same seed + pins -> identical plan
   hash, checked in CI.
4. SCALE LADDER to the fabric cap with per-rung published evidence
   (in progress: step 2 = 384 plants running).
5. EXECUTION-FEEDBACK LOOP: our sim twin + rolling freeze already
   matches their "execution-aware replanning" pattern; publish the
   disruption-recovery measurements we already record.
