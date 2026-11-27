"""Diagnosis: do the CG pricing objective and the master column cost
use the same cost basis?  (distributed non-convergence, 1.0/1.0 s0 and
s700021; 0.9 all seeds).

For each plant of a coupled_comparison cluster: solve_buckets(extra=0)
objective vs coupled_dw._column cost of the SAME qty (true-cost recompute
under DEFAULT_WEIGHTS).  A nonzero difference is a rc bias at zero duals:
rc = b.objective - sigma_p is then wrong by that offset every round.
Measured, per plant; no model-derived claims."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import coupled_comparison as cc
from brain_core.rolling.coupled_dw import _column
from brain_core.rolling.two_level import solve_buckets, DEFAULT_WEIGHTS

n = int(os.environ.get("CMP_SIZE", "2"))
seed_base = int(os.environ.get("CMP_SEED_BASE", "0"))
ps, hs, cap = cc.build_cluster(n, seed_base=seed_base)
rows = []
for i, p in enumerate(ps):
    b = solve_buckets(p.factory, hs, cc.DAYS, cap, time_limit_s=30.0)
    col = _column(p.factory, hs, cc.DAYS, b.qty, None, DEFAULT_WEIGHTS)
    rows.append({"plant": i, "seed_base": seed_base, "status": b.status[:40],
                 "bucket_objective": b.objective,
                 "column_cost_true": col["cost"],
                 "diff": b.objective - col["cost"],
                 "weights": {k: getattr(DEFAULT_WEIGHTS, k) for k in
                             ("setup", "late", "early", "energy")}})
print(json.dumps(rows, indent=1))
