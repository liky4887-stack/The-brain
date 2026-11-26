"""Gate-2M harness units: sharding, per-plant record, revalidation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "benchmarks" / "gate2m"))

from common import plant_params, revalidate_plant, run_plant, shard_indices
from brain_core.synthetic import FnbParams


def test_shard_indices_cover_without_overlap():
    idx = [i for k in range(12) for i in shard_indices(k, 12, 96)]
    assert idx == list(range(96))
    idx = [i for k in range(5) for i in shard_indices(k, 5, 7)]
    assert idx == list(range(7))


def test_run_plant_and_revalidate_tiny():
    params = FnbParams(seed=7, n_lines=3, n_skus=40, days=4,
                       active_fraction=0.9, utilization=0.5,
                       n_raw_materials=5,
                       families=("DAIRY", "BAKERY", "SAUCE"))
    rec = run_plant(0, window_days=4, freeze_days=2, n_windows=2,
                    bucket_time_s=10, seq_time_s=5, params=params)
    assert rec["problems"] == [], rec["problems"][:3]
    assert all(w["vars"] > 0 and w["rows"] > 0 for w in rec["windows"])
    problems, kpis = revalidate_plant(rec, params=params)
    assert problems == [], problems[:3]
    assert kpis["assignments"] == len(rec["assignments"])


def test_revalidate_detects_a_broken_assignment():
    params = FnbParams(seed=7, n_lines=3, n_skus=40, days=4,
                       active_fraction=0.9, utilization=0.5,
                       n_raw_materials=5,
                       families=("DAIRY", "BAKERY", "SAUCE"))
    rec = run_plant(0, window_days=4, freeze_days=2, n_windows=1,
                    bucket_time_s=10, seq_time_s=5, params=params)
    assert rec["assignments"]
    rec["assignments"][0]["qty"] *= 100.0  # break line capacity
    problems, _ = revalidate_plant(rec, params=params)
    assert problems


def test_merge_completeness_check_flags_missing_plant(tmp_path):
    """A partial shard (6 of 8 records, or a plant lost any other way)
    must turn the verdict OPEN with an explicit NO RECORD problem -
    the plant count may never silently shrink (outside-review item)."""
    import json
    import subprocess
    import sys as _sys
    env = {"python": "3.11", "ortools": "9.12.4544"}
    for k in range(2):
        plants = [k * 4 + j for j in range(4)]
        if k == 1:
            plants = plants[:3]  # plant 7 lost: partial shard
        recs = [{"plant": i, "seed": 1000 + i, "gen_s": 0.1,
                 "solve_s": 1.0, "window_days": 7, "freeze_days": 3,
                 "n_windows": 2, "horizon_start": "2026-11-30T00:00:00",
                 "cap_min": 1440.0, "problems": [],
                 "kpis": {"changeover_minutes": 0.0,
                          "backlog_units_end": 0.0, "setups": 1},
                 "windows": [{"vars": 800000, "rows": 1100000,
                              "binaries": 50000, "status": "optimal",
                              "gap": 0.0}],
                 "assignments": []} for i in plants]
        json.dump({"shard": k, "wall_s": 5.0, "env": env,
                   "partial": k == 1, "records": recs},
                  open(tmp_path / f"shard-{k}.json", "w"))
    out = tmp_path / "out"
    r = subprocess.run(
        [_sys.executable, "merge_validate.py", "--shards", "2",
         "--plants", "8", "--artifacts", str(tmp_path),
         "--out", str(out)],
        cwd=tmp_path.parents[0] and
        str((__import__("pathlib").Path(__file__).resolve().parents[1]
             / "benchmarks" / "gate2m")),
        capture_output=True, text=True)
    # merge exits nonzero on OPEN by design; the RESULT is still
    # published (the workflow's publish step runs if: always())
    assert r.returncode in (0, 1), r.stderr
    res = json.load(open(out / "RESULT.json"))
    assert res["verdict"] == "OPEN"
    assert any("plant 7: NO RECORD" in p
               for p in res["measured"]["validation_problems"])
