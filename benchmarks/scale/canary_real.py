"""Real-path canary (review #12 points 2-3).

Solves ONE small plant (first plant of the block, 1 window, short time
limits) through the production run_plant, writes the shard checkpoint
and final payload with the REAL solve_shard._checkpoint, then runs the
real merge_validate on that file against the frozen manifest. Any
exception or any validation problem exits nonzero: no launch.
This file lives outside the ladder solve-path closure on purpose, so
adding or changing it never perturbs the chain-rule diff.

Usage: python benchmarks/scale/canary_real.py --plant-offset N --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gate2m"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "packages", "brain-core"))

import solve_shard  # noqa: E402
from common import BASE_SEED, plant_data_hash, run_plant  # noqa: E402
from brain_core.synthetic import FnbParams  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plant-offset", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    i = a.plant_offset
    t0 = time.monotonic()
    rec = run_plant(i, params=FnbParams(seed=BASE_SEED + i, days=14),
                    n_windows=1, bucket_time_s=15.0, seq_time_s=15.0)
    rec["data_hash"] = plant_data_hash(i)
    path = os.path.join(a.out, "shard-0.json")
    ns = types.SimpleNamespace(shard=0, shards=1, plant_offset=i, plants=1)
    env = solve_shard.env_stamp(1, 1)
    solve_shard._checkpoint(ns, [i], env, "canary", path, {i: rec})
    d = json.load(open(path))
    d["partial"] = False
    d["wall_s"] = round(time.monotonic() - t0, 1)
    d["guards_actual"] = {"job_budget_s": 5700.0, "upload_margin_s": 300.0}
    json.dump(d, open(path, "w"))
    print("canary shard written:", path, "plant", i)
    sys.stdout.flush()
    mdir = os.path.join(a.out, "merged")
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "..", "gate2m",
                                      "merge_validate.py"),
         "--artifacts", a.out, "--shards", "1", "--plants", "1",
         "--plant-offset", str(i), "--expected-job-budget-s", "5700",
         "--out", mdir], capture_output=True, text=True)
    res = json.load(open(os.path.join(mdir, "RESULT.json")))
    m = res["measured"]
    print("merge check: problems =", m["n_validation_problems"],
          "missing =", res["shards_missing"], "assignments =",
          m["assignments_validated"])
    # verdict itself is OPEN by design (one plant is below the gate's
    # size floors); what must be clean is every validation check
    if m["n_validation_problems"] or res["shards_missing"] \
            or not m["assignments_validated"]:
        print(json.dumps(m["validation_problems"], indent=1))
        sys.exit(1)
    print("CANARY REAL PATH OK")


if __name__ == "__main__":
    main()
