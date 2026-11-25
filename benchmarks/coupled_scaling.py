"""Phase D coupled-cluster scaling measurement.

For cluster sizes 2, 4, 8, 16 plants (fixed seeds, recorded), builds
the ONE coupled bucket MIP (shared supplier pools at 0.75x uncoupled
usage = binding) and measures, per size:
  - primal solve (HiGHS): wall, status, incumbent UB, solver gap
  - Lagrangian dual (subgradient + repair): wall, proven LB, repaired
    UB, proven gap
All numbers MEASURED on this box; seeds and params recorded for
reproducibility. UNKNOWN statuses are reported, never dressed up.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))

from brain_core.synthetic import FnbParams, generate_fnb_factory
from brain_core.rolling.two_level import solve_buckets
from brain_core.rolling.coupled import (coupled_dual, _plant_usage,
                                        solve_coupled_cluster)

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
    hs = ps[0].params.horizon_start
    cap = ps[0].day_capacity_minutes
    return ps, hs, cap


def binding_caps(ps, hs, cap):
    mat_tot = {}
    for p in ps:
        b = solve_buckets(p.factory, hs, DAYS, cap, time_limit_s=30.0)
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    return {k: CAP_FACTOR * v for k, v in mat_tot.items()}


def main():
    rows = []
    for n in (2, 4, 8, 16):
        ps, hs, cap = build_cluster(n)
        t0 = time.perf_counter()
        caps = binding_caps(ps, hs, cap)
        t_caps = time.perf_counter() - t0

        t0 = time.perf_counter()
        primal = solve_coupled_cluster([p.factory for p in ps], hs,
                                       DAYS, cap, supplier_cap=caps,
                                       time_limit_s=240.0)
        t_primal = time.perf_counter() - t0

        t0 = time.perf_counter()
        dual = coupled_dual([p.factory for p in ps], hs, DAYS, cap,
                            supplier_cap=caps, rounds=20,
                            time_limit_s=30.0, repair_every=5)
        t_dual = time.perf_counter() - t0

        rows.append({
            "plants": n, "seeds": SEEDS[:n], "days": DAYS,
            "cap_factor": CAP_FACTOR, "n_pools": len(caps),
            "primal": {"wall_s": round(t_primal, 3),
                       "status": primal["status"],
                       "objective": primal["objective"],
                       "gap": primal.get("gap"),
                       "n_vars": primal["n_vars"],
                       "n_rows": primal["n_rows"]},
            "dual": {"wall_s": round(t_dual, 3),
                     "rounds": dual.rounds_run,
                     "lower_bound": dual.lower_bound,
                     "upper_bound": dual.upper_bound,
                     "proven_gap": dual.proven_gap,
                     "problems": dual.problems[:5]},
            "caps_wall_s": round(t_caps, 3),
        })
        print(f"[done] {n} plants: primal {t_primal:.1f}s "
              f"({primal['status']}), dual {t_dual:.1f}s "
              f"(LB={dual.lower_bound}, UB={dual.upper_bound})",
              flush=True)
    out = {"measured": True, "days": DAYS, "cap_factor": CAP_FACTOR,
           "rows": rows}
    Path("/tmp/coupled-scaling.json").write_text(json.dumps(out,
                                                           indent=1))
    print("WROTE /tmp/coupled-scaling.json", flush=True)


if __name__ == "__main__":
    main()
