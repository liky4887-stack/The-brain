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

import traceback

from common import run_plant, shard_indices


SEQ_WORKERS = None  # set by main() before pool.map (worker init is local)


def _run_with_workers(i: int) -> dict:
    return run_plant(i, seq_num_workers=SEQ_WORKERS)


def _provenance(i: int) -> str:
    from common import plant_data_hash
    return plant_data_hash(i)


def run_plant_safe(i: int) -> dict:
    """One plant, failure-isolated: an exception or validation problems
    land IN THE RECORD so the merge step reports them with full detail
    instead of killing the shard with an opaque exit code."""
    try:
        rec = _run_with_workers(i)
        rec["data_hash"] = _provenance(i)
        return rec
    except Exception as e:
        return {"plant": i, "seed": 1000 + i, "gen_s": 0.0,
                "data_hash": _provenance(i),
                "solve_s": 0.0, "window_days": 7, "freeze_days": 3,
                "n_windows": 2, "horizon_start": "", "cap_min": 0.0,
                "problems": [f"plant crashed: {type(e).__name__}: {e}"],
                "crash_traceback": traceback.format_exc()[-1500:],
                "kpis": {}, "windows": [], "assignments": []}


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def child_rss_mb() -> float:
    """Peak RSS of the largest TERMINATED child (Linux ru_maxrss):
    the overload signal for worker processes."""
    return resource.getrusage(
        resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0


def not_attempted_record(i: int, guard: str) -> dict:
    """A plant the guard stopped us from STARTING. Honest status: not
    a crash, not a solve failure - the shard degraded gracefully
    instead of being OOM-killed or hitting the job timeout."""
    return {"plant": i, "seed": 1000 + i, "gen_s": 0.0, "solve_s": 0.0,
            "window_days": 7, "freeze_days": 3, "n_windows": 2,
            "horizon_start": "", "cap_min": 0.0,
            "problems": [f"not attempted: {guard} stopped the shard "
                         f"before this plant started"],
            "kpis": {}, "windows": [], "assignments": []}


def execute(idx, workers, t0, wall_guard_s, mem_guard_mb,
            runner=run_plant_safe, clock=time.monotonic,
            child_rss=child_rss_mb, checkpoint=None,
            job_budget_s=None, upload_margin_s=300.0):
    """Wave-based submission with overload guards. Never let a shard be
    killed mid-plant by the job timeout or the OOM killer: stop
    STARTING new plants past the wall guard or when the children peak
    past the memory guard, and record unstarted plants honestly.

    job_budget_s: HARD backstop aligned with the CI job timeout. Each
    wave is submitted with timeout = budget - upload_margin - elapsed;
    on expiry the worker pool is TERMINATED (real SIGTERM, unlike
    concurrent.futures) and the unfinished wave plants are recorded
    as not-attempted. The solve step then exits normally, so the
    upload step (if: always()) always runs and no finished plant's
    record is lost (review: a wave started near the limit used to
    carry the whole job past the timeout and lose the shard)."""
    records: dict[int, dict] = {}
    pending = list(idx)
    stopped_by = None
    hard = job_budget_s is not None
    pool = None
    mp = None
    if hard:
        import multiprocessing as mp
        pool = mp.Pool(max(1, workers))
    elif workers > 1 and len(pending) > 1:
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(max_workers=workers)
    try:
        while pending:
            if clock() - t0 > wall_guard_s:
                stopped_by = f"wall guard ({wall_guard_s:.0f}s)"
                break
            remaining = None
            if hard:
                remaining = job_budget_s - upload_margin_s - \
                    (clock() - t0)
                if remaining <= 0:
                    stopped_by = (f"job budget guard "
                                  f"({job_budget_s:.0f}s budget - "
                                  f"{upload_margin_s:.0f}s upload "
                                  "margin)")
                    break
            wave, pending = pending[:max(1, workers)], pending[max(1, workers):]
            if hard:
                async_res = pool.map_async(runner, wave)
                try:
                    got = async_res.get(timeout=max(1.0, remaining))
                except mp.TimeoutError:
                    stopped_by = ("wave hard bound: wave exceeded the "
                                  "remaining job budget; pool "
                                  "terminated, unfinished plants "
                                  "recorded as not attempted")
                    for i in wave:
                        records[i] = not_attempted_record(
                            i, stopped_by)
                    break   # remaining pending plants are filled by
                            # the stopped_by loop below
            elif pool is not None:
                got = list(pool.map(runner, wave))
            else:
                got = [runner(i) for i in wave]
            for rec in got:
                records[rec["plant"]] = rec
            if checkpoint is not None:
                checkpoint(records)   # resumable: latest state on disk
            if pending and child_rss() > mem_guard_mb:
                stopped_by = (f"memory guard (children peak "
                              f"{child_rss():.0f} MB > {mem_guard_mb:.0f} MB)")
                break
    finally:
        if pool is not None:
            if hard:
                pool.terminate()   # no orphan workers, no join wait
                pool.join()
            else:
                pool.shutdown()
    if stopped_by:
        for i in pending:
            records[i] = not_attempted_record(i, stopped_by)
    # Bounded retry (review item): a plant that CRASHED gets exactly
    # one retry before its failure is recorded. Retried plants are
    # stamped so the merge can see what was healed vs clean first
    # try. Not-attempted (guard-stopped) plants are NOT retried -
    # the guard's reason still holds.
    if clock() - t0 <= wall_guard_s:
        crashed = [i for i in idx
                   if records[i].get("crash_traceback")]
        for i in crashed:
            rec2 = runner(i)
            if not rec2.get("crash_traceback"):
                rec2["retried"] = 1
                records[i] = rec2
            else:
                records[i]["retry_also_crashed"] = True
    return [records[i] for i in idx], stopped_by


def env_stamp(workers: int, seq_workers) -> dict:
    """Reproducibility provenance: the exact environment the solves ran
    in. The merge REQUIRES all shards to agree - a version mismatch
    across shards is silent environment drift and fails the verdict."""
    import importlib.metadata as md
    import sys
    def v(pkg):
        try:
            return md.version(pkg)
        except md.PackageNotFoundError:
            return "absent"
    return {"python": sys.version.split()[0],
            "ortools": v("ortools"), "scipy": v("scipy"),
            "numpy": v("numpy"), "highspy": v("highspy"),
            "workers": workers, "seq_workers": seq_workers}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--plants", type=int, default=96)
    ap.add_argument("--plant-offset", type=int, required=True,
                    help="first plant index of this block - REQUIRED: "
                         "a default of 0 once masked a missing flag "
                         "and a whole block re-solved block A's range. "
                         "Seeds derive from the plant index, so "
                         "blocks are disjoint ranges of the same "
                         "generator - SUPERVISOR.md layer 2)")
    ap.add_argument("--dry-run", action="store_true",
                    help="canary: print the resolved indices, range "
                         "and sample data hashes; solve nothing")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "out"))
    ap.add_argument("--seq-workers", type=int, default=None,
                    help="CP-SAT workers per day-sequencing solve; set 1 "
                         "when --workers already saturates the cores")
    ap.add_argument("--job-budget-s", type=float, default=6000.0,
                    help="HARD backstop matching the CI job timeout "
                         "(100 min): waves are killed at budget minus "
                         "--upload-margin-s so the upload step always "
                         "runs")
    ap.add_argument("--upload-margin-s", type=float, default=300.0,
                    help="reserved upload/merge margin inside the job "
                         "budget")
    ap.add_argument("--wall-guard-s", type=float, default=5400.0,
                    help="stop STARTING new plants past this wall "
                         "(job timeout is 100 min; the 90-min default "
                         "leaves merge margin). Jobs are NEVER rerun; "
                         "partials upload and the merge completeness "
                         "check owns the verdict")
    ap.add_argument("--mem-guard-mb", type=float, default=12288.0,
                    help="stop STARTING new plants when the children "
                         "peak RSS passes this (runner has 16 GB)")
    a = ap.parse_args()
    global SEQ_WORKERS
    SEQ_WORKERS = a.seq_workers
    idx = [a.plant_offset + i
           for i in shard_indices(a.shard, a.shards, a.plants)]
    # preflight: the resolved indices must sit inside the block range
    assert a.plants > 0 and idx, "empty shard: misconfigured range"
    assert all(a.plant_offset <= i < a.plant_offset + a.plants
               for i in idx), \
        f"indices outside block [{a.plant_offset}, " \
        f"{a.plant_offset + a.plants}): {idx[:3]}..."
    if a.dry_run:
        print(json.dumps({"shard": a.shard, "indices": idx,
                          "range": [a.plant_offset,
                                    a.plant_offset + a.plants],
                          "sample_hashes": {str(i): _provenance(i)
                                            for i in idx[:2]}},
                         indent=1))
        return
    t0 = time.monotonic()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"shard-{a.shard}.json")

    env = env_stamp(a.workers, a.seq_workers)

    def _checkpoint(records):
        # compact separators (artifact quota); atomic-ish via tmp+rename
        # env included so a partial upload does not fake "drift" in the
        # merge's cross-shard stamp check
        payload = {"shard": a.shard, "shards": a.shards,
                   "plant_offset": a.plant_offset, "indices": idx,
                   "started_utc": started, "partial": True,
                   "sha": os.environ.get("GITHUB_SHA", "local"),
                   "argv": sys.argv,
                   "expected_range": [a.plant_offset,
                                      a.plant_offset + a.plants],
                   "env": env,
                   "records": [records[i] for i in idx if i in records]}
        tmp = path + ".tmp"
        json.dump(payload, open(tmp, "w"), separators=(",", ":"))
        os.replace(tmp, path)

    records, stopped_by = execute(idx, a.workers, t0, a.wall_guard_s,
                                  a.mem_guard_mb,
                                  job_budget_s=a.job_budget_s,
                                  upload_margin_s=a.upload_margin_s,
                                  checkpoint=_checkpoint)
    wall = time.monotonic() - t0
    payload = {"shard": a.shard, "shards": a.shards,
               "plant_offset": a.plant_offset, "indices": idx,
               "started_utc": started, "wall_s": round(wall, 1),
               "sha": os.environ.get("GITHUB_SHA", "local"),
               "argv": sys.argv,
               "expected_range": [a.plant_offset,
                                  a.plant_offset + a.plants],
               "rss_mb_peak_main": round(rss_mb(), 1),
               "env": env,
               "guards": {"wall_guard_s": a.wall_guard_s,
                          "mem_guard_mb": a.mem_guard_mb,
                          "stopped_by": stopped_by},
               "records": records}
    # compact separators: shard artifacts accumulate against the
    # account's 500 MB artifact-storage quota (free tier) across runs
    # and shards; whitespace is pure overhead here
    json.dump(payload, open(path, "w"), separators=(",", ":"))
    bad = sum(len(r["problems"]) for r in records)
    # The artifact always uploads; merge_validate owns the verdict, so a
    # failing plant is reported with its evidence, not as an opaque
    # job failure that needs signed-in log access to diagnose.
    print(f"shard {a.shard}: {len(idx)} plants, wall {wall:.0f}s, "
          f"problems {bad} -> {path}")


if __name__ == "__main__":
    main()
