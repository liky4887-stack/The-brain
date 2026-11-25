"""Overload protection: shards degrade gracefully (wall/memory guards,
streaming merge), never die silently."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "benchmarks" / "gate2m"))

from solve_shard import execute


def fake_rec(i):
    return {"plant": i, "seed": 1000 + i, "gen_s": 0.1, "solve_s": 1.0,
            "window_days": 7, "freeze_days": 3, "n_windows": 2,
            "horizon_start": "", "cap_min": 100.0, "problems": [],
            "kpis": {}, "windows": [], "assignments": []}


def test_wall_guard_stops_starting_and_records_honestly():
    clock_t = [0.0]

    def clock():
        clock_t[0] += 100.0   # each check jumps 100 s
        return clock_t[0]

    records, stopped = execute([0, 1, 2, 3], workers=1, t0=0.0,
                               wall_guard_s=250.0, mem_guard_mb=1e9,
                               runner=fake_rec, clock=clock,
                               child_rss=lambda: 0.0)
    assert stopped is not None and "wall guard" in stopped
    done = [r for r in records if not r["problems"]]
    skipped = [r for r in records if r["problems"]]
    assert done and skipped                      # graceful degradation
    assert all("not attempted" in r["problems"][0] for r in skipped)
    assert [r["plant"] for r in records] == [0, 1, 2, 3]  # order kept


def test_memory_guard_stops_starting():
    records, stopped = execute([0, 1, 2, 3], workers=1, t0=0.0,
                               wall_guard_s=1e9, mem_guard_mb=100.0,
                               runner=fake_rec,
                               clock=lambda: 0.0,
                               child_rss=lambda: 200.0)  # over budget
    assert "memory guard" in stopped
    assert len([r for r in records if not r["problems"]]) == 1


def test_no_guard_all_done():
    records, stopped = execute([0, 1], workers=1, t0=0.0,
                               wall_guard_s=1e9, mem_guard_mb=1e9,
                               runner=fake_rec, clock=lambda: 0.0,
                               child_rss=lambda: 0.0)
    assert stopped is None
    assert all(not r["problems"] for r in records)


def test_streaming_merge_matches_expectations(tmp_path):
    """Two shard artifacts (one healthy-ish, one crash) + one missing:
    the merge must still publish a RESULT with both problems recorded
    and only the real windows counted."""
    art = tmp_path / "art"
    art.mkdir()
    crash = {"plant": 1, "seed": 1001, "gen_s": 0.0, "solve_s": 0.0,
             "window_days": 7, "freeze_days": 3, "n_windows": 2,
             "horizon_start": "", "cap_min": 0.0,
             "problems": ["plant crashed: boom"],
             "crash_traceback": "line1\nline2 boom",
             "kpis": {}, "windows": [], "assignments": []}
    for k, recs in ((0, []), (1, [crash])):
        json.dump({"shard": k, "shards": 3, "wall_s": 5.0,
                   "records": recs},
                  open(art / f"shard-{k}.json", "w"))
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parents[1] / "benchmarks" /
             "gate2m" / "merge_validate.py"),
         "--shards", "3", "--artifacts", str(art), "--out", str(out)],
        capture_output=True, text=True)
    assert (out / "RESULT.json").exists()     # always publishes
    res = json.load(open(out / "RESULT.json"))
    assert res["verdict"] == "OPEN"
    assert res["shards_expected"] == 3 and res["shards_missing"] == [2]
    probs = " ".join(res["measured"]["validation_problems"])
    assert "artifact missing" in probs and "CRASHED" in probs
    assert res["measured"]["plants"] == 1     # only real records count
