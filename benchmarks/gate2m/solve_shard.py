"""Solve one shard of the 2M-gate plants (one runner's share).

Usage: python benchmarks/gate2m/solve_shard.py --shard K --shards 12 \
    [--plants 96] [--workers 4] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import time

from common import run_plant, shard_indices


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--plants", type=int, default=96)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "out"))
    a = ap.parse_args()
    idx = shard_indices(a.shard, a.shards, a.plants)
    t0 = time.monotonic()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if a.workers > 1 and len(idx) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            records = list(pool.map(run_plant, idx))
    else:
        records = [run_plant(i) for i in idx]
    wall = time.monotonic() - t0
    os.makedirs(a.out, exist_ok=True)
    payload = {"shard": a.shard, "shards": a.shards, "indices": idx,
               "started_utc": started, "wall_s": round(wall, 1),
               "rss_mb_peak_main": round(rss_mb(), 1),
               "records": records}
    path = os.path.join(a.out, f"shard-{a.shard}.json")
    json.dump(payload, open(path, "w"))
    bad = sum(len(r["problems"]) for r in records)
    print(f"shard {a.shard}: {len(idx)} plants, wall {wall:.0f}s, "
          f"problems {bad} -> {path}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
