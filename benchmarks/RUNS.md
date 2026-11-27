# Runs log

One line per launched run: id, SHA, block, plant range, status,
reason if cancelled. The provenance anchor for every ladder and
crossover claim; RESULT.json files carry sha/argv/range per shard.

| when (UTC) | run id | SHA | what | plant range / sizes | status / reason |
|---|---|---|---|---|---|
| 2026-11-25..26 | 45616135861..45737026860 | see scale_history | ladder steps 1-6 | per config/scale_history.json | PASS (7 entries recorded there) |
| 2026-11-26 08:48 | 45786313189 | 1e8ef94 | ladder step 7 block B | INTENDED [2048, 4096); ACTUAL [0, 2048) | CANCELLED: launched from stale gate-scale/run predating the offset plumbing (40ac926 not an ancestor); re-solved block A's range; shard 194 also cancelled at the 60-min timeout (registry 43c2596bdee8) |
| 2026-11-26 14:41 | 45841504784 | main | coupled crossover (1 replica) | n=2,4,8,16,32,64 | CANCELLED by concurrency group on relaunch with 5 replicas |
| 2026-11-26 14:46 | 45842450508 | main | coupled crossover (5 replicas) | n=2,4,8,16,32,64 | COMPLETED success, but UB plans INVALID (VOID, see docs/COUPLED-MEASUREMENTS.md); superseded by run 45863417715 |
| 2026-11-26 15:13 | 45846995824 | 3f98ab6 | ladder step 7 block B RETRY | [2048, 4096) | CANCELLED (completed/cancelled per API 2026-11-27); block B later ran as 45858321122 |
| 2026-11-26 15:47 UTC | 45852637645 | 366983699cd6 | ladder step 7 block B | [2048, 4096) | launched via workflow_dispatch on main relaunch at main for canary+manifest+closure hardening, replaces 45846995824 (sha 3f98ab6, predates canary AND the wave hard bound 7421b66) |
| 2026-11-26 16:23 UTC | 45858321122 | 2e4b75e81a64 | ladder step 7 block B | [2048, 4096) | launched via workflow_dispatch on main heal e1945e36a495 (import sys), replaces 45852637645; carries budget recording + merge enforcement |
