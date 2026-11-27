"""Do the shared pools bind? Per seed: solve each plant ALONE (no pool rows,
exact), sum the optima, and check the combined solo plans against the real
pools with the independent validator. If the combined solo plan is valid,
the instance is independent (sum of optima = exact coupled optimum, pools
cannot change the plan). Also reports the max pool utilisation of the
combined solo plan and the number of pool rows at >= 99.9%.
Env: CMP_SUPPLIER_FACTOR, CMP_LABOR_FACTOR, CMP_SIZE, CMP_REPLICAS,
PB_LIMIT, PB_REF (coupled_comparison json to read the monolith objective)."""
import json, os, sys, time
import coupled_comparison as cc
from brain_core.rolling.coupled import (build_coupled_mip,
                                        validate_coupled_plan)
from brain_core.solvers.highs_mip import solve_mip

cc.SUPPLIER_FACTOR = float(os.environ.get("CMP_SUPPLIER_FACTOR", "0.75"))
cc.LABOR_FACTOR = float(os.environ.get("CMP_LABOR_FACTOR", "0.8"))
n = int(os.environ.get("CMP_SIZE", "2"))
reps = int(os.environ.get("CMP_REPLICAS", "10"))
lim = float(os.environ.get("PB_LIMIT", "120"))
ref = {}
if os.environ.get("PB_REF"):
    for r in json.load(open(os.environ["PB_REF"]))["rows"]:
        ref[r["seed_base"]] = r["monolithic"].get("incumbent")
rows = []
for i in range(reps):
    sb = i * 100003 if i else 0
    sb = [0, 100003, 200006, 300009, 400012, 500015, 600018, 700021,
          800024, 900027][i]
    ps, hs, cap = cc.build_cluster(n, seed_base=sb)
    fs = [p.factory for p in ps]
    sup, lab, _ = cc.binding_caps(ps, hs, cap)
    qtys, opts, stat = [], [], []
    t0 = time.perf_counter()
    for f in fs:
        mip, meta = build_coupled_mip([f], hs, cc.DAYS, cap, {}, {})
        res = solve_mip(mip, time_limit_s=lim, mip_rel_gap=0.0)
        stat.append(str(res["status"]))
        opts.append(res["objective"])
        qtys.append(cc.qty_from_mip_x(res["x"], meta["maps"],
                                      meta["offsets"])[0])
    probs, kpis = validate_coupled_plan(fs, qtys, hs, cc.DAYS, cap,
                                        supplier_cap=sup, labor_cap=lab)
    mat, lb = {}, {}
    for f, q in zip(fs, qtys):
        m, l = cc._plant_usage(f, q)
        for k, v in m.items(): mat[k] = mat.get(k, 0) + v
        for k, v in l.items(): lb[k] = lb.get(k, 0) + v
    ut = [mat.get(k, 0) / v for k, v in sup.items() if v > 0] + \
         [lb.get(k, 0) / v for k, v in lab.items() if v > 0]
    row = {"seed_base": sb, "plants": n,
           "factors": [cc.SUPPLIER_FACTOR, cc.LABOR_FACTOR],
           "solo_status": stat, "solo_all_optimal":
           all("Optimal" in s for s in stat), "sum_solo_optima": sum(opts),
           "monolith_incumbent": ref.get(sb),
           "combined_solo_plan_valid_vs_pools": not probs,
           "validator_problems_n": len(probs),
           "max_pool_util": max(ut) if ut else None,
           "pool_rows": len(ut), "pool_rows_ge_99_9pct":
           sum(1 for u in ut if u >= 0.999),
           "wall_s": round(time.perf_counter() - t0, 1)}
    print(json.dumps(row), flush=True)
    rows.append(row)
json.dump(rows, open(os.environ.get("PB_OUT", "/tmp/pb.json"), "w"))
