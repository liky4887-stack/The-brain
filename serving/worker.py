"""Serving worker: pull a plan job, run THE BRAIN on it, store the result.

This is where the two tracks meet: the same brain_core rolling solver
the ladder measures is what serves a submitted job. solve_rolling ends
with the independent validator's verdict inside res.problems - a served
plan carries the same honesty bar as a benchmark plant.
"""

from __future__ import annotations

import time
from datetime import datetime

from brain_core.rolling import solve_rolling
from brain_core.synthetic import FnbParams, generate_fnb_factory


def run_job(spec: dict) -> dict:
    """Execute one plan job. Spec keys (all optional but seed):
    seed, n_lines, n_skus, days, window_days, freeze_days, n_windows,
    bucket_time_s, seq_time_s, active_fraction, utilization,
    n_raw_materials, families. Returns a measured result dict - never
    raises on solver trouble; failures land in status/problems.
    """
    seed = int(spec.get("seed", 0))
    params = FnbParams(
        seed=seed,
        n_lines=int(spec.get("n_lines", 2)),
        n_skus=int(spec.get("n_skus", 20)),
        days=int(spec.get("days", 3)),
        active_fraction=float(spec.get("active_fraction", 0.9)),
        utilization=float(spec.get("utilization", 0.5)),
        n_raw_materials=int(spec.get("n_raw_materials", 4)),
        families=tuple(spec.get("families", ("DAIRY", "BAKERY"))),
        horizon_start=datetime(2026, 11, 30),
    )
    window_days = int(spec.get("window_days", 3))
    freeze_days = int(spec.get("freeze_days", 1))
    n_windows = int(spec.get("n_windows", 1))
    t0 = time.monotonic()
    plant = generate_fnb_factory(params)
    gen_s = time.monotonic() - t0
    t0 = time.monotonic()
    res = solve_rolling(plant.factory, params.horizon_start,
                        window_days=window_days, freeze_days=freeze_days,
                        n_windows=n_windows,
                        cap_min=plant.day_capacity_minutes,
                        bucket_time_s=float(spec.get("bucket_time_s", 30.0)),
                        seq_time_s=float(spec.get("seq_time_s", 5.0)),
                        seq_num_workers=1)
    solve_s = time.monotonic() - t0
    ok = not res.problems
    return {
        "ok": ok,
        "status": "validated" if ok else "problems",
        "seed": seed,
        "gen_s": round(gen_s, 2),
        "solve_s": round(solve_s, 1),
        "assignments": len(res.assignments),
        "problems": list(res.problems),
        "kpis": {k: round(v, 6) if isinstance(v, float) else v
                 for k, v in res.kpis.items()},
    }


def serve(queue, once: bool = False, poll_s: float = 2.0) -> None:
    while True:
        job = queue.claim()
        if job is None:
            if once:
                return
            time.sleep(poll_s)
            continue
        try:
            result = run_job(job["spec"])
            queue.finish(job["id"], result["ok"], result)
        except Exception as exc:  # crash lands IN the record, no silence
            queue.finish(job["id"], False,
                         {"ok": False, "status": "error",
                          "problems": [f"worker exception: {exc!r}"]})
        if once:
            return
