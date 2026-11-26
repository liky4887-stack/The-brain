# Hierarchical supervisor for block-scale runs (design)

> LABEL (2026-11-26): ladder = THROUGHPUT AND RELIABILITY on
> independent plants (coupling is empty by construction here);
> never cite ladder sizes as coupled-optimizer evidence. Coupled
> evidence: docs/COUPLED-MEASUREMENTS.md only, and DW bounds count
> as bounds only when bound_certified is true.

User ask (2026-11-25, 2:51 PM): stack blocks of ~100M variables toward
a billion+, with a supervisor layer over each block that reviews the
results and compares them against the other blocks. Results must be
definitive and measured, never estimates.

## What must be said plainly first

Independent blocks summed are NOT one coupled solve. The current
benchmark is a synthetic world of INDEPENDENT plants, so the block sum
happens to be a true solve of the whole instance - the coupling is
empty by construction. If plants ever share resources (common raw
material, transferable demand, shared energy), a block sum is only a
lower bound on difficulty, and the supervisor's job changes: it must
then verify cross-block COUPLING, not just block integrity. This doc
separates the two and never claims the second while doing the first.

## Layer 0: plant record (existing)

Every plant solves independently (run_plant_safe). Crashes land IN the
record with a traceback; nothing is a bare exit code.

## Layer 1: block supervisor = the merge/validate job (existing,
hardened 2026-11-25)

For one block (one workflow run, up to 256 shards = the matrix cap)
the supervisor verifies, from artifacts, never from solver claims:
- every shard artifact accounted for (missing = recorded problem,
  not silence);
- EVERY assignment of EVERY plant re-validated independently against
  the regenerated ground-truth factory (same seed): production meets
  the model's constraints, KPIs recomputed;
- aggregates (vars, rows, binaries, walls) recomputed from records;
- guard transparency: shard guards (wall/memory) report exactly which
  plants were not attempted and why;
- verdict published on every outcome to the results branch.

## Layer 2: super-block supervisor (orchestrator-driven; aggregation
## implemented 2026-11-26 in benchmarks/superblock.py +
## tests/test_superblock.py; --plant-offset plumbed through
## solve_shard.py and scale.yml, config key plant_offset default 0)

For a run of B blocks (e.g. 10 x ~100M toward ~1B), the orchestrator
(this agent, wake-driven, free) plus a superblock job verify:
1. Provenance chain: every block RESULT carries run id, commit SHA,
   ladder step; the super-block result lists them all. A number that
   cannot be traced to an artifact does not exist.
2. Recomputation: block aggregates are re-summed from block RESULTs;
   the super-block total is arithmetic over verified blocks, labelled
   MEASURED (sum of measured parts).
3. Spot re-validation: a seeded random sample of plant records
   (default 2%) is re-downloaded from artifacts and re-validated
   end-to-end (full re-validation of a billion-variable run is itself
   beyond the free fabric - that limit is stated, not hidden).
4. Cross-block consistency (what "compare blocks against each other"
   concretely means here): per-plant solve-time and per-plant variable
   distributions are compared across blocks; a block whose stats are
   outliers is flagged for re-run, because identical generator +
    identical code should give statistically similar blocks. This
   catches silent environment drift (runner downgrade, library
   change) rather than solver errors - the independent re-validation
   already catches those.
5. Coupling checks: NONE EXIST in the current benchmark (independent
   plants). When coupling is introduced, this layer must add: global
   material balance across blocks, and dual-consistency of shared
   capacity prices. Until then the supervisor reports "no coupling to
   verify" - never a vacuous "consistent".

## Watchdog spec (user voice 2:53 PM) - what each ask maps to

(a) Disjoint assignment, verified not assumed: plants are partitioned
by construction (shard_indices is a pure function; seeds derive from
the plant index), and the block supervisor now VERIFIES it: duplicate
plant ids across shards and silently skipped plants are verdict-level
problems. One block never touches another block's plants; blocks are
disjoint ranges of the same generator.

(b) Pause -> auto-heal -> resume (user correction 2:54 PM): failures
do NOT cancel the climb. Honest GitHub reality: runners cannot pause
mid-matrix and cannot talk to each other; "pause" = the orchestrator
holds the next rung's push, "resume" = re-dispatch. Within a block,
shards stay failure-isolated (never cancelled: a cancelled shard
uploads no artifact and destroys the evidence the heal needs). On a
FAIL the orchestrator: classifies the failure SIGNATURE
(benchmarks/failure_registry.py - volatile details stripped so the
same failure is recognized across runs), then, bounded at 2 heal
attempts per signature: known+fixed -> re-dispatch once, only if the
run actually contains the fix commit; known+open -> stay paused
(healing in progress); new -> diagnose, fix on a branch, full suite +
verification-harness claim, merge (every fix visible in a parent
report - no unreviewed code on main), record the registry entry,
resume. Later blocks consult the registry BEFORE running: that is
what "learn from the error" concretely means here
(benchmarks/registry/known-failures.json, committed, with first/last
seen, fix commit and avoidance rule).

(c) Watchdog, continuous: the wake-driven orchestrator plus the
results branch are the watchdog - no rung starts before the previous
rung's verdict is VERIFIED. No silent errors: failure-isolated
records + always-publish (done). No hidden errors: every guard
intervention is recorded in the artifact ("not attempted: <guard>").
No dead code paths: a coverage ratchet is added to CI (coverage must
not decrease; new code ships covered or not at all). Nothing blocks
the system: every solve has a time limit, every shard has wall/memory
guards, every job has a timeout, every outcome publishes. No wrongly
written code: independent re-validation and brute-force oracles gate
every claim (the verification harness).

## Free-fabric reality

- Block ceiling: 256 jobs/workflow (matrix cap) x 8 plants x ~69.2K
  vars (measured mean) ~ 141M vars EXTRAPOLATED; the ladder measures
  the real number rung by rung.
- Super-block: sequential block runs (free-plan concurrency makes
  parallel blocks slower, not faster). Orchestration state lives on
  the results branch; the wake-driven loop drives it.
- Honest ceiling statement: a billion variables is ~8 matrix-capped
  blocks minimum; whether the free fabric sustains that is a MEASURED
  question the ladder answers. A trillion is beyond any free tier;
  that is said plainly, not reached for.
