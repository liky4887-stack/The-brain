"""Super-block aggregation (SUPERVISOR.md layer 2).

One block = one scale-ceiling run (up to the 256-shard matrix cap).
A super-block = several SEQUENTIAL blocks over disjoint plant ranges of
the same generator, stacking toward scales the matrix cap cannot reach
in one run. This script takes the block RESULT.json files (each
already independently validated by its own merge job) and produces the
super-block verdict:

1. Provenance chain: every block must carry ladder metadata
   {step, plants, shards, run_id, sha}; run ids must be distinct; the
   plant ranges [plant_offset, plant_offset + plants) must be
   pairwise disjoint. A number that cannot be traced to a block
   artifact does not exist.
2. Recomputation: super-block aggregates are re-summed from the block
   RESULTs and labelled MEASURED (sum of measured parts) - the blocks
   are independent plants, so the sum is a true solve of the whole
   instance, never an estimate. Walls are reported per block and
   summed (blocks run sequentially; the sum is the fabric time).
3. Cross-block consistency: per-plant solve-time means are compared
   across blocks; a block whose mean deviates from the pooled mean of
   the others by more than 50% is flagged (identical generator +
   identical code should give statistically similar blocks; drift
   points at the environment, not the solver). A flag makes the
   super-block verdict OPEN, never silently PASS.
4. Verdict: PASS only if every block is PASS, no block reports missing
   shards or validation problems, ranges are disjoint, and no
   consistency flag fires. Otherwise OPEN with the reasons listed.

Spot re-validation (2% sample re-downloaded from artifacts, per the
design) is an orchestrator duty at run time, not part of this
arithmetic; the super-block result says so plainly.

Usage: python benchmarks/superblock.py RESULT_A.json RESULT_B.json ...
Writes SUPERBLOCK_RESULT.json next to the first input.
"""

from __future__ import annotations

import json
import os
import sys
import statistics

CONSISTENCY_TOL = 0.5  # block mean per-plant solve time vs pooled others


def _plant_range(block):
    lad = block.get("ladder", {})
    off = int(lad.get("plant_offset", 0))
    return off, off + int(lad.get("plants", block["measured"]["plants"]))


def aggregate(blocks: list[dict]) -> dict:
    problems: list[str] = []

    # 1. provenance
    run_ids = []
    ranges = []
    for i, b in enumerate(blocks):
        lad = b.get("ladder")
        if not lad or not all(k in lad for k in
                              ("step", "plants", "shards", "run_id", "sha")):
            problems.append(f"block {i}: missing ladder provenance "
                            f"(step/plants/shards/run_id/sha)")
            continue
        run_ids.append(str(lad["run_id"]))
        ranges.append(_plant_range(b))
    if len(run_ids) != len(set(run_ids)):
        problems.append(f"run ids not distinct: {run_ids}")
    for i in range(len(ranges)):
        for j in range(i + 1, len(ranges)):
            lo = max(ranges[i][0], ranges[j][0])
            hi = min(ranges[i][1], ranges[j][1])
            if lo < hi:
                problems.append(f"blocks {i} and {j}: plant ranges overlap "
                                f"[{lo}, {hi}) - disjointness violated")

    # 2. verdict inputs from each block
    for i, b in enumerate(blocks):
        if b.get("verdict") != "PASS":
            problems.append(f"block {i} (run {b.get('ladder', {}).get('run_id')}): "
                            f"verdict {b.get('verdict')} - a super-block sums "
                            f"PASS blocks only")
        if b.get("shards_missing"):
            problems.append(f"block {i}: missing shards "
                            f"{b['shards_missing']}")
        m = b["measured"]
        if m.get("n_validation_problems"):
            problems.append(f"block {i}: {m['n_validation_problems']} "
                            f"validation problems")

    # 3. recomputation (MEASURED: sum of measured parts)
    agg = {"vars": 0, "rows": 0, "binaries": 0, "windows": 0,
           "assignments": 0, "changeover_minutes": 0.0,
           "backlog_units_end": 0.0, "distributed_wall_s": 0.0,
           "merge_validate_s": 0.0}
    means = []
    for b in blocks:
        m = b["measured"]
        agg["vars"] += m["aggregate_vars"]
        agg["rows"] += m["aggregate_rows"]
        agg["binaries"] += m["aggregate_binaries"]
        agg["windows"] += m["windows"]
        agg["assignments"] += m["assignments_validated"]
        agg["changeover_minutes"] += m["kpis"]["changeover_minutes"]
        agg["backlog_units_end"] += m["kpis"]["backlog_units_end"]
        agg["distributed_wall_s"] += m["distributed_wall_s"]
        agg["merge_validate_s"] += m["merge_validate_s"]
        means.append(m["per_plant_solve_s"]["mean"])

    # 4. cross-block consistency
    for i, mean in enumerate(means):
        others = [v for k, v in enumerate(means) if k != i]
        if not others:
            continue
        pooled = statistics.fmean(others)
        if pooled > 0 and abs(mean - pooled) / pooled > CONSISTENCY_TOL:
            problems.append(
                f"block {i}: per-plant solve-time mean {mean:.1f}s "
                f"deviates from the pooled other-block mean {pooled:.1f}s "
                f"by >{CONSISTENCY_TOL:.0%} - environment drift suspect, "
                f"re-run the block")

    verdict = "PASS" if not problems else "OPEN"
    return {
        "kind": "super-block",
        "verdict": verdict,
        "label": "MEASURED (sum of independently validated block results; "
                 "plants are independent, so the block sum is a true solve "
                 "of the whole instance)",
        "spot_revalidation": "orchestrator duty at run time (2% sample "
                             "re-downloaded from artifacts, SUPERVISOR.md "
                             "layer 2 point 3) - not part of this "
                             "arithmetic",
        "blocks": [{"run_id": str(b.get("ladder", {}).get("run_id")),
                    "sha": b.get("ladder", {}).get("sha"),
                    "plants": b["measured"]["plants"],
                    "plant_range": list(ranges[i]) if i < len(ranges) else None,
                    "verdict": b.get("verdict")}
                   for i, b in enumerate(blocks)],
        "measured": {
            "plants": sum(b["measured"]["plants"] for b in blocks),
            **agg,
        },
        "problems": problems,
    }


def extend_chain(chain: dict | None, new_block: dict) -> dict:
    """ONE linear chain (user requirement 2026-11-26): blocks append in
    order to a single super-block result, never scattered merges.

    Rules on top of aggregate():
    - the first block must start at plant 0;
    - every appended block's plant range must start EXACTLY where the
      chain currently ends (no gaps, no overlaps, no reordering);
    - the chain's blocks stay in append order in the output; the final
      output is ONE object with the full ordered provenance chain.
    A broken append makes the chain verdict OPEN with the reason; the
    previous chain content is preserved in the output's blocks list.
    """
    prior = [] if chain is None else list(chain.get("blocks_raw", []))
    prior.append(new_block)
    out = aggregate(prior)
    problems = list(out["problems"])
    end = 0
    for i, b in enumerate(prior):
        lo, hi = _plant_range(b)
        if lo != end:
            problems.append(
                f"chain break at block {i}: range starts at {lo}, chain "
                f"ends at {end} - blocks must append exactly tail-to-head")
        end = max(end, hi)
    out["problems"] = problems
    out["verdict"] = "PASS" if not problems else "OPEN"
    out["chain"] = {"length": len(prior),
                    "plant_span": [0, end],
                    "ordered_run_ids": [str(b.get("ladder", {}).get("run_id"))
                                        for b in prior]}
    out["blocks_raw"] = prior  # the chain, for the next append
    return out


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    blocks = [json.load(open(p)) for p in sys.argv[1:]]
    out = aggregate(blocks)
    path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])),
                        "SUPERBLOCK_RESULT.json")
    json.dump(out, open(path, "w"), indent=1)
    m = out["measured"]
    print(f"super-block verdict {out['verdict']}: plants {m['plants']:,} "
          f"vars {m['vars']:,} rows {m['rows']:,} "
          f"assignments {m['assignments']:,}")
    for p in out["problems"]:
        print("PROBLEM:", p)


if __name__ == "__main__":
    main()
