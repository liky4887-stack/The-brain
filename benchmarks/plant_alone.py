"""Each plant of a calib instance solved ALONE (pools effectively
unlimited, same weights and min-lot as the n-plant benchmark: weights
and median demand come from the whole n-plant instance). Per-plant rows:
status, gap, objective, late/backlog/early/setups from the independent
validator. Where does lateness live? env: MS_CLASS (calib3), MS_N (4),
MS_SEED, PA_LIMIT_S (40), PA_GAP (1e-4), BRAIN_LINKING_M (v1|v2),
PA_OUT. One thread; run alone or state the concurrency.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import monolith_scaling as ms  # noqa: E402
from brain_core.rolling.coupled import (build_coupled_mip,  # noqa: E402
                                        validate_coupled_plan)
from brain_core.rolling.two_level import (EARLY_W,  # noqa: E402
                                          ObjectiveWeights,
                                          linking_m_version)
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from coupled_comparison import qty_from_mip_x  # noqa: E402


def main():
    cls = os.environ.get("MS_CLASS", "calib3")
    n = int(os.environ.get("MS_N", "4"))
    lim = float(os.environ.get("PA_LIMIT_S", "40"))
    gap = float(os.environ.get("PA_GAP", "1e-4"))
    c = dict(ms.CLASSES[cls])
    c.update(json.loads(os.environ.get("MS_CLASS_JSON", "{}")))
    ps = [generate_fnb_factory(FnbParams(
        seed=101 * (i + 1) + ms.SEED_OFF, n_lines=3, n_skus=c["n_skus"],
        days=c["days"], active_fraction=0.9, utilization=c["util"],
        n_raw_materials=6, families=("DAIRY", "BAKERY")))
        for i in range(n)]
    hs, cap, days = ps[0].params.horizon_start, \
        ps[0].day_capacity_minutes, c["days"]
    fs = [p.factory for p in ps]
    dd = ms.sku_daily_demand(fs, hs, days)
    d_med = statistics.median(dd.values())
    w = ObjectiveWeights(setup=c["tbo"] ** 2 * EARLY_W * d_med / 2.0)
    out = {"class": cls, "n": n, "seed": ms.SEED_OFF, "limit_s": lim,
           "rel_gap_target": gap, "threads": 1,
           "linking_m_version": linking_m_version(),
           "sha": ms._sha(), "weights": {"setup": w.setup, "late": w.late,
                                         "early": w.early},
           "concurrency": os.environ.get("PA_CONCURRENCY", "alone"),
           "plants": []}
    for i, f in enumerate(fs):
        mip, meta = build_coupled_mip([f], hs, days, cap, {}, {}, weights=w)
        if c.get("minlot_days"):
            def lot_fn(p_i, sk, M, i=i):
                return min(0.9 * M, c["minlot_days"] * dd.get((i, sk), d_med))
            mip, _ = ms.add_min_lot(mip, meta, None, lot_fn)
        t0 = time.perf_counter()
        r = ms.solve_highspy(mip, lim, 1, rel_gap=gap)
        rec = {"plant": i, "status": str(r["status"]),
               "wall_s": round(time.perf_counter() - t0, 1),
               "objective": r["objective"], "gap": r.get("gap"),
               "nodes": r.get("node_count")}
        if r["x"] is not None:
            q = qty_from_mip_x(r["x"], meta["maps"], meta["offsets"])
            pr, k = validate_coupled_plan([f], q, hs, days, cap)
            rec.update({"validator_problems": pr[:3], "late_unit_days":
                        k["late_unit_days"], "backlog_units_end":
                        k["backlog_units_end"], "early_unit_days":
                        k["early_unit_days"], "setups": k["setups"]})
        out["plants"].append(rec)
        print(json.dumps(rec), flush=True)
        Path(os.environ.get("PA_OUT", "/tmp/plant-alone.json")).write_text(
            json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
