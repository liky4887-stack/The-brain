"""Monolith on one CG-cluster seed (pools 0.9 x uncoupled usage, n=2, 7 days),
saving the PLAN and an objective decomposition computed from the plan with
raw records (not from model helpers).

env: MP_SEED (seed_base), MP_LIMIT (s), MP_OUT, BRAIN_LINKING_M (version of
the SOLVE), MP_CAPS (json cache: created under MP_CAPS_VERSION, default v1,
and reused so v1 and v2 see the SAME pools), MP_CONCURRENCY (text).
Objective terms (two_level.build_bucket_mip): setup*y(sku-day), late*lo(sku,
day) with lo >= cum_demand - cum_produced EVERY day (so a shortfall that
persists is charged on every day it persists, incl. the final day),
early*e with e >= cum_produced - cum_demand every day."""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import coupled_comparison as cc  # noqa: E402
from brain_core.rolling.coupled import (build_coupled_mip,  # noqa: E402
                                        validate_coupled_plan)
from brain_core.rolling.two_level import DEFAULT_WEIGHTS as W, linking_m_version  # noqa: E402
from brain_core.guards.independent_data import raw_sku_data, raw_due_day  # noqa: E402
from brain_core.solvers.highs_mip import solve_mip  # noqa: E402


def caps_for(ps, hs, cap):
    path = os.environ.get("MP_CAPS")
    if path and os.path.exists(path):
        d = json.load(open(path))
        return ({tuple(json.loads(k)): v for k, v in d["sup"].items()},
                {int(k): v for k, v in d["lab"].items()}, d["version"], "cache hit")
    keep = os.environ.get("BRAIN_LINKING_M")
    os.environ["BRAIN_LINKING_M"] = os.environ.get("MP_CAPS_VERSION", "v1")
    sup, lab, solo = cc.binding_caps(ps, hs, cap)
    ver = os.environ["BRAIN_LINKING_M"]
    if keep is None:
        os.environ.pop("BRAIN_LINKING_M")
    else:
        os.environ["BRAIN_LINKING_M"] = keep
    if path:
        json.dump({"version": ver, "sup": {json.dumps(list(k)): v for k, v in sup.items()},
                   "lab": {str(k): v for k, v in lab.items()}}, open(path, "w"))
    return sup, lab, ver, "computed"


def decompose(factories, qtys, hs, days):
    set_n = 0; short = 0.0; early = 0.0; end_bl = 0.0; per_plant = []
    for f, qty in zip(factories, qtys):
        sku = raw_sku_data(f); dem = {}
        for d in f.demands:
            t = raw_due_day(d.due, hs)
            if 0 <= t < days:
                dem.setdefault(d.item, [0.0] * days)[t] += d.quantity
        pp = dict(setup_days=0, short=0.0, early=0.0, end_backlog=0.0)
        for s, ds in dem.items():
            lines = sku[s][1]; cum = pr = 0.0
            for t in range(days):
                q = sum(qty.get((s, t, l), 0.0) for l in lines)
                if q > 1e-9:
                    pp["setup_days"] += 1
                cum += ds[t]; pr += q
                pp["short"] += max(0.0, cum - pr)
                pp["early"] += max(0.0, pr - cum)
            pp["end_backlog"] += max(0.0, cum - pr)
        per_plant.append(pp)
    tot = {k: sum(p[k] for p in per_plant) for k in per_plant[0]}
    tot["terms"] = {"setup": W.setup * tot["setup_days"],
                    "late": W.late * tot["short"],
                    "early": W.early * tot["early"]}
    tot["terms_sum"] = sum(tot["terms"].values())
    return tot


def main():
    seed = int(os.environ["MP_SEED"]); lim = float(os.environ.get("MP_LIMIT", "600"))
    ps, hs, cap = cc.build_cluster(2, seed_base=seed)
    fs = [p.factory for p in ps]
    sup, lab, cver, cnote = caps_for(ps, hs, cap)
    out = {"seed_base": seed, "plants": 2, "days": cc.DAYS, "limit_s": lim,
           "cap_factors": {"supplier": cc.SUPPLIER_FACTOR, "labor": cc.LABOR_FACTOR},
           "linking_m_version": linking_m_version(), "caps_linking_m_version": cver,
           "caps_note": cnote, "sha": cc._sha(), "weights": vars(W) if hasattr(W, "__dict__") else str(W),
           "concurrency": os.environ.get("MP_CONCURRENCY", "alone")}
    mip, meta = build_coupled_mip(fs, hs, cc.DAYS, cap, sup, lab)
    t0 = time.perf_counter()
    res = solve_mip(mip, time_limit_s=lim, mip_rel_gap=0.0)
    out.update(wall_s=round(time.perf_counter() - t0, 1), status=str(res["status"]),
               objective=res["objective"], gap=res.get("gap"), nodes=res.get("node_count"))
    if res["x"] is not None:
        q = cc.qty_from_mip_x(res["x"], meta["maps"], meta["offsets"])
        probs, k = validate_coupled_plan(fs, q, hs, cc.DAYS, cap, supplier_cap=sup, labor_cap=lab)
        out["validator_problems"] = probs[:5]; out["kpis"] = k
        out["decomposition"] = decompose(fs, q, hs, cc.DAYS)
        out["plan"] = [[[s, t, l, v] for (s, t, l), v in sorted(p.items())] for p in q]
    Path(os.environ["MP_OUT"]).write_text(json.dumps(out))
    d = out.get("decomposition", {})
    print(json.dumps({k: out.get(k) for k in ("linking_m_version", "caps_note", "status", "gap", "objective", "wall_s")}
                     | {"decomp_terms_sum": d.get("terms_sum"), "terms": d.get("terms"), "end_backlog": d.get("end_backlog")}), flush=True)


main()
