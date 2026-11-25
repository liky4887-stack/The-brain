"""Merge shard artifacts and independently re-validate the full plan.

Usage: python benchmarks/gate2m/merge_validate.py --shards 12 \
    [--artifacts DIR] [--out DIR]

Streams plant-by-plant (bounded memory): regenerates each plant from
its seed and re-runs validate_window_plan on the rebuilt frozen plan.
Equivalence with one full-factory validation: plant cells are proven
disjoint by decompose.partition_plants (no shared SKU or line), so the
full-factory check is exactly the union of per-plant checks; the merged
multi-plant path itself is validated end-to-end by
tests/test_capstone.py.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from common import revalidate_plant


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--artifacts", default=os.path.join(
        os.path.dirname(__file__), "artifacts"))
    ap.add_argument("--out", default=os.path.dirname(__file__))
    a = ap.parse_args()

    t0 = time.monotonic()
    shards = []
    for k in range(a.shards):
        path = os.path.join(a.artifacts, f"shard-{k}.json")
        shards.append(json.load(open(path)))
    records = [r for s in shards for r in s["records"]]
    records.sort(key=lambda r: r["plant"])

    problems: list[str] = []
    tot = {"vars": 0, "rows": 0, "binaries": 0, "windows": 0,
           "assignments": 0, "changeover_minutes": 0.0,
           "backlog_units_end": 0.0}
    solve_times = []
    for r in records:
        if r.get("crash_traceback"):
            problems.append(f"plant {r['plant']}: CRASHED on runner - "
                            + r["crash_traceback"].splitlines()[-1])
            continue
        v_problems, kpis = revalidate_plant(r)
        problems.extend(f"plant {r['plant']}: {p}" for p in v_problems)
        problems.extend(f"plant {r['plant']} (runner): {p}"
                        for p in r["problems"])
        for w in r["windows"]:
            if w:
                tot["vars"] += w["vars"]
                tot["rows"] += w["rows"]
                tot["binaries"] += w["binaries"]
                tot["windows"] += 1
        tot["assignments"] += len(r["assignments"])
        tot["changeover_minutes"] += kpis["changeover_minutes"]
        tot["backlog_units_end"] += kpis["backlog_units_end"]
        solve_times.append(r["solve_s"])
    merge_s = time.monotonic() - t0

    n = len(records)
    shard_walls = [s["wall_s"] for s in shards]
    # Single-32-core-box estimate (EXTRAPOLATION, not measured): plants
    # are independent single-threaded solves; 32 workers => ceil(n/32)
    # waves; each wave bounded by the slowest plant in it. Reported with
    # the conservative bound (waves x global slowest plant).
    import math
    waves = math.ceil(n / 32)
    est_single_box_s = waves * max(solve_times) + merge_s

    result = {
        "gate": "2M-constraint / 1.4M-variable rolling plan",
        "verdict": "PASS" if (not problems and tot["rows"] >= 2_000_000
                              and tot["vars"] >= 1_400_000) else "OPEN",
        "measured": {
            "plants": n, "shards": len(shards),
            "aggregate_vars": tot["vars"], "aggregate_rows": tot["rows"],
            "aggregate_binaries": tot["binaries"],
            "windows": tot["windows"],
            "assignments_validated": tot["assignments"],
            "validation_problems": problems[:20],
            "n_validation_problems": len(problems),
            "per_plant_solve_s": {"min": round(min(solve_times), 1),
                                  "mean": round(sum(solve_times) / n, 1),
                                  "max": round(max(solve_times), 1)},
            "shard_wall_s": sorted(shard_walls, reverse=True),
            "distributed_wall_s": round(max(shard_walls) + merge_s, 1),
            "merge_validate_s": round(merge_s, 1),
            "kpis": {"changeover_minutes": round(tot["changeover_minutes"], 1),
                     "backlog_units_end": tot["backlog_units_end"]},
        },
        "extrapolated_single_32core_box": {
            "method": "ceil(plants/32) waves x slowest measured plant "
                      "+ measured merge/validation; per-core speed "
                      "assumed similar; memory-bandwidth contention NOT "
                      "measured",
            "est_wall_s": round(est_single_box_s, 1),
            "gate_budget_s": 1800,
            "fits": est_single_box_s < 1800,
        },
    }
    os.makedirs(a.out, exist_ok=True)
    out_path = os.path.join(a.out, "RESULT.json")
    json.dump(result, open(out_path, "w"), indent=1)
    print(json.dumps({k: result[k] for k in ("verdict",)}, indent=1))
    print(f"plants {n} rows {tot['rows']:,} vars {tot['vars']:,} "
          f"problems {len(problems)} merge {merge_s:.0f}s -> {out_path}")
    if problems:
        raise SystemExit(1)


def main_guarded() -> None:
    """Whatever happens, a RESULT.json exists for the publish step: the
    verdict on success, the exception on harness failure."""
    import traceback
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        os.makedirs(os.path.dirname(__file__), exist_ok=True)
        json.dump({"gate": "2M-constraint / 1.4M-variable rolling plan",
                   "verdict": "HARNESS-ERROR",
                   "error": traceback.format_exc()[-2000:]},
                  open(os.path.join(os.path.dirname(__file__),
                                    "RESULT.json"), "w"), indent=1)
        raise


if __name__ == "__main__":
    main_guarded()
