"""CG trace: record the per-iteration master objective and Farley LB
(unseeded, same instance builder and caps as coupled_comparison) so
the natural flat stretches of the bound can be MEASURED.

python benchmarks/cg_trace.py SEED_BASE OUT.json
env: CMP_SIZE (2), CMP_SUPPLIER_FACTOR/CMP_LABOR_FACTOR, CG_ITERS (400),
CG_WALL_S (900). Also prints the longest flat stretch per tolerance.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coupled_comparison as cc  # noqa: E402
from brain_core.rolling.coupled_dw import column_generation  # noqa: E402


def longest_flat(series, rel_tol, decreasing=True):
    """Longest run of consecutive updates whose best-so-far did not
    improve by more than rel_tol (relative)."""
    best, cur, worst = None, 0, 0
    for v in series:
        if best is None:
            best = v
            continue
        gain = (best - v) if decreasing else (v - best)
        if gain > rel_tol * max(1.0, abs(best)):
            best, cur = v, 0
        else:
            cur += 1
            worst = max(worst, cur)
    return worst


from brain_core.guards.progress import DEFAULT_CG_PROGRESS_WINDOW  # noqa: E402


if __name__ == "__main__":
    seed, out = int(sys.argv[1]), sys.argv[2]
    n = int(os.environ.get("CMP_SIZE", "2"))
    ps, hs, cap = cc.build_cluster(n, seed_base=seed)
    sup, lab, solo = cc.binding_caps(ps, hs, cap)
    t0 = time.perf_counter()
    dw = column_generation(
        [p.factory for p in ps], hs, cc.DAYS, cap, supplier_cap=sup,
        labor_cap=lab, max_iter=int(os.environ.get("CG_ITERS", "400")),
        time_limit_s=30.0, seed_qtys=None,
        wall_s=float(os.environ.get("CG_WALL_S", "900")))
    wall = time.perf_counter() - t0
    tols = [1e-12, 1e-9, 1e-6, 1e-4]
    rec = {"class": {"n": n, "seed_base": seed,
                     "supplier": cc.SUPPLIER_FACTOR,
                     "labor": cc.LABOR_FACTOR, "days": cc.DAYS},
           "sha": cc._sha(), "seeded": False,
           "progress_window": DEFAULT_CG_PROGRESS_WINDOW,
           "status": dw.status, "converged": dw.converged,
           "iterations": dw.iterations, "wall_s": round(wall, 1),
           "master_series": dw.master_series, "lb_series": dw.lb_series,
           "flat_master": {str(t): longest_flat(dw.master_series, t)
                           for t in tols},
           "flat_lb": {str(t): longest_flat(dw.lb_series, t, False)
                       for t in tols}}
    json.dump(rec, open(out, "w"), default=str)
    print(json.dumps({k: rec[k] for k in ("class", "status",
          "iterations", "wall_s", "flat_master", "flat_lb")}))
