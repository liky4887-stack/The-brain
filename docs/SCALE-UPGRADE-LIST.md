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

## Staggered/pipelined dispatch - VERDICT (measured + documented, 2026-11-25)

User proposal (4:54 PM): stagger cluster starts 5-10 s so all 20 slots
stay busy. Verdict: staggering does NOT add capacity, and the queue
already pipelines.

- DOCUMENTED (docs.github.com/en/actions/reference/limits, "Job
  concurrency limits for GitHub-hosted runners"): standard runner,
  Free plan = 20 TOTAL concurrent jobs per account (Pro 40, Team 60,
  Enterprise 500). Support can raise it; not free. One pool per
  account: N staggered runs share the same 20 slots.
- MEASURED (scale step-2 run 45630465498, per-job start/end stamps
  from the public API): peak occupancy = 20 (the cap binds), mean =
  12.75 (63.8% of the 20-slot cap over the 1435 s solve window), job
  durations 319-604 s (mean 381). The occupancy curve shows the loss
  is NOT inter-wave idling: slots fill progressively (~2 job-starts
  per minute for the first ~8 min: 8 slots for 5 min, then a linear
  ramp to 20) and drain smoothly at the tail (20 -> 1 over the last
  ~7 min). The queue starts a queued job as soon as a slot frees -
  pipelining is already automatic.
- What would actually recover the lost ~36%: (a) fewer, longer jobs
  (less exposure to the ~2/min start metering; e.g. 40 shards instead
  of 48 for the same plant count = 2 exact waves), (b) adaptive shard
  sizing (already on this list; smaller stragglers shrink the tail).
  Staggered run starts implement none of these and are NOT adopted.
- LPT matrix ordering REJECTED after measurement (same day): the
  step-2 run's actual job-start order (public API stamps) is NOT
  matrix order - shard start sequence began 19, 26, 29, 37, 41, 47,
  18, ... i.e. GitHub does not start matrix jobs in definition
  order, so ordering the matrix list cannot schedule anything. Do not
  implement LPT via matrix ordering; the lever is shard sizing only.

## What else the system can be pushed to do (user ask 2026-11-25 4:57 PM; grounded in today's measured findings)

1. CLOSE THE COUPLED GAP BELOW 1%: the CG master LP bound is measured
   within 0.0004% of optimum; the integer restricted master is the
   weak side (2.79% at 16 plants). Branch-and-price-lite (re-price
   after branching on the fractional master) or fractional-master
   repair closes it. Highest-value MILP improvement available.
2. COUPLED CLAIMS AT FABRIC SCALE: workers-per-round -> one master
   job per cluster (state via artifacts); 12 clusters x 16 plants =
   192 coupled plants each with a per-cluster proven gap. The honest
   "coupled at scale" headline.
3. UTILIZATION 63.8% -> 85%+: shard count near a multiple of 20 +
   adaptive sizing (LPT matrix ordering measured NOT to work -
   GitHub ignores matrix order; see the staggering verdict above).
4. EXTERNAL VERIFIABILITY: MIPLIB 2017 + CLSP/Trigeiro published
   optima as free targets; no competitor publishes bounds - the sweep
   makes the "show me yours" claim concrete.
5. REAL-COMPANY-STYLE PLANS: Zenodo 10.5281/zenodo.17493292 /
   Mendeley 10.17632/gdm7nkn6b3 / EMRPS refinery benchmark after
   license verification.
6. frePPLe (now MIT) feature mapping: demand pegging, buffer model,
   fences/policies - adopt missing pieces with citations.
7. Standing gaps (unchanged): optimality headline day statuses,
   adaptive shard sizing, super-block supervisor, tree-merge,
   coverage ratchet, generator-stats publication.
8. IPM items from Wright 1997 (skill: docs/skills/
   wright-primal-dual-ipm.md, 2026-11-26): (a) DONE - least-squares
   cold start implemented (_least_squares_start, measured: 484 vs 525
   total iterations vs all-ones on the seeded set); (b) HSD embedding
   for CERTIFIED infeasibility in the IPM (today: blowup diagnostic
   only, simplex owns certificates); (c) crossover / optimal-basis
   recovery (ch.7 BUN partition) if an exact vertex from an IPM
   solution is ever needed. CG master LP solver: dual simplex
   KEPT - ch.11 sequence-of-similar-LPs analysis + measured one-shot
   A/B vs HiGHS IPM (<=8000 cols: within noise, same objective).

### Benchmark sources pinned (2026-11-25, for the sweep)
License verification (done 2026-11-25, live pages):
- Zenodo 10.5281/zenodo.17493292 (Willms & Brandenburg 2025, benchmark
  dataset for production planning + detailed scheduling in process
  industries): CC-BY 4.0 (verified on the record page). USABLE with
  citation.
- Mendeley 10.17632/gdm7nkn6b3 (FJSP with dual-mode parallel batching,
  35 instances + preprocessing/plotting code): data CC BY 4.0, code
  MIT (stated on the dataset page). USABLE with citation. Targets the
  day-model (level 2) side of the sweep.
- MIPLIB 2017 (miplib.zib.de): no explicit license text on the site
  (checked homepage 2026-11-25); the collection is published openly
  for benchmarking with a citation request (DOI
  10.1007/s12532-020-00194-3). USABLE with citation; download at sweep
  time, do NOT vendor instances into the repo.
- Trigeiro/Thomas/McClain 1989 CLSP instances:
  github.com/gsamaro/trigeiro_fdata has NO license (GitHub license API
  + repo page, 2026-11-25) -> all rights reserved; do not vendor.
  suerie.de/testsets.html (TU Darmstadt CLSP/CLSPL test sets) also
  carries no explicit license; academic redistribution with citation
  is customary. Sweep stance: use the published TTM 1989 optima as
  reference numbers, obtain instances from suerie.de with citation,
  record the license caveat in the sweep writeup.
- EMRPS/refinery-planning-benchmark (arXiv:2503.22057): NO license
  (GitHub license API + README, 2026-11-25); README asks only for
  citation of the arXiv preprint. Academic use with citation; do not
  vendor; note instances carry no proven optima ("global optimum
  cannot be guaranteed" per README).

### GitHub-free ceiling: how many sequential blocks (2026-11-26, user question)

Answered from the live GitHub docs + our measured block stats. Repo
visibility confirmed public (api.github.com repo record, 2026-11-26), so
standard-runner compute is free and does NOT draw from any minutes quota.

Live-doc facts (URLs at the end):
- Public repos: standard GitHub-hosted runner usage remains free, no
  monthly minutes quota applies (billing concept page + billing/usage
  page).
- Job execution limit 6 h/job; workflow run limit 35 days; matrix cap
  256 jobs/run; re-run cap 50/run (actions/reference/limits).
- Concurrency: Free plan = 20 total concurrent jobs (same page).
- Free plan included storage: 500 MB Actions artifacts + $12/month
  included compute (compute is for PRIVATE repos; ours is public)
  (billing/reference/product-usage-included). Storage bills by GB-hours
  accrued; deleting artifacts stops future accrual (billing concept page).
- API: GITHUB_TOKEN 1000 req/h/repo; PAT 5000 req/h (limits page).

Measured block stats:
- Step 5 (1536 plants): 7h20m end-to-end, 106,147,349 vars
  (69,071 vars/plant measured mean), 192 artifacts totaling 5.0 MB.
- Step 6 block (2048 plants): ESTIMATED ~141.4M vars at the measured
  per-plant mean; wall measuring now.

Ceiling analysis:
- COMPUTE: no cap on the number of sequential runs for a public repo on
  standard runners. 100 blocks is mechanically allowed. 100 x ~8h
  (ESTIMATED from the measured 7h20m; step 6 refines) = ~33 days
  continuous. Per-run limits (6 h job, 35-day run, 256 matrix, 50
  re-runs) are all far from our shape (~45-50 min shard jobs, fresh run
  per block).
- STORAGE: the only metered resource. 5.0 MB/block measured; 100 blocks
  with the 30-day retention ~= 500-700 MB vs the 500 MB Free allowance -
  borderline (ESTIMATED). Mitigation (standard hygiene, not evasion):
  delete a block's artifacts after its merge validation + the spot
  re-validation window; RESULT.json on gate-scale-results is the
  permanent record. In-flight storage then stays ~2 blocks (~14 MB).
- RELIABILITY over ~33 days continuous: weekly runner-image updates can
  trip the environment-drift check (by design it flags, supervisor
  pauses+heals); the 2-attempt heal rule bounds automatic recovery.
- VARIABLES: 100 blocks x ~141.4M = ~14.1 BILLION vars (ESTIMATED);
  1 billion vars at ~7 blocks of 2048 plants (~2.5 days, ESTIMATED).
- Answer: yes, 100 blocks is within the documented free use; the honest
  constraints are wall-clock (~33 days) and artifact-storage hygiene,
  not quotas. ToS: normal CI of our own code on a public repo, standard
  runners, single account - no evasion.

Sources:
- https://docs.github.com/en/actions/administering-github-actions/usage-limits-billing-and-administration
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/billing/reference/product-usage-included

### Can GitHub be the production server for customers? (2026-11-26, user question) - NO, terms prohibit it

Live-terms answer (GitHub Terms for Additional Products and Features,
Actions and Pages sections, fetched 2026-11-26):

- Actions may NOT be used for "the provision of a stand-alone or
  integrated application or service offering the Actions product or
  service, or any elements of the Actions product or service, for
  commercial purposes"; nor for "any activity that places a burden on
  our servers ... disproportionate to the benefits provided to users
  (for example, don't use Actions as a content delivery network or as
  part of a serverless application)"; and, on GitHub-hosted runners,
  not for "any other activity unrelated to the production, testing,
  deployment, or publication of the software project associated with
  the repository". It also says plainly: "You may only access and use
  GitHub Actions to develop and test your application(s)."
- Pages is "not intended for or allowed to be used as a free web
  hosting service to run your online business, e-commerce site, or any
  other website that is primarily directed at either facilitating
  commercial transactions or providing commercial software as a
  service (SaaS)".
- Enforcement named in the terms: GitHub may monitor usage; misuse can
  mean terminated jobs, disabled repos, account suspension.

Consequence for The-brain: the ladder and every benchmark run are
legitimate - they ARE testing the software project of this repository,
which is what Actions is for. Serving customers (a planner-facing
service that runs plans for factories) from Actions runners or Pages is
prohibited by the terms. Production serving needs real hosting when the
product ships (its own decision later); Actions stays the CI/benchmark
fabric. The engine being proven on Actions is exactly what makes it
portable to any host.

Hard limits for long chains of runs (docs.github.com/en/actions/
reference/limits + billing pages, fetched 2026-11-26):
- 6 h per job (our shard jobs measured <= ~45-50 min - far inside).
- 35 days per workflow run (our blocks are fresh runs of ~7-10 h).
- 256 jobs per matrix (respected: block = 256 shards max).
- 50 re-runs per run (we never re-run; fresh run per block).
- 20 concurrent jobs on Free (queueing absorbs the rest - measured).
- 500 MB artifact storage included on Free; GB-hours accrual; delete
  after validation (5.0 MB/block measured) keeps us far inside.
- GITHUB_TOKEN 1000 req/h/repo; PAT 5000 req/h (our runs use a handful).
- Run count itself: no documented cap for public repos - the ceiling is
  wall-clock and reliability, not quota.

Source: https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features
