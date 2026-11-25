# HANDOFF - The-brain scale program (2026-11-25, ~10:20 PM EET)

Written at agent handoff. Everything below is measured state, not plans,
unless labeled ESTIMATED/QUEUED.

## Where things stand RIGHT NOW

- main = 305b1eab8c62c1a6cf01eec9119d6e3e763a9a7e + the commit that
  adds this file and the step-4 PASS record (see git log). Suite:
  345 passed / 3 skipped / 19 benchmark deselected (run with
  `python3 -m pytest tests -q -m 'not benchmark'`; benchmark-marked
  tests are slow by design and excluded from the gate).
- STEP 4 (768 plants / 96 shards) = PASS, run 45663952096, sha
  afec95ebbd36. Measured: 53,003,363 vars / 18,528,930 rows /
  6,115,382 binaries / 249,178 assignments validated / 0 validation
  problems / both previously-UNKNOWN days decided (dense-day heal).
  distributed_wall_s 2878.2, merge_validate_s 215.2, backlog ~0.
  Recorded in config/scale_history.json (5 entries, deduped by run_id).
  Note: the earlier OPEN run reported 249,179 validated vs 249,178 now -
  a 1-assignment delta from budget-dependent chunk splitting; both runs
  validated every assignment they produced. Not a lost assignment.
- Ladder so far: S1 PASS 13.30M vars (run 45627176287), S2 PASS 26.5M
  (45630465498), S3 PASS 30.9M (45637538991), S4 PASS 53.0M
  (45663952096).

## Step 5 (QUEUED/launching at handoff)

- config/scale.json on branch gate-scale/run: step 5, plants 1536,
  shards 192 (8 plants/shard = measured-safe memory, unchanged).
  ESTIMATED ~105-106M vars (2x step 4's 53.0M). Pushing gate-scale/run
  triggers the run automatically (workflow .github/workflows/scale.yml,
  driven by benchmarks/scale_ceiling.py).
- Expected wall: step 4 took ~3h end-to-end with the dense-day budgets
  (plant jobs median 1771s, max 2687s; ~2 job-starts/min metering;
  20-job concurrency cap). ESTIMATED step 5: ~4-6h (192 shards at 20
  concurrent). Dense-day escalation (300s start / 600s cap, >110
  chunks) applies; at 192 SKUs/plant more days may cross the threshold
  - watch for UNKNOWNs ABOVE 600s, which would be a new signature.

## What to do on a step verdict (any step)

1. Fetch: `git fetch origin gate-scale-results` then
   `git show origin/gate-scale-results:benchmarks/scale/RESULT.json`.
   The verdict is computed by the merge job and published on every
   outcome (never depend on signed-in logs; the public API
   api.github.com/repos/liky4887-stack/The-brain/actions/runs/<id>
   works anonymously for status).
2. PASS: append RESULT.json to config/scale_history.json (dedup by
   ladder.run_id), commit main, push, verify with
   `git ls-remote origin main`, launch the next ladder step (double
   plants+shards), arm a watcher wake, report measured numbers.
3. OPEN with a known signature: follow the registry entry's avoidance.
4. OPEN with a NEW signature: register in
   benchmarks/registry/known-failures.json (status open, attempts: 1,
   run_id/sha/step, measured summary), classify (needs-more-time vs
   hint-saturation vs bug) with a TARGETED repro (pickle the failing
   day's lots - see /tmp/diag_days.py pattern from fc9f56ec5ce7 - not
   full-plant repros, they exceed 45 min), heal, suite, commit, push,
   rerun the SAME step. UNKNOWN is undecided, never infeasible, never
   silently skipped.
5. Failure conclusion on an OPEN run is BY DESIGN (gate not green yet).

## The user's standing instructions (do not lose these)

- Measured only: headline numbers only from actual solves with solver
  status; MEASURED vs EXTRAPOLATED labels; no unvalidated metrics;
  validator independent of solver; UNKNOWN != infeasible; no unproven
  goldens; deterministic reproducibility (pinned versions, fixed
  seeds, recorded params); LLMs never decide plans.
- No UNKNOWN left unexplained: every UNKNOWN gets classified, healed
  or recorded with a measured ceiling, and the user hears about it.
- Autonomy: gaps applied without asking; build -> test -> branch ->
  merge --no-ff (no force pushes) -> keep main in sync; push green to
  main; report only real milestones/blockers/money.
- Money: FREE routes only (GitHub Free = 20 concurrent jobs, ~2
  starts/min); no spend, single account, no ToS evasion; if a wall is
  hit, report the real measured ceiling + cause.
- Security: never install/run untrusted repos (patterns only); no
  secrets in chat; the clone's remote URL embeds credentials - never
  print it, never git remote set-url; verify pushes via ls-remote.
- Public/open-licensed material only (leaked/confidential explicitly
  excluded by the parent at 5:01 PM).
- Licenses: no AGPL in product; frePPLe is MIT since 2026-11-25
  (verified); ortools Apache-2.0, pydantic/pytest MIT, numpy/scipy
  BSD, PyVRP MIT; dataset stance in docs/SCALE-UPGRADE-LIST.md
  (Zenodo CC-BY + Mendeley CC-BY/MIT usable with citation;
  trigeiro_fdata + EMRPS unlicensed = cite-only, no vendoring).

## Open gap list (ranked, from SCALE-UPGRADE-LIST.md + today)

1. Step 5 verdict handling (above), then steps 6+ toward ~1B vars;
   report the real measured ceiling + cause when free compute stops
   scaling.
2. Coupled CG master-worker fabric workflow (12 clusters x 16 plants =
   192 coupled plants, proven gap per cluster; LB within 0.0004% of
   optimum measured at 2/4/8 plants - docs/COUPLED-MEASUREMENTS.md).
3. CG integer restricted-master UB improvement (16-plant gap 2.79%,
   UB is the weak side, LB essentially exact).
4. Benchmark sweep: MIPLIB 2017 + CLSP/Trigeiro published optima
   (licenses verified today, see SCALE-UPGRADE-LIST.md).
5. Real-company-style datasets (Zenodo/Mendeley verified usable).
6. frePPLe solver-semantics adoption (docs/FREPLE-MAP.md):
   maxlateness hard bound -> priority-weighted lateness -> soft
   safety-stock. Records already mirror frePPLe; solvers ignore the
   fields today.
7. Utilization 63.8% -> 85%+: shard count near a multiple of 20 +
   adaptive sizing (LPT matrix ordering measured NOT to work).
8. Standing: optimality headline day statuses, super-block supervisor,
   tree-merge, coverage ratchet, generator-stats publication.

## Operational gotchas (all hit today, all recovered)

- pytest default collects benchmark-marked tests (pyproject has no
  addopts deselect): always `-m 'not benchmark'` for the gate suite.
- Do not commit while on gate-scale/run (a push there triggers a full
  scale run); check `git branch --show-current` before committing;
  recover by cherry-picking onto main + `git branch -f gate-scale/run
  origin/gate-scale/run`.
- Transient GitHub push 500s: retry after ~20s.
- Bash `cd X && cmd &` backgrounds the cd too; detach long jobs with
  `setsid nohup ... < /dev/null > log 2>&1 &`.
- Agent runs cap at ~35 min; arm a wake for anything longer.
