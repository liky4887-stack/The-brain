# HANDOFF - The-brain scale program (updated 2026-11-26, ~10:50 AM EET)

Project state only: verified benchmark results, public evidence, and
technical next steps. Everything below is measured, not planned, unless
labeled ESTIMATED/QUEUED.

## Verified benchmark state

Scale ladder (branch gate-scale/run drives the runs via
.github/workflows/scale.yml + benchmarks/scale_ceiling.py; every run's
verdict is computed by the merge job and published to
benchmarks/scale/RESULT.json on branch gate-scale-results; PASS
records are mirrored into config/scale_history.json on main, deduped
by ladder.run_id):

| Step | Plants | Shards | Vars      | Rows       | Assignments validated | Run         | Verdict |
|------|--------|--------|-----------|------------|-----------------------|-------------|---------|
| 1    | 64     | 8      | 13.30M    | -          | all, 0 problems       | 45627176287 | PASS    |
| 2    | 128    | 16     | 26.5M     | -          | all, 0 problems       | 45630465498 | PASS    |
| 3    | 256    | 32     | 30.9M     | -          | all, 0 problems       | 45637538991 | PASS    |
| 4    | 768    | 96     | 53,003,363| 18,528,930 | 249,178, 0 problems   | 45663952096 | PASS    |
| 5    | 1536   | 192    | 106,147,349| 37,106,181| 499,393, 0 problems   | 45694139435 | PASS    |
| 6    | 2048   | 256    | 141,608,152| 49,501,928| 666,396, 0 problems   | 45737026860 | PASS    |

- Step 6 closed the single-block ladder: 256 is the workflow matrix
  cap, so step 7+ is super-blocks
  (sequential disjoint plant ranges, see benchmarks/superblock.py and
  docs/SUPERVISOR.md layer 2).
- Validation: every produced assignment is re-checked by an independent
  validator (validator is separate from the solver); a step is PASS
  only with 0 validation problems and 0 unexplained UNKNOWNs.
- Determinism: pinned dependency versions in CI, fixed seeds, recorded
  params; run ids and shas above are the provenance.
- Public evidence: run status is readable anonymously at
  api.github.com/repos/liky4887-stack/The-brain/actions/runs/<id>;
  artifacts and RESULT.json live on branch gate-scale-results.

## Known measured behaviors (from the runs above)

- 8 plants/shard is the measured-safe memory point; 12 trips the
  2700s shard wall guard / 60-min job timeout.
- Dense-day escalation: bucket budget starts at 300s, caps at 600s,
  >110 chunks; UNKNOWN above the cap is a new signature to classify.
- Step-5 plant jobs: artifacts 192 shards totaling 5.0 MB; mean
  69,071 vars/plant.
- GitHub Free fabric: 20 concurrent jobs, ~2 job-starts/min metering;
  job runtime cap 6h; run retention 35 days; matrix cap 256.
  (docs.github.com/en/actions/reference/limits)
- GitHub-free ceiling analysis: 100 sequential super-blocks are
  mechanically allowed; storage hygiene is the metered constraint
  (5.0 MB/block measured vs 500 MB Free Actions storage - delete
  artifacts after validation). ~14.1B vars at 100 blocks (ESTIMATED).
- GitHub Actions/Pages terms: Actions is develop/test only and Pages
  excludes SaaS/commercial hosting - the ladder is legitimate testing;
  customer-facing serving needs separate hosting.
  (docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features)

## Verdict-handling protocol (any step)

1. Fetch: `git fetch origin gate-scale-results` then
   `git show origin/gate-scale-results:benchmarks/scale/RESULT.json`.
2. PASS: append RESULT.json to config/scale_history.json (dedup by
   ladder.run_id), commit main, push, launch the next ladder step,
   report measured numbers.
3. OPEN with a known signature: follow the registry entry's avoidance
   (benchmarks/registry/known-failures.json).
4. OPEN with a NEW signature: register (status open, attempts: 1,
   run_id/sha/step, measured summary), classify (needs-more-time vs
   hint-saturation vs bug) with a TARGETED repro (pickle the failing
   day's lots - /tmp/diag_days.py pattern from fc9f56ec5ce7 - not
   full-plant repros, they exceed 45 min), heal within the 2-attempt
   rule, suite green, commit, push, rerun the SAME step. UNKNOWN is
   undecided, never infeasible, never silently skipped.
5. Failure conclusion on an OPEN run is BY DESIGN (gate not green yet).

## Technical next steps (ranked)

1. Step 7+ super-blocks (linear chain via --plant-offset +
   benchmarks/superblock.py extend_chain) toward the free ceiling;
   report the real measured ceiling + cause when free compute stops
   scaling.
2. Serving layer (serving/): postgres queue + stdlib API + worker that
   runs the same brain_core rolling solver with the same independent
   validation; CI in .github/workflows/serving.yml. Next slices: real
   plant intake (CSV/JSON spec -> factory), result download endpoint,
   container deployment on a permitted host.
3. Coupled CG master-worker fabric workflow (12 clusters x 16 plants =
   192 coupled plants, proven gap per cluster; LB within 0.0004% of
   optimum measured at 2/4/8 plants - docs/COUPLED-MEASUREMENTS.md).
4. CG integer restricted-master UB improvement (16-plant gap 2.79%,
   UB is the weak side, LB essentially exact).
5. Benchmark sweep: MIPLIB 2017 + CLSP/Trigeiro published optima
   (licenses in docs/SCALE-UPGRADE-LIST.md).
6. Real-company-style datasets (Zenodo/Mendeley usable with citation).
7. frePPLe solver-semantics adoption (docs/FREPLE-MAP.md):
   maxlateness hard bound -> priority-weighted lateness -> soft
   safety-stock. Records already mirror frePPLe; solvers ignore the
   fields today.
8. Utilization 63.8% -> 85%+: shard count near a multiple of 20 +
   adaptive sizing (LPT matrix ordering measured NOT to work).
9. Standing: optimality headline day statuses, super-block supervisor,
   tree-merge, coverage ratchet, generator-stats publication.

## Repo conventions (hit and recovered during the runs)

- Gate suite: `python3 -m pytest tests -q -m 'not benchmark'`
  (benchmark-marked tests are slow by design and excluded from the
  gate; pytest default collects them - pyproject has no addopts
  deselect).
- Never commit while on gate-scale/run (a push there triggers a full
  scale run); check `git branch --show-current` before committing;
  recover by cherry-picking onto main + `git branch -f gate-scale/run
  origin/gate-scale/run`.
- Transient GitHub push 500s: retry after ~20s.
- Licenses: no AGPL in product; frePPLe MIT (verified 2026-11-25);
  ortools Apache-2.0; pydantic/pytest MIT; numpy/scipy BSD; PyVRP
  MIT; pg8000 BSD-3. Dataset stance in docs/SCALE-UPGRADE-LIST.md.
