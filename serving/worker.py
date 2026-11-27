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

# Hard input bounds: a spec outside them is refused at the door (API
# 400) and by the worker, before any model is built. They stop resource
# bombs (n_skus=10**7) and nonsense (days=-1); they are NOT the solver
# contract (window_days >= freeze_days is still solve_rolling's check).
SPEC_LIMITS = {
    "n_lines": (1, 64), "n_skus": (1, 2000), "days": (1, 120),
    "window_days": (1, 60), "freeze_days": (0, 60),
    "n_windows": (1, 52), "bucket_time_s": (0.1, 3600.0),
    "seq_time_s": (0.1, 3600.0), "active_fraction": (0.0, 1.0),
    "utilization": (0.0, 2.0), "n_raw_materials": (0, 200),
}

SPEC_KEYS = set(SPEC_LIMITS) | {"seed", "families"}


def unknown_keys(spec: dict) -> list[str]:
    """Keys the worker does not read. A misspelt key ("n_sku") used to be
    ignored silently and the default solved instead: a value written in the
    wrong place. Default is WARN (job still runs, the warning travels in the
    API reply and the result); SPEC_STRICT_KEYS=1 refuses it (400). Warn
    first so existing clients that send extra keys keep working."""
    return sorted(set(spec) - SPEC_KEYS) if isinstance(spec, dict) else []


def strict_keys() -> bool:
    import os
    return os.environ.get("SPEC_STRICT_KEYS", "") in ("1", "true", "yes")


def validate_spec(spec: dict) -> list[str]:
    """Every out-of-bounds or non-numeric field, by name (plus unknown
    keys when SPEC_STRICT_KEYS is set). The numeric bounds are the outside
    reviewer's choice, not a user decision."""
    out = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    unknown = unknown_keys(spec)
    if unknown and strict_keys():
        out.append(f"unknown key(s) {unknown}; accepted: "
                   f"{sorted(SPEC_KEYS)}")
    fam = spec.get("families")
    if fam is not None and not (isinstance(fam, list) and fam and
                                all(isinstance(x, str) for x in fam)):
        out.append(f"families: {fam!r} is not a list of names")
    try:
        int(spec.get("seed", 0))
    except (TypeError, ValueError):
        out.append(f"seed: {spec.get('seed')!r} is not an integer")
    for k, (lo, hi) in SPEC_LIMITS.items():
        if k not in spec:
            continue
        try:
            v = float(spec[k])
        except (TypeError, ValueError):
            out.append(f"{k}: {spec[k]!r} is not a number")
            continue
        if not (lo <= v <= hi):        # NaN fails too
            out.append(f"{k}: {spec[k]!r} outside [{lo}, {hi}]")
    return out


def run_job(spec: dict) -> dict:
    """Execute one plan job. Spec keys (all optional but seed):
    seed, n_lines, n_skus, days, window_days, freeze_days, n_windows,
    bucket_time_s, seq_time_s, active_fraction, utilization,
    n_raw_materials, families. Returns a measured result dict - never
    raises on solver trouble; failures land in status/problems.
    """
    bad = validate_spec(spec)
    if bad:
        return {"ok": False, "status": "rejected",
                "seed": spec.get("seed") if isinstance(spec, dict)
                else None, "problems": [f"invalid spec: {p}"
                                        for p in bad]}
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
        "warnings": ([f"unknown spec key(s) ignored: {unknown_keys(spec)}"]
                     if unknown_keys(spec) else []),
    }


def _run_guarded(spec: dict, job_timeout_s: float) -> dict:
    """run_job in a watchdog child: a hung or crashing solve becomes
    a failed record with the reason; the worker loop survives."""
    from brain_core.guards.watchdog import run_step
    r = run_step("plan job", run_job, (spec,), timeout_s=job_timeout_s)
    if r.status == "ok":
        return r.value
    return {"ok": False, "status": r.status,
            "problems": [f"worker {r.status}: {r.detail}"],
            "solve_s": round(r.wall_s, 1)}


def serve(queue, once: bool = False, poll_s: float = 2.0,
          job_timeout_s: float | None = None,
          stale_after_s: float | None = None) -> None:
    """job_timeout_s: run each job in a watchdog child with this hard
    limit (None keeps the old in-process call). stale_after_s: before
    each claim, close jobs another worker left 'running' that long."""
    while True:
        if stale_after_s is not None:
            queue.fail_stale(stale_after_s)
        job = queue.claim()
        if job is None:
            if once:
                return
            time.sleep(poll_s)
            continue
        try:
            if job_timeout_s is not None:
                result = _run_guarded(job["spec"], job_timeout_s)
            else:
                result = run_job(job["spec"])
            queue.finish(job["id"], result["ok"], result)
        except Exception as exc:  # crash lands IN the record, no silence
            queue.finish(job["id"], False,
                         {"ok": False, "status": "error",
                          "problems": [f"worker exception: {exc!r}"]})
        if once:
            return
