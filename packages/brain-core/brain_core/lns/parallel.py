"""Parallel LNS shards (Stage: distributed solve, Phase B).

Several workers run lns_improve on the SAME incumbent with different
seeds / free fractions (independent destroy-repair trajectories), and
the merge keeps the best. Honesty rules:

- comparability is exact, not assumed: every candidate objective was
  recomputed from its returned x over the FULL variable set with the
  SAME cost vector (lns_improve does this per neighbourhood), so
  picking the minimum is sound;
- never-worse is structural: the incumbent itself is always candidate
  zero, so the merged result can never be worse than what went in;
- improvement is measured, not claimed: merged.improved is true only
  when the winning candidate strictly beats the incumbent's own
  recomputed objective by EPS.
"""
from __future__ import annotations

from .bucket import EPS, LNSResult


def merge_lns_results(incumbent_objective: float,
                      results: list[LNSResult]) -> LNSResult:
    """Pick the recomputed-best LNS shard result.

    incumbent_objective: the incumbent's own recomputed objective
    (candidate zero). Returns the best shard's LNSResult with
    `improved` re-evaluated against the incumbent (never worse)."""
    if not results:
        raise ValueError("no LNS shard results to merge")
    best = min(results, key=lambda r: r.bucket.objective
               if r.bucket.objective is not None else float("inf"))
    if best.bucket.objective is None:
        raise ValueError("winning shard has no objective")
    improved = best.bucket.objective < incumbent_objective - EPS
    return LNSResult(best.bucket, improved, incumbent_objective,
                     best.bucket.objective,
                     sum(r.iterations_run for r in results),
                     sum(r.accepted for r in results),
                     sum(r.wall_s for r in results),
                     [h for r in results for h in r.history])
