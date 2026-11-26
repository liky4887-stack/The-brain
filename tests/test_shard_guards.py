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


def test_duplicate_plant_is_a_verdict_problem(tmp_path):
    """De-duplication is verified, not assumed: the same plant id in
    two shards must fail the verdict loudly."""
    art = tmp_path / "art"
    art.mkdir()
    crash = {"plant": 7, "seed": 1007, "gen_s": 0.0, "solve_s": 0.0,
             "window_days": 7, "freeze_days": 3, "n_windows": 2,
             "horizon_start": "", "cap_min": 0.0,
             "problems": ["plant crashed: boom"],
             "crash_traceback": "line1\nboom",
             "kpis": {}, "windows": [], "assignments": []}
    for k in (0, 1):
        json.dump({"shard": k, "shards": 2, "wall_s": 5.0,
                   "records": [crash]},
                  open(art / f"shard-{k}.json", "w"))
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parents[1] / "benchmarks" /
             "gate2m" / "merge_validate.py"),
         "--shards", "2", "--artifacts", str(art), "--out", str(out)],
        capture_output=True, text=True)
    res = json.load(open(out / "RESULT.json"))
    assert res["verdict"] == "OPEN"
    assert any("SOLVED TWICE" in pr
               for pr in res["measured"]["validation_problems"])


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


def test_crashed_plant_gets_one_bounded_retry():
    import solve_shard
    calls = []

    def flaky(i):
        calls.append(i)
        if calls.count(7) == 1:
            return {"plant": 7, "crash_traceback": "boom",
                    "problems": ["plant crashed"], "kpis": {},
                    "windows": [], "assignments": []}
        return {"plant": i, "problems": [], "kpis": {},
                "windows": [], "assignments": []}

    records, stopped = solve_shard.execute(
        [5, 6, 7], workers=1, t0=0.0, wall_guard_s=1e9,
        mem_guard_mb=1e18, runner=flaky,
        clock=_FrozenClock(), child_rss=lambda: 0.0)
    assert stopped is None
    by_plant = {r["plant"]: r for r in records}
    assert by_plant[7].get("retried") == 1
    assert "crash_traceback" not in by_plant[7]
    assert calls.count(7) == 2  # exactly one retry, bounded


def test_retry_that_crashes_again_is_recorded():
    import solve_shard

    def always_crashes(i):
        return {"plant": i, "crash_traceback": "boom",
                "problems": ["plant crashed"], "kpis": {},
                "windows": [], "assignments": []}

    records, _ = solve_shard.execute(
        [3], workers=1, t0=0.0, wall_guard_s=1e9, mem_guard_mb=1e18,
        runner=always_crashes, clock=_FrozenClock(),
        child_rss=lambda: 0.0)
    assert records[0]["retry_also_crashed"] is True


def test_checkpoint_called_each_wave():
    import solve_shard
    seen = []

    def ok(i):
        return {"plant": i, "problems": [], "kpis": {},
                "windows": [], "assignments": []}

    solve_shard.execute([1, 2, 3], workers=1, t0=0.0,
                        wall_guard_s=1e9, mem_guard_mb=1e18, runner=ok,
                        clock=_FrozenClock(), child_rss=lambda: 0.0,
                        checkpoint=lambda recs: seen.append(sorted(recs)))
    assert seen == [[1], [1, 2], [1, 2, 3]]


class _FrozenClock:
    def __call__(self):
        return 0.0
