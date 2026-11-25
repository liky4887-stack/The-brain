"""Stage 4 capstone: time x plant decomposition at scale.

The roadmap gate (2M constraints / 1.4M variables in 30 min on one
32-core server) CANNOT be proven on this 2-core box: the Makkook-scale
bucket MILP is 60,725 vars / 21,140 rows (measured), so the gate's
target instance is ~30-100x beyond this hardware. Honest status:
OPEN, with the combined rolling+decomposed path measured at the
largest scale that fits here.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.decompose import solve_decomposed
from brain_core.rolling import solve_rolling
from brain_core.synthetic import FnbParams, generate_fnb_factory


def _decomposed_window(factory, ws, window_days, cap_min,
                       chg_allowance, bucket_time_s, seq_time_s,
                       **kw):
    return solve_decomposed(factory, ws, window_days, cap_min,
                            chg_allowance=chg_allowance,
                            bucket_time_s=bucket_time_s,
                            seq_time_s=seq_time_s, **kw).plan


def test_rolling_accepts_a_decomposed_window_solver_small():
    params = FnbParams(seed=0, n_lines=3, n_skus=40, days=4,
                       active_fraction=0.9, utilization=0.5,
                       n_raw_materials=5,
                       families=("DAIRY", "BAKERY", "SAUCE"))
    p = generate_fnb_factory(params)
    res = solve_rolling(p.factory, p.params.horizon_start,
                        window_days=4, freeze_days=2, n_windows=2,
                        cap_min=p.day_capacity_minutes,
                        bucket_time_s=10, seq_time_s=5,
                        window_solver=_decomposed_window)
    assert res.problems == [], res.problems[:3]


@pytest.mark.benchmark
def test_capstone_rolling_decomposed_two_plants():
    """2 plants x (6 lines x 400 SKUs), 2 rolling windows of 7 days
    (freeze 3): the combined time+plant path, validated end to end."""
    import json
    import time
    from tests.helpers_two_plant import two_plant_factory
    params = FnbParams(n_lines=6, n_skus=400, days=14,
                       active_fraction=0.25, utilization=0.65,
                       n_raw_materials=30, seed=1000)
    p = generate_fnb_factory(params)
    f2 = two_plant_factory(p.factory)
    t0 = time.monotonic()
    res = solve_rolling(f2, p.params.horizon_start,
                        window_days=7, freeze_days=3, n_windows=2,
                        cap_min=p.day_capacity_minutes,
                        bucket_time_s=30, seq_time_s=10,
                        window_solver=_decomposed_window)
    wall = time.monotonic() - t0
    ev = {"gate": "stage4_capstone_rolling_decomposed",
          "scale": "2 plants x (6 lines x 400 SKUs), 2 x 7d windows",
          "wall_s": round(wall, 1), "problems": res.problems[:5],
          "kpis": {k: res.kpis[k] for k in
                   ("changeover_minutes", "backlog_units_end")}}
    json.dump(ev, open("/tmp/gate4-capstone.json", "w"), indent=1)
    print(ev)
    assert res.problems == []
