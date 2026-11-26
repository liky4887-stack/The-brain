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
}


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
    mat_tot, lab_tot = {}, {}
    unsolved = 0
    for p in ps:
        b = solve_buckets(p.factory, hs, days, cap,
                          time_limit_s=cap_solve)
        if b.objective is None:
            unsolved += 1
            continue
        m_p, l_p = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
        for k, v in l_p.items():
            lab_tot[k] = lab_tot.get(k, 0.0) + v
    sup = {k: c["sup"] * v for k, v in mat_tot.items()}
    lab = {k: c["lab"] * v for k, v in lab_tot.items()}
    out["plants_solo_unsolved"] = unsolved
    save("caps")
    mip, meta = build_coupled_mip(factories, hs, days, cap, sup, lab)
    out["mip"] = {"rows": int(mip.A.shape[0]), "cols": int(mip.A.shape[1]),
                  "nnz": int(mip.A.nnz),
                  "binaries": int(mip.integrality.sum())}
    save("build")
    out["solves"] = {}
    res = None
    for spec in os.environ.get("MS_SOLVERS", "scipy").split(","):
        name, _, th = spec.partition(":")
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
