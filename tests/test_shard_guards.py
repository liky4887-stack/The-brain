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


def fake_slow_rec(i):
    import time
    time.sleep(30.0)   # would blow any sub-second budget
    return fake_rec(i)


def test_wave_hard_bound_terminates_and_records_honestly():
    """A wave that overruns the remaining job budget is TERMINATED;
    its plants are recorded not-attempted, the step returns in time
    for the upload step to run (the shard-194 lesson)."""
    import time
    t0 = time.monotonic()
    records, stopped = execute([0, 1], workers=1, t0=t0,
                               wall_guard_s=1e9, mem_guard_mb=1e9,
                               runner=fake_slow_rec,
                               job_budget_s=2.0, upload_margin_s=1.5)
    elapsed = time.monotonic() - t0
    assert stopped is not None and "hard bound" in stopped
    assert elapsed < 15.0   # killed, not the runner's 30s
    assert all("not attempted" in r["problems"][0]
               for r in records)
    assert [r["plant"] for r in records] == [0, 1]


def test_job_budget_guard_stops_starting_before_budget():
    clock_t = [0.0]

    def clock():
        clock_t[0] += 100.0
        return clock_t[0]

    records, stopped = execute([0, 1, 2, 3], workers=1, t0=0.0,
                               wall_guard_s=1e9, mem_guard_mb=1e9,
                               runner=fake_rec, clock=clock,
                               child_rss=lambda: 0.0,
                               job_budget_s=350.0, upload_margin_s=100.0)
    assert stopped is not None and "job budget guard" in stopped
    assert any(r["problems"] and "not attempted" in r["problems"][0]
               for r in records)


def test_checkpoint_payload_end_to_end(tmp_path):
    """Regression (run 45852637645, all solve jobs NameError'd at the
    first checkpoint): the provenance payload uses sys.argv - call the
    REAL module-level _checkpoint so a missing import can never ship.
    """
    import json
    import types
    import sys as _sys
    from pathlib import Path
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                            / "benchmarks" / "gate2m"))
    import solve_shard

    a = types.SimpleNamespace(shard=0, shards=1, plant_offset=0,
                              plants=2)
    path = str(tmp_path / "shard-0.json")
    records = {0: {"plant": 0}, 1: {"plant": 1}}
    solve_shard._checkpoint(a, [0, 1], {"python": "3.11"},
                            "2026-11-26T00:00:00Z", path, records)
    d = json.loads(open(path).read())
    assert d["partial"] is True
    assert isinstance(d["argv"], list) and d["argv"]
    assert d["expected_range"] == [0, 2]
    assert [r["plant"] for r in d["records"]] == [0, 1]


def fake_mixed_rec(i):
    import time
    if i == 1:
        time.sleep(30.0)
    return fake_rec(i)


def test_wave_hard_bound_keeps_plants_that_finished():
    """Plant 0 finishes in ms, plant 1 overruns: only plant 1 is
    recorded not-attempted (map_async lost both)."""
    import time
    t0 = time.monotonic()
    records, stopped = execute([0, 1], workers=2, t0=t0,
                               wall_guard_s=1e9, mem_guard_mb=1e9,
                               runner=fake_mixed_rec,
                               job_budget_s=12.0, upload_margin_s=1.0)
    assert stopped is not None and "hard bound" in stopped
    assert time.monotonic() - t0 < 25.0
    assert records[0]["problems"] == []
    assert "not attempted" in records[1]["problems"][0]
