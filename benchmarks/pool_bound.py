"""Pool-level LOWER BOUND on the lateness term for CG-cluster seeds (pools
0.9, n=2, 7 days). LP over per-SKU-day production q (units), raw capacity, no
line capacity, no changeovers, no setups, build-ahead allowed:
  min sum_{s,t} shortfall_{s,t}   shortfall_{s,t} >= cum_demand(s,t) - cum_q(s,t)
  per (material, day) in the supplier pool: sum_s recipe[s][r] q_{s,t} <= cap(r,t)
  per day labor pool: sum_s q_{s,t}/rate_s <= labor_cap(t)
Variant B adds per-plant minutes: sum_{s in plant} q_{s,t}/rate_s <= lines*cap_eff.
Also: min end shortfall (sum_s max(0, total demand - total q)).
Caps = the cached caps of mono_plan.py (MP_CAPS_DIR/mp-caps-SEED.json).
A bound, not a target: the real optimum is >= the bound."""
import json, os, sys
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import coupled_comparison as cc  # noqa: E402
from brain_core.rolling import two_level as T  # noqa: E402
from brain_core.guards.independent_data import raw_sku_data, raw_recipe_data, raw_due_day  # noqa: E402


def bound(seed, caps_path, plant_minutes):
    ps, hs, cap = cc.build_cluster(2, seed_base=seed)
    d = json.load(open(caps_path))
    sup = {tuple(json.loads(k)): v for k, v in d["sup"].items()}
    lab = {int(k): v for k, v in d["lab"].items()}
    days = cc.DAYS; cap_eff = cap * (1 - T.DEFAULT_CHG_ALLOWANCE)
    skus = []   # (plant, sku, rate, recipe, demand[t])
    for pi, p in enumerate(ps):
        f = p.factory; sk = raw_sku_data(f); rc = raw_recipe_data(f); dem = {}
        for dm in f.demands:
            t = raw_due_day(dm.due, hs)
            if 0 <= t < days:
                dem.setdefault(dm.item, [0.0] * days)[t] += dm.quantity
        for s, ds in dem.items():
            skus.append((pi, s, sk[s][0], rc.get(s, {}), ds, len(sk[s][1])))
    n = len(skus); nq = n * days
    qi = lambda i, t: i * days + t
    si = lambda i, t: nq + i * days + t
    nv = 2 * nq
    A, b = [], []
    for i, (pi, s, rate, rc, ds, nl) in enumerate(skus):          # shortfall rows
        cum = 0.0
        for t in range(days):
            cum += ds[t]; row = np.zeros(nv)
            for tau in range(t + 1): row[qi(i, tau)] -= 1.0
            row[si(i, t)] = -1.0
            A.append(row); b.append(-cum)                         # -cumq - sf <= -cum
    for (r, t), c in sup.items():
        row = np.zeros(nv)
        for i, (pi, s, rate, rc, ds, nl) in enumerate(skus):
            if rc.get(r): row[qi(i, t)] = rc[r]
        if row.any(): A.append(row); b.append(c)
    for t, c in lab.items():
        row = np.zeros(nv)
        for i, (pi, s, rate, rc, ds, nl) in enumerate(skus): row[qi(i, t)] = 1.0 / rate
        A.append(row); b.append(c)
    if plant_minutes:
        for pi in range(len(ps)):
            for t in range(days):
                row = np.zeros(nv)
                for i, (p2, s, rate, rc, ds, nl) in enumerate(skus):
                    if p2 == pi: row[qi(i, t)] = 1.0 / rate
                A.append(row); b.append(3 * cap_eff)
    c = np.zeros(nv); c[nq:] = 1.0
    r = linprog(c, A_ub=np.array(A), b_ub=b, bounds=(0, None), method="highs")
    # end shortfall bound: same constraints, minimise sum over sku of final shortfall
    c2 = np.zeros(nv)
    for i in range(n): c2[si(i, days - 1)] = 1.0
    r2 = linprog(c2, A_ub=np.array(A), b_ub=b, bounds=(0, None), method="highs")
    tot = sum(sum(x[4]) for x in skus)
    return {"total_demand_units": tot, "min_shortfall_unit_days": r.fun,
            "late_term_lower_bound": T.DEFAULT_WEIGHTS.late * r.fun,
            "min_end_shortfall_units": r2.fun, "end_shortfall_ratio": r2.fun / tot,
            "status": [r.status, r2.status]}


if __name__ == "__main__":
    cdir = os.environ.get("MP_CAPS_DIR", "/tmp")
    for seed in (100003, 200006, 400012, 500015, 700021, 800024):
        cp = os.path.join(cdir, "mp-caps.json" if seed == 100003 else f"mp-caps-{seed}.json")
        for pm in (False, True):
            print(json.dumps({"seed": seed, "plant_minutes": pm,
                              "caps_linking_m_version": "v1", **bound(seed, cp, pm)}), flush=True)
