"""Monolith-only scaling probe (review 15): where does the plain
coupled MIP stop being solvable? One instance size per process, stages
written to JSON as they complete so an OOM/timeout kill still leaves
the measured stages. Everything measured; nothing estimated.

env: MS_N (plants), MS_LIMIT (solve seconds), MS_CLASS (easy|hard),
MS_OUT (json path), MS_CAP_SOLVE_S (per-plant solo solve limit for
cap generation).

easy = the crossover instances (7 days, 12 SKUs/plant, util 0.6,
caps 0.75/0.8 of uncoupled usage). hard = 14 days, 16 SKUs/plant,
util 0.85, caps 0.55/0.65 (tight shared pools). Lead times are NOT
modelled by this bucket model; stated as a limitation, not tested.
time to first valid plan: scipy.milp exposes no incumbent timestamp,
so the recorded time is wall at termination (optimal, or time limit
with an incumbent); 'first_plan_time_available' is false.
"""
from __future__ import annotations
import json, os, resource, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))
from brain_core.synthetic import FnbParams, generate_fnb_factory
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coupled_comparison import qty_from_mip_x
from brain_core.rolling.coupled import (build_coupled_mip,
                                        validate_coupled_plan,
                                        _plant_usage)
from brain_core.rolling.two_level import solve_buckets
from brain_core.solvers.highs_mip import solve_mip

CLASSES = {
    "easy": dict(days=7, n_skus=12, util=0.6, sup=0.75, lab=0.8),
    "hard": dict(days=14, n_skus=16, util=0.85, sup=0.55, lab=0.65),
    # lumpy = hard + fixed-charge economics the bucket model supports:
    # setup weight x200 (a setup costs as much as 10,000 unit-days
    # late/1000 = 10 units late a day) and a MINIMUM LOT of 25% of the
    # tight big-M (x >= L*y), added by this probe (the core model has no
    # min-lot; the core files are NOT modified). Setup TIME consumption
    # is not modelled by the core (aggregate changeover allowance only).
    "lumpy": dict(days=14, n_skus=16, util=0.85, sup=0.65, lab=0.7,
                  setup_scale=200.0, minlot_frac=0.25),
    # calib = standard lot-sizing calibration (review 16): the setup
    # cost S is chosen so the EOQ time between orders of the MEDIAN
    # SKU is `tbo` days: TBO = sqrt(2 S / (h d))  =>  S = TBO^2 h d / 2
    # with h = the model's holding weight (EARLY_W) and d the median
    # daily demand per SKU of the generated instance. Minimum lot =
    # minlot_tbo x (TBO days of that SKU's demand), capped at 90% of
    # the tight big-M. Parameters are synthetic; no benchmark library
    # (Trigeiro / Tempelmeier-Derstroff) is used: those have setup
    # TIMES and a different structure the core model does not support.
    "calib1": dict(days=14, n_skus=16, util=0.85, sup=0.65, lab=0.7,
                   tbo=1.0, minlot_tbo=0.5),
    "calib3": dict(days=14, n_skus=16, util=0.85, sup=0.65, lab=0.7,
                   tbo=3.0, minlot_tbo=0.5),
    "calib5": dict(days=14, n_skus=16, util=0.85, sup=0.65, lab=0.7,
                   tbo=5.0, minlot_tbo=0.5),
}


def sku_daily_demand(factories, hs, days):
    """{(plant, sku): average daily demand over the horizon}, from the
    records."""
    from brain_core.rolling.two_level import due_day
    tot = {}
    for p_i, f in enumerate(factories):
        for d in f.demands:
            if 0 <= due_day(d.due, hs) < days:
                tot[(p_i, d.item)] = tot.get((p_i, d.item), 0.0) \
                    + d.quantity
    return {k: v / days for k, v in tot.items()}


def add_min_lot(mip, meta, frac, lot_fn=None):
    """Append x_sum(sku, day) - L*y >= 0 for every plant/sku/day, with
    L = frac * M where M is the model's own tight big-M, read from its
    linking row. Returns (new_mip, {(plant, sku, day): L})."""
    import numpy as np
    from scipy.sparse import coo_matrix, vstack
    from brain_core.solvers.highs_mip import MIP
    A = mip.A.tocsc()
    rows, cols, vals, lots = [], [], [], {}
    r = 0
    for p_i, mp in enumerate(meta["maps"]):
        off = meta["offsets"][p_i]
        by_sd = {}
        for (sk, t, l), j in mp["x"].items():
            by_sd.setdefault((sk, t), []).append(off + j)
        for (sk, t), yj in mp["y"].items():
            col = A.getcol(off + yj)
            negs = [v for v in col.data if v < 0]
            if not negs:
                continue
            M = -min(negs)
            L = lot_fn(p_i, sk, M) if lot_fn else frac * M
            for j in by_sd[(sk, t)]:
                rows.append(r); cols.append(j); vals.append(1.0)
            rows.append(r); cols.append(off + yj); vals.append(-L)
            lots[(p_i, sk, t)] = L
            r += 1
    extra = coo_matrix((vals, (rows, cols)), shape=(r, A.shape[1])).tocsr()
    new = MIP(mip.name, mip.c, vstack([mip.A.tocsr(), extra]).tocsr(),
              tuple(mip.sense) + ("G",) * r,
              np.concatenate([mip.rhs, np.zeros(r)]),
              mip.lb, mip.ub, mip.integrality)
    return new, lots


def add_ls_cuts(mip, meta, factories, hs, days):
    """(l,S) inequalities, prefix-S family, with lateness (probe only).
    For SKU s, horizon end k and split j<k (T_k = cumulative demand
    due by k, net of nothing: no opening inventory in the probe):
      sum_{t<=j} x_t + sum_{j<t<=k} d_{t,k} y_t + sum_{u<=k} lo_u >= T_k
    with d_{t,k} = T_k - T_{t-1}. Valid: take t* the first t in
    (j,k] with y=1; units due before t* are covered by x_{<=j} or are
    late (lo_u >= lo_{t*-1}); y_{t*}=1 pays for the rest. If no such
    t*, every x in (j,k] is 0. Valid for every feasible plan, so the
    optimum is unchanged; only the LP bound moves. y,lo are adjacent
    columns in the bucket model (y, lo, e)."""
    import numpy as np
    from scipy.sparse import coo_matrix, vstack
    from brain_core.rolling.two_level import due_day
    from brain_core.solvers.highs_mip import MIP
    rows, cols, vals, rhs = [], [], [], []
    r = 0
    for p_i, mp in enumerate(meta["maps"]):
        off = meta["offsets"][p_i]
        dem = {}
        for d in factories[p_i].demands:
            day = due_day(d.due, hs)
            if 0 <= day < days:
                dem.setdefault(d.item, [0.0] * days)[day] += d.quantity
        xs = {}
        for (sk, t, l), j in mp["x"].items():
            xs.setdefault((sk, t), []).append(off + j)
        for sk in sorted({k[0] for k in mp["y"]}):
            ds = dem.get(sk)
            if not ds:
                continue
            T = np.concatenate([[0.0], np.cumsum(ds)])  # T[t+1]=due by t
            for k in range(1, days):
                Tk = T[k + 1]
                if Tk <= 0:
                    continue
                for j in range(-1, k):
                    # S = periods 0..j ; non-S = j+1..k
                    for t in range(0, j + 1):
                        for xj in xs[(sk, t)]:
                            rows.append(r); cols.append(xj); vals.append(1.0)
                    for t in range(j + 1, k + 1):
                        dtk = Tk - T[t]
                        if dtk > 0:
                            rows.append(r)
                            cols.append(off + mp["y"][(sk, t)])
                            vals.append(dtk)
                    for u in range(0, k + 1):
                        rows.append(r)
                        cols.append(off + mp["y"][(sk, u)] + 1)
                        vals.append(1.0)
                    rhs.append(Tk); r += 1
    extra = coo_matrix((vals, (rows, cols)), shape=(r, mip.A.shape[1])).tocsr()
    new = MIP(mip.name, mip.c, vstack([mip.A.tocsr(), extra]).tocsr(),
              tuple(mip.sense) + ("G",) * r,
              np.concatenate([mip.rhs, np.array(rhs)]),
              mip.lb, mip.ub, mip.integrality)
    return new, r


def min_lot_violations(qtys, lots):
    bad = []
    per = {}
    for p_i, q in enumerate(qtys):
        for (sk, t, l), v in q.items():
            per[(p_i, sk, t)] = per.get((p_i, sk, t), 0.0) + v
    for k, v in per.items():
        L = lots.get(k)
        if L is not None and 1e-6 < v < L - 1e-6:
            bad.append(f"plant {k[0]} {k[1]} day {k[2]}: lot {v:.1f} < "
                       f"min {L:.1f}")
    return bad


def rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                 / 1024.0, 1)


def _sha():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(__file__)).stdout.strip()
    except Exception:
        return "unknown"


def runner_specs():
    """Measured machine spec: the failure point depends on it."""
    import platform
    spec = {"cpu_count": os.cpu_count(), "platform": platform.platform()}
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal"):
                spec["mem_total_mb"] = round(int(line.split()[1]) / 1024)
        spec["cpu_model"] = next(
            (l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo")
             if l.startswith("model name")), None)
    except OSError:
        pass
    return spec


def solve_highspy(mip, limit, threads, rel_gap=None):
    """Same MIP through highspy (HiGHS pinned to scipy's bundled
    version) with an explicit threads option and an improving-solution
    callback, which gives the time of the first incumbent."""
    import highspy
    import numpy as np
    lo = np.where(np.array(mip.sense) == "G", mip.rhs, -np.inf)
    hi = np.where(np.array(mip.sense) == "L", mip.rhs, np.inf)
    eq = np.array(mip.sense) == "E"
    lo[eq] = hi[eq] = mip.rhs[eq]
    A = mip.A.tocsr()
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = A.shape[1], A.shape[0]
    lp.col_cost_ = mip.c
    lp.col_lower_, lp.col_upper_ = mip.lb, mip.ub
    lp.row_lower_, lp.row_upper_ = lo, hi
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_ = A.indptr
    lp.a_matrix_.index_ = A.indices
    lp.a_matrix_.value_ = A.data
    lp.integrality_ = [highspy.HighsVarType.kInteger if v else
                       highspy.HighsVarType.kContinuous
                       for v in mip.integrality]
    h = highspy.Highs()
    h.setOptionValue("output_flag", True)   # callbacks need logging on
    h.setOptionValue("threads", int(threads))
    h.setOptionValue("time_limit", float(limit))
    h.setOptionValue("mip_rel_gap", float(
        os.environ.get("MS_REL_GAP", "1e-4") if rel_gap is None
        else rel_gap))
    for kv in filter(None, os.environ.get("MS_HIGHS_OPTS", "").split(",")):
        k, _, v = kv.partition("=")
        if v.lstrip("-").isdigit():
            v = int(v)
        elif v in ("true", "false"):
            v = v == "true"
        h.setOptionValue(k, v)
    h.passModel(lp)
    first = {}
    t0 = time.perf_counter()

    traj = []

    def cb(*a):
        first.setdefault("t", round(time.perf_counter() - t0, 2))

    def cblog(e):
        try:
            data_out = e.data_out
            g = data_out.mip_gap
            traj.append((round(time.perf_counter() - t0, 2),
                         data_out.mip_primal_bound,
                         data_out.mip_dual_bound, g))
        except Exception:
            pass
    h.cbMipImprovingSolution.subscribe(cb)
    h.cbMipLogging.subscribe(cblog)
    h.setOptionValue("log_to_console", False)
    h.run()
    info = h.getInfo()
    sol = h.getSolution()
    x = np.array(sol.col_value) if len(sol.col_value) else None
    ms = h.modelStatusToString(h.getModelStatus())
    ok = x is not None and info.primal_solution_status == 2
    return {"status": ms, "x": x if ok else None,
            "objective": float(mip.c @ x) if ok else None,
            "gap": info.mip_gap, "node_count": info.mip_node_count,
            "dual_bound": info.mip_dual_bound,
            "first_incumbent_s": first.get("t"),
            "time_to_gap_s": time_to_gap(traj),
            "trajectory_points": len(traj),
            "trajectory": traj[::max(1, len(traj) // 200)]}


def time_to_gap(traj):
    """First time the relative gap (HiGHS callback, |primal-dual| /
    |primal|) is at or below each threshold; None if never seen."""
    out = {}
    for name, thr in (("1%", 1e-2), ("0.1%", 1e-3), ("0.01%", 1e-4),
                      ("0.001%", 1e-5)):
        out[name] = next((t for t, pb, db, g in traj
                          if g is not None and g == g and g <= thr),
                         None)
    return out


def _solo(args):
    f, hs, days, cap, cap_solve = args
    b = solve_buckets(f, hs, days, cap, time_limit_s=cap_solve)
    if b.objective is None:
        return None
    return _plant_usage(f, b.qty)


def make_caps(ps, hs, days, cap, c, cap_solve, cls, n):
    """Binding shared caps = factor x usage of one solo plan per plant.
    Cached per (class, n) in /tmp; solo solves run in a process pool
    (deterministic: results are combined in plant order) when no other
    probe is running."""
    cache = Path(f"/tmp/caps-{cls}-{n}-{cap_solve:g}.json")
    if cache.exists():
        d = json.loads(cache.read_text())
        sup = {(k.split("|")[0], int(k.split("|")[1])): v
               for k, v in d["sup"].items()}
        lab = {int(k): v for k, v in d["lab"].items()}
        return sup, lab, d["unsolved"], "cache hit " + cache.name
    workers = int(os.environ.get("MS_CAP_WORKERS", "0")) or (
        1 if other_probes() else (os.cpu_count() or 1))
    args = [(p.factory, hs, days, cap, cap_solve) for p in ps]
    if workers > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(workers) as pool:
            res = pool.map(_solo, args, chunksize=4)
    else:
        res = [_solo(a) for a in args]
    mat_tot, lab_tot, unsolved = {}, {}, 0
    for r in res:                       # plant order: deterministic
        if r is None:
            unsolved += 1
            continue
        m_p, l_p = r
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
        for k, v in l_p.items():
            lab_tot[k] = lab_tot.get(k, 0.0) + v
    sup = {k: c["sup"] * v for k, v in mat_tot.items()}
    lab = {k: c["lab"] * v for k, v in lab_tot.items()}
    cache.write_text(json.dumps({
        "sup": {f"{k[0]}|{k[1]}": v for k, v in sup.items()},
        "lab": {str(k): v for k, v in lab.items()},
        "unsolved": unsolved}))
    return sup, lab, unsolved, f"computed with {workers} workers"


def other_probes():
    """Number of OTHER monolith_scaling processes running right now
    (parallel runs can slow each other through memory/cache)."""
    me, n = os.getpid(), 0
    for d in os.listdir("/proc"):
        if d.isdigit() and int(d) != me:
            try:
                cmd = open(f"/proc/{d}/cmdline", "rb").read()
            except OSError:
                continue
            if b"monolith_scaling.py" in cmd and b"python" in cmd.split(
                    b"\0")[0]:
                n += 1
    return n


def cpu_wall(fn):
    """Run fn, return (result, wall_s, avg_cores_used) from process
    CPU time (user+sys, children included) over wall time."""
    t0 = os.times()
    w0 = time.perf_counter()
    r = fn()
    t1 = os.times()
    w = time.perf_counter() - w0
    cpu = (t1.user - t0.user) + (t1.system - t0.system) + \
        (t1.children_user - t0.children_user) + \
        (t1.children_system - t0.children_system)
    return r, w, cpu / w if w > 0 else None


def main():
    n = int(os.environ["MS_N"])
    limit = float(os.environ.get("MS_LIMIT", "600"))
    cls = os.environ.get("MS_CLASS", "easy")
    cap_solve = float(os.environ.get("MS_CAP_SOLVE_S", "10"))
    out_path = os.environ.get("MS_OUT", "/tmp/monolith-scaling.json")
    c = CLASSES[cls]
    out = {"measured": True, "plants": n, "class": cls, "params": c,
           "solve_limit_s": limit, "first_plan_time_available": False,
           "stages": {}}

    def save(stage):
        out["stages"][stage] = {"t_s": round(time.perf_counter() - T0, 1),
                                "peak_rss_mb": rss_mb()}
        Path(out_path).write_text(json.dumps(out, indent=1))
        print(stage, out["stages"][stage], flush=True)

    T0 = time.perf_counter()
    ps = [generate_fnb_factory(FnbParams(
        seed=101 * (i + 1), n_lines=3, n_skus=c["n_skus"], days=c["days"],
        active_fraction=0.9, utilization=c["util"], n_raw_materials=6,
        families=("DAIRY", "BAKERY"))) for i in range(n)]
    hs = ps[0].params.horizon_start
    cap = ps[0].day_capacity_minutes
    factories = [p.factory for p in ps]
    days = c["days"]
    out["runner"] = runner_specs()
    out["code_sha"] = _sha()
    try:
        import scipy
        out["versions"] = {"scipy": scipy.__version__}
        import highspy
        out["versions"]["highspy"] = highspy.Highs().version()
    except Exception:
        pass
    save("generate")
    sup, lab, unsolved, caps_note = make_caps(ps, hs, days, cap, c,
                                              cap_solve, cls, n)
    out["plants_solo_unsolved"] = unsolved
    out["caps_note"] = caps_note
    save("caps")
    weights = None
    lot_fn = None
    if c.get("tbo"):
        import statistics
        from brain_core.rolling.two_level import (ObjectiveWeights,
                                                  EARLY_W)
        dd = sku_daily_demand(factories, hs, days)
        d_med = statistics.median(dd.values())
        S = c["tbo"] ** 2 * EARLY_W * d_med / 2.0
        weights = ObjectiveWeights(setup=S)
        out["calibration"] = {"median_daily_demand": d_med,
                              "holding_weight": EARLY_W,
                              "setup_weight": S, "target_tbo_days":
                              c["tbo"]}

        def lot_fn(p_i, sk, M):
            d = dd.get((p_i, sk), d_med)
            return min(0.9 * M, c["minlot_tbo"] * c["tbo"] * d)
    if c.get("setup_scale"):
        from brain_core.rolling.two_level import (ObjectiveWeights,
                                                  SETUP_W)
        weights = ObjectiveWeights(setup=SETUP_W * c["setup_scale"])
    mip, meta = build_coupled_mip(factories, hs, days, cap, sup, lab,
                                  weights=weights)
    lots = {}
    if c.get("minlot_frac") or lot_fn:
        mip, lots = add_min_lot(mip, meta, c.get("minlot_frac"), lot_fn)
        out["min_lot_rows"] = len(lots)
    if os.environ.get("MS_STRENGTH") == "ls":
        mip, n_ls = add_ls_cuts(mip, meta, factories, hs, days)
        out["strengthened"] = {"kind": "ls-prefix", "rows_added": n_ls}
    out["mip"] = {"rows": int(mip.A.shape[0]), "cols": int(mip.A.shape[1]),
                  "nnz": int(mip.A.nnz),
                  "binaries": int(mip.integrality.sum())}
    save("build")
    out["solves"] = {}
    res = None
    for spec in os.environ.get("MS_SOLVERS", "scipy").split(","):
        name, _, th = spec.partition(":")
        others_start = other_probes()
        if name == "scipy":
            r, w, cores = cpu_wall(lambda: solve_mip(
                mip, time_limit_s=limit, mip_rel_gap=0.0))
        else:
            r, w, cores = cpu_wall(lambda: solve_highspy(
                mip, limit, th or 4))
        rec = {"solve_wall_s": round(w, 1),
               "avg_cores_used": round(cores, 2),
               "status": str(r["status"]),
               "optimal_proven": "ptimal" in str(r["status"]),
               "has_incumbent": r["x"] is not None,
               "first_incumbent_s": r.get("first_incumbent_s"),
               "time_to_gap_s": r.get("time_to_gap_s"),
               "other_probes_at_solve_start": others_start,
               "other_probes_at_solve_end": other_probes(),
               "threads": int(th) if th else None,
               "highs_opts": os.environ.get("MS_HIGHS_OPTS", ""),
               "trajectory": r.get("trajectory"),
               "mip_rel_gap_setting": (0.0 if name == "scipy" else float(
                   os.environ.get("MS_REL_GAP", "1e-4")))}
        if r["x"] is not None:
            rec["incumbent"] = r["objective"]
            rec["mip_gap"] = r.get("gap")
            rec["nodes"] = r.get("node_count")
        out["solves"][spec] = rec
        out["stages"]["solve:" + spec] = {
            "t_s": round(time.perf_counter() - T0, 1),
            "peak_rss_mb": rss_mb()}
        if res is None:
            res = r
            out.update({k: rec[k] for k in rec})
            out["solve_wall_s"] = rec["solve_wall_s"]
            if rec.get("incumbent") and rec.get("mip_gap") is not None:
                out["derived_bound"] = rec["incumbent"] * (
                    1 - rec["mip_gap"])
        Path(out_path).write_text(json.dumps(out, indent=1))
    save("solve")
    if res["x"] is not None:
        qtys = qty_from_mip_x(res["x"], meta["maps"], meta["offsets"])
        problems, kpis = validate_coupled_plan(
            factories, qtys, hs, days, cap, supplier_cap=sup,
            labor_cap=lab)
        if lots:
            ml = min_lot_violations(qtys, lots)
            problems = problems + ml
            out["min_lot_violations"] = len(ml)
        out["validation_problems"] = problems[:20]
        out["validation_problem_count"] = len(problems)
        out["kpis"] = kpis
    save("validate")
    out["total_wall_s"] = round(time.perf_counter() - T0, 1)
    out["peak_rss_mb"] = rss_mb()
    Path(out_path).write_text(json.dumps(out, indent=1))
    print("DONE", out["status"], out.get("mip_gap"), out["peak_rss_mb"])


if __name__ == "__main__":
    main()
