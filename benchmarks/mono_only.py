"""Monolith only on one coupled-comparison instance, long limit.

python benchmarks/mono_only.py SEED_BASE LIMIT_S OUT.json
Class from env CMP_SUPPLIER_FACTOR / CMP_LABOR_FACTOR (default 0.75,
0.8), n from CMP_SIZE (default 2). Same instance builder, caps and MIP
as coupled_comparison.run; writes status, objective, gap, bound, wall,
threads, SHA, manifest. Measured only; no CG.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coupled_comparison as cc  # noqa: E402
from brain_core.rolling.coupled import build_coupled_mip  # noqa: E402
from brain_core.solvers.highs_mip import solve_mip  # noqa: E402

seed, limit, out = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
n = int(os.environ.get("CMP_SIZE", "2"))
ps, hs, cap = cc.build_cluster(n, seed_base=seed)
sup, lab, solo = cc.binding_caps(ps, hs, cap)
t0 = time.perf_counter()
mip, meta = build_coupled_mip([p.factory for p in ps], hs, cc.DAYS, cap,
                              sup, lab)
r = solve_mip(mip, time_limit_s=limit, mip_rel_gap=0.0)
rec = {"status": str(r["status"]), "incumbent": r.get("objective"),
       "mip_gap": r.get("gap"), "nodes": r.get("node_count"),
       "int_violation": r.get("int_violation"),
       "wall_s": round(time.perf_counter() - t0, 1),
       "time_limit_s": limit, "has_incumbent": r["x"] is not None}
res = {"class": {"n": n, "seed_base": seed,
                 "supplier": cc.SUPPLIER_FACTOR, "labor": cc.LABOR_FACTOR,
                 "days": cc.DAYS},
       "sha": cc._sha(), "machine": os.uname().nodename,
       "uncoupled_objective_sum": solo,
       "concurrency_note": os.environ.get("CONCURRENCY_NOTE", ""),
       "solves": {"monolith": rec}}
json.dump(res, open(out, "w"), indent=1, default=str)
