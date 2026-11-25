"""Ceiling-discovery ladder: how far past 6.6M variables can the free
Actions fabric take this repo's own solver?

One run of .github/workflows/scale.yml is one ladder step, configured
by config/scale.json. This module is the orchestrator brain: given the
history of measured RESULT.json verdicts it decides the next action
(run step k / stop with the measured ceiling). It never estimates a
ceiling: the ceiling is the last MEASURED pass, and the failure mode
of the step that failed is reported alongside.

Ladder design (honest defaults):
- 8 plants per shard, fixed: proven memory-safe on the 16 GB runner in
  the 96-plant run (shard RSS measured, no OOM). Scaling raises shard
  COUNT, not per-shard memory, so the limits discovered are the real
  fabric limits: job concurrency (queue waves), wall time, artifact
  and merge load, and the 256-job matrix cap.
- Steps roughly double: 192, 384, 768, 1536, 2048 plants.
- 2048 plants / 256 shards is the hard matrix cap (GitHub limit).

Verdicts per step (from benchmarks/scale/RESULT.json):
  PASS          every window solved (OK), all shards reported
  FAIL          unsolved/failed windows or shard failures: the ceiling
  HARNESS-ERROR the harness itself broke (fix, re-run same step)
Wall beyond the 1800 s gate is NOT a failure here (the 30-min gate
was decommissioned as the target); it is recorded as measured wall.
"""
from __future__ import annotations

import argparse
import json
import os

# (plants, shards); 8 plants per shard; last step is the matrix cap.
# Step 3 (448 plants) is the user's ~30M-variable target rung
# (448 x 69.2K measured-mean vars/plant ~= 31.0M, EXTRAPOLATED).
LADDER = [(192, 24), (384, 48), (448, 56), (768, 96),
          (1536, 192), (2048, 256)]
CONFIG_PATH = os.path.join("config", "scale.json")
RESULT_PATH = os.path.join("benchmarks", "scale", "RESULT.json")


def classify(result: dict) -> tuple[str, str]:
    """(status, reason) from one measured RESULT.json.

    Schema is the real one written by benchmarks/gate2m/merge_validate.py:
    verdict PASS/OPEN/HARNESS-ERROR, measured.{shards,
    n_validation_problems, validation_problems, ...}, plus the ladder
    stamp added by the scale workflow. Anything but a clean PASS is a
    FAIL for ceiling purposes; the reason keeps the honest distinction
    (infeasible window vs undecided-after-escalation vs runner death).
    """
    if result.get("verdict") == "HARNESS-ERROR":
        return ("HARNESS-ERROR", str(result.get("error"))[:200])
    measured = result.get("measured", {})
    expected = (result.get("ladder", {}) or {}).get("shards") or \
        result.get("shards_expected")
    got = measured.get("shards")
    if expected is not None and got is not None and got != expected:
        return ("FAIL", f"{got}/{expected} shards reported")
    n_problems = measured.get("n_validation_problems") or 0
    if n_problems:
        first = (measured.get("validation_problems") or ["?"])[0]
        return ("FAIL", f"{n_problems} validation problem(s): "
                        f"{str(first)[:150]}")
    if result.get("verdict") != "PASS":
        return ("FAIL", f"verdict {result.get('verdict')!r}")
    return ("PASS", "all windows solved, all assignments re-validated")


def next_action(history: list[dict]) -> dict:
    """history: measured RESULT dicts in ladder order (step 1 first).
    Returns the next action: run a step, or stop with the ceiling."""
    done = {h.get("ladder", {}).get("step"): h for h in history}
    for k, (plants, shards) in enumerate(LADDER, start=1):
        r = done.get(k)
        if r is None:
            return {"action": "run", "step": k,
                    "plants": plants, "shards": shards,
                    "why": f"step {k} not measured yet"}
        status, reason = classify(r)
        if status == "HARNESS-ERROR":
            return {"action": "rerun", "step": k,
                    "plants": plants, "shards": shards,
                    "why": f"harness error to fix first: {reason}"}
        if status != "PASS":
            prev = done.get(k - 1)
            ceiling = _ceiling(prev, k - 1)
            ceiling["failed_step"] = {"step": k, "plants": plants,
                                      "shards": shards, "reason": reason}
            return {"action": "stop", **ceiling}
    # ladder exhausted: the fabric's matrix cap is the ceiling
    return {"action": "stop", **_ceiling(done.get(len(LADDER)),
                                         len(LADDER)),
            "note": "GitHub 256-job matrix cap reached, still PASS"}


def _ceiling(result: dict | None, step: int) -> dict:
    if result is None:
        return {"ceiling": None, "why": "no measured pass at any step"}
    m = result.get("measured", {})
    ladder = result.get("ladder", {}) or {}
    return {"ceiling": {
        "step": step,
        "plants": ladder.get("plants", m.get("plants")),
        "shards": ladder.get("shards", m.get("shards")),
        "variables": m.get("aggregate_vars"),
        "rows": m.get("aggregate_rows"),
        "binaries": m.get("aggregate_binaries"),
        "distributed_wall_s": m.get("distributed_wall_s"),
        "label": "MEASURED on the free fabric"}}


def write_config(repo: str, step: int, plants: int, shards: int) -> str:
    path = os.path.join(repo, CONFIG_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = {"step": step, "plants": plants, "shards": shards,
           "note": f"ladder step {step}: 8 plants/shard "
                   "(measured-safe memory)"}
    with open(path, "w") as fh:
        json.dump(cfg, fh, indent=1)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["plan", "write-config"])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--step", type=int)
    ap.add_argument("--plants", type=int)
    ap.add_argument("--shards", type=int)
    a = ap.parse_args()
    if a.cmd == "plan":
        history = []
        p = os.path.join(a.repo, RESULT_PATH)
        if os.path.exists(p):
            history.append(json.load(open(p)))
        print(json.dumps(next_action(history), indent=1))
    else:
        print(write_config(a.repo, a.step, a.plants, a.shards))


if __name__ == "__main__":
    main()
