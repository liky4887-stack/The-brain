"""Phase D column-generation scaling measurement (the master-worker
architecture). Same clusters/seeds as coupled_scaling.py (2/4/8/16
plants, 0.75x binding supplier caps); measures per size:
  - CG wall (sequential pricing: rounds x sum of plant solves),
    iterations, columns, converged flag, proven LB
  - integer restricted master wall, incumbent UB
  - proven gap (LB vs UB, both independent)
Also records the EXTRAPOLATED parallel wall (rounds x slowest plant
solve, dispatch overhead NOT included) for the fabric mapping.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))

from brain_core.synthetic import FnbParams, generate_fnb_factory
from brain_core.rolling.two_level import solve_buckets
from brain_core.rolling.coupled import _plant_usage
from brain_core.rolling.coupled_dw import (column_generation,
                                           integer_master)

DAYS = 7
CAP_FACTOR = 0.75
SEEDS = [101 * (i + 1) for i in range(16)]


def build_cluster(n):
    ps = [generate_fnb_factory(FnbParams(seed=SEEDS[i], n_lines=4,
                                         n_skus=12, days=2,
                                         active_fraction=0.9,
                                         utilization=0.6,
                                         n_raw_materials=6,
                                         families=("DAIRY", "BAKERY")))
          for i in range(n)]
    return ps, ps[0].params.horizon_start, \
        ps[0].day_capacity_minutes


def binding_caps(ps, hs, cap):
    mat_tot = {}
    slowest = 0.0
    for p in ps:
        t0 = time.perf_counter()
        b = solve_buckets(p.factory, hs, DAYS, cap, time_limit_s=30.0)
        slowest = max(slowest, time.perf_counter() - t0)
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    return {k: CAP_FACTOR * v for k, v in mat_tot.items()}, slowest


def run_one(n, mode):
    ps, hs, cap = build_cluster(n)
    caps, slowest = binding_caps(ps, hs, cap)
    dw = None
    t_cg = t_im = None
    if mode in ("cg", "both"):
        t0 = time.perf_counter()
        dw = column_generation([p.factory for p in ps], hs, DAYS, cap,
                               supplier_cap=caps, max_iter=60,
                               time_limit_s=30.0)
        t_cg = time.perf_counter() - t0
    if mode in ("im", "both"):
        if dw is None:
            dw = column_generation([p.factory for p in ps], hs, DAYS,
                                   cap, supplier_cap=caps, max_iter=60,
                                   time_limit_s=30.0)
        t0 = time.perf_counter()
        dw = integer_master(dw, [p.factory for p in ps], hs, DAYS,
                            time_limit_s=240.0)
        t_im = time.perf_counter() - t0
    return dw, t_cg, t_im, slowest


def main():
    import os
    sizes = [int(x) for x in
             os.environ.get("CG_SIZES", "2,4,8,16").split(",")]
    mode = os.environ.get("CG_MODE", "both")
    rows = []
    for n in sizes:
        dw, t_cg, t_im, slowest = run_one(n, mode)
        rows.append({
            "plants": n, "seeds": SEEDS[:n], "cap_factor": CAP_FACTOR,
            "cg": {"wall_s": round(t_cg, 3) if t_cg is not None else None,
                   "iterations": dw.iterations,
                   "columns_per_plant": dw.columns_per_plant,
                   "converged": dw.converged, "status": dw.status,
                   "bound_certified": dw.bound_certified,
                   "lower_bound": dw.lower_bound},
            "integer_master": {"wall_s": round(t_im, 3) if t_im is not None else None,
                               "upper_bound": dw.upper_bound,
                               "problems": dw.problems[-3:]},
            "proven_gap": dw.proven_gap,
            "parallel_wall_extrapolated_s":
                round(dw.iterations * slowest, 2),
            "parallel_wall_note": "EXTRAPOLATED: iterations x slowest "
                "single-plant solve; dispatch overhead not included",
        })
        print(f"[done] {n} plants: CG "
              f"{t_cg if t_cg is None else round(t_cg,1)}s "
              f"({dw.iterations} iters, conv={dw.converged}, "
              f"certified={dw.bound_certified}), IM "
              f"{t_im if t_im is None else round(t_im,1)}s, "
              f"LB={dw.lower_bound}, UB={dw.upper_bound}, "
              f"gap={dw.proven_gap}", flush=True)
    Path(os.environ.get("CG_OUT", "/tmp/coupled-cg-scaling.json")).write_text(
        json.dumps({"measured": True, "rows": rows}, indent=1))
    print("WROTE", os.environ.get("CG_OUT", "/tmp/coupled-cg-scaling.json"), flush=True)


if __name__ == "__main__":
    main()
