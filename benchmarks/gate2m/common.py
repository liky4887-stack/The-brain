"""Shared harness for the 2M-constraint gate attempt (Stage 4 capstone).

The gate instance: N_PLANTS independent Makkook-scale plants (17 lines x
4001 SKUs each, per-plant seed), each planned over 2 rolling 7-day
windows (freeze 3) - the same shape as tests/test_capstone.py. Plant
cells are proven independent by decompose.partition_plants, so a
shared-nothing split (one shard per runner, no communication during
solves) is exact, not an approximation: the merged plan is the
concatenation of cell plans, and the independent validator checks it
from records + returned assignments only.

Every number here is measured: per-plant generation/solve wall times,
per-window bucket model sizes (vars/rows/binaries from the built MIP),
validation outcomes. The only extrapolation anywhere is the single
32-core-box wall estimate in merge_validate, and it is labelled as such.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "packages", "brain-core"))

from brain_core.rolling import solve_rolling
from brain_core.rolling.two_level import (LotAssignment, WindowPlan,
                                          validate_window_plan)
from brain_core.synthetic import FnbParams, generate_fnb_factory

BASE_SEED = 1000
N_PLANTS = 96          # aggregate rows target: 96 x ~24k = ~2.3M
WINDOW_DAYS = 7
FREEZE_DAYS = 3
N_WINDOWS = 2
BUCKET_TIME_S = 30.0
SEQ_TIME_S = 10.0


def plant_params(i: int) -> FnbParams:
    return FnbParams(seed=BASE_SEED + i, days=14)


def plant_data_hash(i: int) -> str:
    """Provenance anchor for plant i: sha256 of its generator params.
    The generator is deterministic, so the params fully determine the
    plant; the merge re-derives this hash for every record's index and
    rejects mismatches (a record generated for the wrong index cannot
    masquerade as the right one)."""
    import hashlib
    p = plant_params(i)
    return hashlib.sha256(
        f"fnb|seed={p.seed}|days={p.days}".encode()).hexdigest()[:16]


def shard_indices(shard: int, shards: int, plants: int) -> list[int]:
    """Contiguous block partition of range(plants); deterministic."""
    assert 0 <= shard < shards
    lo = plants * shard // shards
    hi = plants * (shard + 1) // shards
    return list(range(lo, hi))


def run_plant(i: int, window_days: int = WINDOW_DAYS,
              freeze_days: int = FREEZE_DAYS, n_windows: int = N_WINDOWS,
              bucket_time_s: float = BUCKET_TIME_S,
              seq_time_s: float = SEQ_TIME_S,
              params: FnbParams | None = None,
              seq_num_workers: int | None = None) -> dict:
    """Generate plant i and plan it with the production rolling path.

    solve_rolling ends by running the SAME independent validator on the
    full frozen plan, so res.problems already carries that verdict; the
    merge step re-runs the validator from this record alone."""
    t0 = time.monotonic()
    p = generate_fnb_factory(params or plant_params(i))
    gen_s = time.monotonic() - t0
    t0 = time.monotonic()
    res = solve_rolling(p.factory, p.params.horizon_start,
                        window_days=window_days, freeze_days=freeze_days,
                        n_windows=n_windows,
                        cap_min=p.day_capacity_minutes,
                        bucket_time_s=bucket_time_s, seq_time_s=seq_time_s,
                        seq_num_workers=seq_num_workers)
    solve_s = time.monotonic() - t0
    return {
        "plant": i, "seed": p.params.seed, "gen_s": round(gen_s, 2),
        "solve_s": round(solve_s, 1),
        "window_days": window_days, "freeze_days": freeze_days,
        "n_windows": n_windows,
        "horizon_start": p.params.horizon_start.isoformat(),
        "cap_min": p.day_capacity_minutes,
        "problems": res.problems,
        "kpis": {k: res.kpis[k] for k in
                 ("changeover_minutes", "backlog_units_end", "setups")},
        "windows": [
            {"vars": w.bucket.n_vars, "rows": w.bucket.n_rows,
             "binaries": w.bucket.n_binaries, "status": w.bucket.status,
             "gap": w.bucket.mip_gap} if w.bucket else None
            for w in res.windows],
        "assignments": [asdict(a) for a in res.assignments],
    }


def revalidate_plant(rec: dict, params: FnbParams | None = None
                     ) -> tuple[list[str], dict]:
    """Re-run the independent validator from the record alone: regenerate
    the plant from its seed, rebuild the frozen WindowPlan from the
    returned assignments, recompute every KPI. Never trusts the shard's
    own verdict."""
    p = generate_fnb_factory(params or plant_params(rec["plant"]))
    assignments = [LotAssignment(**a) for a in rec["assignments"]]
    total_days = rec["n_windows"] * rec["freeze_days"]
    from datetime import datetime
    full = WindowPlan(datetime.fromisoformat(rec["horizon_start"]),
                      total_days, assignments, None, "frozen")
    return validate_window_plan(p.factory, full, rec["cap_min"])
