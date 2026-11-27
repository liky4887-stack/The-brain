"""Physical lower BOUND on lateness for a calib instance (a bound, not a
target; no solver). Per plant and SKU: every day, produce as much as
the SKU's eligible lines could make at RAW capacity (cap minutes, no
changeover, no setup, no sharing with other SKUs), as EARLY as possible
(stock may be built ahead), but never more than the total window demand. Any real plan has less capacity
(changeovers, shared lines), so its lateness cannot be lower. The plan is
infeasible by construction; only the validator's lateness KPI is read,
so the number is in the SAME accounting as the model rows.
env: MS_CLASS (calib3), MS_N (4), MS_SEED, MS_CLASS_JSON.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))
import monolith_scaling as ms  # noqa: E402
from brain_core.guards.independent_data import (raw_due_day,  # noqa: E402
                                                raw_sku_data)
from brain_core.rolling.coupled import validate_coupled_plan  # noqa: E402
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402


def bound(cls="calib3", n=4, seed=0, c_over=None):
    c = dict(ms.CLASSES[cls])
    c.update(c_over or {})
    ps = [generate_fnb_factory(FnbParams(
        seed=101 * (i + 1) + seed, n_lines=3, n_skus=c["n_skus"],
        days=c["days"], active_fraction=0.9, utilization=c["util"],
        n_raw_materials=6, families=("DAIRY", "BAKERY")))
        for i in range(n)]
    hs, cap, days = ps[0].params.horizon_start, ps[0].day_capacity_minutes, \
        c["days"]
    fs = [p.factory for p in ps]
    qtys, own_late, short_end = [], 0.0, 0.0
    plant_short_min_days, plant_max_short_min = 0.0, 0.0
    for f in fs:
        sku = raw_sku_data(f)
        dem = {}
        for d in f.demands:
            t = raw_due_day(d.due, hs)
            if 0 <= t < days:
                dem.setdefault(d.item, [0.0] * days)[t] += d.quantity
        # plant level (SKUs share the lines): minutes of work due by day
        # t must fit in the raw minutes of days 0..t on all lines
        n_ln = len(f.resources)
        for t in range(days):
            need = sum(sum(ds[:t + 1]) / sku[s][0] for s, ds in dem.items())
            sh = max(0.0, need - n_ln * cap * (t + 1))
            plant_short_min_days += sh
            plant_max_short_min = max(plant_max_short_min, sh)
        q = {}
        for s, ds in dem.items():
            rate, lines, _ = sku[s]
            per_day = len(lines) * cap * rate        # raw, all lines
            cum, made = 0.0, 0.0
            total_d = sum(ds)
            for t in range(days):
                cum += ds[t]
                # as EARLY as possible (stock may be built ahead of the
                # due day): the most any plan can have made by day t
                x = min(per_day, total_d - made)
                if x > 1e-9:
                    q[(s, t, lines[0])] = x
                made += x
                own_late += max(0.0, cum - made)     # open units at day t
            short_end += max(0.0, cum - made)
        qtys.append(q)
    _, k = validate_coupled_plan(fs, qtys, hs, days, cap)
    return {"class": cls, "plants": n, "seed": seed,
            "bound_late_unit_days_validator_accounting":
                k["late_unit_days"],
            "bound_open_unit_days_sum_over_days": round(own_late, 3),
            "bound_backlog_units_end": round(short_end, 3),
            "plant_level_short_minutes_sum_over_days":
                round(plant_short_min_days, 1),
            "plant_level_max_short_minutes": round(plant_max_short_min, 1),
            "note": "lower bound, raw capacity, per SKU alone; not a "
                    "target"}


if __name__ == "__main__":
    print(json.dumps(bound(os.environ.get("MS_CLASS", "calib3"),
                           int(os.environ.get("MS_N", "4")),
                           ms.SEED_OFF,
                           json.loads(os.environ.get("MS_CLASS_JSON",
                                                     "{}")))))
