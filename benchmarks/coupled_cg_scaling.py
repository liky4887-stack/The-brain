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


def main():
    rows = []
    for n in (2, 4, 8, 16):
        ps, hs, cap = build_cluster(n)
        caps, slowest = binding_caps(ps, hs, cap)
        t0 = time.perf_counter()
        dw = column_generation([p.factory for p in ps], hs, DAYS, cap,
                               supplier_cap=caps, max_iter=60,
                               time_limit_s=30.0)
        t_cg = time.perf_counter() - t0
        t0 = time.perf_counter()
        dw = integer_master(dw, [p.factory for p in ps], hs, DAYS,
                            time_limit_s=240.0)
        t_im = time.perf_counter() - t0
        rows.append({
            "plants": n, "seeds": SEEDS[:n], "cap_factor": CAP_FACTOR,
            "cg": {"wall_s": round(t_cg, 3),
                   "iterations": dw.iterations,
                   "columns_per_plant": dw.columns_per_plant,
                   "converged": dw.converged, "status": dw.status,
                   "lower_bound": dw.lower_bound},
            "integer_master": {"wall_s": round(t_im, 3),
                               "upper_bound": dw.upper_bound,
                               "problems": dw.problems[-3:]},
            "proven_gap": dw.proven_gap,
            "parallel_wall_extrapolated_s":
                round(dw.iterations * slowest, 2),
            "parallel_wall_note": "EXTRAPOLATED: iterations x slowest "
                "single-plant solve; dispatch overhead not included",
        })
        print(f"[done] {n} plants: CG {t_cg:.1f}s "
              f"({dw.iterations} iters, conv={dw.converged}), "
              f"IM {t_im:.1f}s, LB={dw.lower_bound}, "
              f"UB={dw.upper_bound}, gap={dw.proven_gap}", flush=True)
    Path("/tmp/coupled-cg-scaling.json").write_text(
        json.dumps({"measured": True, "rows": rows}, indent=1))
    print("WROTE /tmp/coupled-cg-scaling.json", flush=True)


if __name__ == "__main__":
    main()
