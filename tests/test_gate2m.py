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


def test_merge_rejects_mixed_shas_and_bad_hashes(tmp_path):
    """Provenance enforcement: a shard from a different commit, or a
    record whose data hash does not match the generator for its
    index, must turn the verdict OPEN with a named problem."""
    import json
    import subprocess
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "benchmarks" / "gate2m"))
    from common import plant_data_hash

    def shard(k, sha, plants):
        return {"shard": k, "shards": 2, "plant_offset": 0,
                "indices": plants, "started_utc": "", "wall_s": 1.0,
                "sha": sha, "env": {"python": "3.11"},
                "records": [{"plant": i, "seed": 1000 + i,
                             "gen_s": 0.1, "solve_s": 1.0,
                             "window_days": 7, "freeze_days": 3,
                             "n_windows": 2,
                             "horizon_start": "2026-11-30T00:00:00",
                             "cap_min": 1440.0, "problems": [],
                             "data_hash": plant_data_hash(i),
                             "kpis": {"changeover_minutes": 0.0,
                                      "backlog_units_end": 0.0,
                                      "setups": 1},
                             "windows": [{"vars": 1500000,
                                          "rows": 2100000,
                                          "binaries": 50000,
                                          "status": "optimal",
                                          "gap": 0.0}],
                             "assignments": []}
                            for i in plants]}
    d = tmp_path
    (d / "shard-0.json").write_text(
        json.dumps(shard(0, "aaa", [0, 1])))
    bad = shard(1, "bbb", [2, 3])
    bad["records"][0]["data_hash"] = "forged"
    (d / "shard-1.json").write_text(json.dumps(bad))
    r = subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parents[1] / "benchmarks"
             / "gate2m" / "merge_validate.py"),
         "--artifacts", str(d), "--shards", "2", "--plants", "4",
         "--plant-offset", "0", "--out", str(d / "merged")],
        capture_output=True, text=True)
    res = json.loads((d / "merged" / "RESULT.json").read_text())
    assert res["verdict"] == "OPEN"
    text = json.dumps(res)
    assert "MIXED SHAs" in text and "data hash mismatch" in text, text
