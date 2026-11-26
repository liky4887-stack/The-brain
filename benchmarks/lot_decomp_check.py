"""Exact optimum of a calib instance by decomposition, and the check that
makes it exact (review 10:35 PM).

Solves each plant ALONE (shared pools effectively unlimited) to a tight
gap, sums the optima (a valid LOWER BOUND of the coupled problem: it is
a relaxation), assembles the combined plan and validates it against the
REAL shared pools with the independent coupled validator. If the combined
plan is valid, the sum is attained, so it is the exact coupled optimum
and the pools do not bind (the class is decomposable: a CG/Lagrangian
bound on it equals this sum, and "CG beats the monolith" there only says
that independent blocks are solved better as blocks).

env: MS_N, MS_CLASS, MS_SEED, MS_CAP_SOLVE_S, DC_LIMIT_S (per plant,
default 120), DC_GAP (default 1e-6), MS_CLASS_JSON, DC_OUT.
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
from brain_core.rolling.two_level import (ObjectiveWeights,  # noqa: E402
                                          EARLY_W)
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from coupled_comparison import qty_from_mip_x  # noqa: E402


def main():
    n = int(os.environ["MS_N"])
    cls = os.environ.get("MS_CLASS", "calib3")
    seed_off = ms.SEED_OFF
    cap_solve = float(os.environ.get("MS_CAP_SOLVE_S", "60"))
    lim = float(os.environ.get("DC_LIMIT_S", "120"))
    gap = float(os.environ.get("DC_GAP", "1e-6"))
    c = dict(ms.CLASSES[cls])
    c.update(json.loads(os.environ.get("MS_CLASS_JSON", "{}")))
    ps = [generate_fnb_factory(FnbParams(
        seed=101 * (i + 1) + seed_off, n_lines=3, n_skus=c["n_skus"],
        days=c["days"], active_fraction=0.9, utilization=c["util"],
        n_raw_materials=6, families=("DAIRY", "BAKERY")))
        for i in range(n)]
    hs = ps[0].params.horizon_start
    cap = ps[0].day_capacity_minutes
    fs = [p.factory for p in ps]
    days = c["days"]
    sup, lab, unsolved, note = ms.make_caps(ps, hs, days, cap, c,
                                            cap_solve, cls, n)
    dd = ms.sku_daily_demand(fs, hs, days)
    d_med = statistics.median(dd.values())
    S = c["tbo"] ** 2 * EARLY_W * d_med / 2.0
    w = ObjectiveWeights(setup=S)
    out = {"class": cls, "plants": n, "seed": seed_off, "params": c,
           "setup_weight": S, "sha": ms._sha(), "runner": ms.runner_specs(),
           "per_plant": [], "caps_note": note}
    big_sup = {k: 1e3 * v for k, v in sup.items()}
    big_lab = {k: 1e3 * v for k, v in lab.items()}
    qtys, total, all_opt = [], 0.0, True
    t_all = time.perf_counter()
    for i, f in enumerate(fs):
        mip, meta = build_coupled_mip([f], hs, days, cap, big_sup, big_lab,
                                      weights=w)
        if c.get("minlot_days"):
            def lot_fn(p_i, sk, M, i=i):
                d = dd.get((i, sk), d_med)
                return min(0.9 * M, c["minlot_days"] * d)
            mip, _ = ms.add_min_lot(mip, meta, None, lot_fn)
        t0 = time.perf_counter()
        r = ms.solve_highspy(mip, lim, 1, rel_gap=gap)
        dt = time.perf_counter() - t0
        opt = "ptimal" in str(r["status"])
        all_opt &= opt
        rec = {"plant": i, "status": str(r["status"]), "wall_s": round(dt, 1),
               "objective": r["objective"], "gap": r.get("gap"),
               "nodes": r.get("node_count"),
               "int_violation": r.get("int_violation"),
               "bound": (r["objective"] * (1 - r["gap"])
                         if r["x"] is not None and r.get("gap") is not None
                         else None)}
        out["per_plant"].append(rec)
        if r["x"] is None:
            all_opt = False
            continue
        total += r["objective"]
        qtys.extend(qty_from_mip_x(r["x"], meta["maps"], meta["offsets"]))
    out["sum_plan_objective"] = total
    out["sum_bound"] = sum(p["bound"] for p in out["per_plant"]
                           if p["bound"] is not None)
    out["all_plants_optimal_to_gap"] = all_opt
    out["decomp_wall_s"] = round(time.perf_counter() - t_all, 1)
    if len(qtys) == n:
        problems, kpis = validate_coupled_plan(
            fs, qtys, hs, days, cap, supplier_cap=sup, labor_cap=lab)
        out["combined_plan_validation_problems"] = problems[:10]
        out["combined_plan_valid_vs_real_pools"] = (len(problems) == 0)
    out["reading"] = ("combined plan valid against the real pools => the "
                      "pools do not bind; the sum of per-plant optima IS "
                      "the exact coupled optimum, and a CG bound on this "
                      "class equals it" if out.get(
                          "combined_plan_valid_vs_real_pools") else
                      "combined plan violates the real pools => the pools "
                      "bind, the sum is only a lower bound")
    Path(os.environ.get("DC_OUT", "/tmp/decomp.json")).write_text(
        json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in (
        "sum_plan_objective", "sum_bound", "all_plants_optimal_to_gap",
        "combined_plan_valid_vs_real_pools", "decomp_wall_s")}))


if __name__ == "__main__":
    main()
