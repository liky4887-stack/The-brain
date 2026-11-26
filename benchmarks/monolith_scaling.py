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
    t0 = time.perf_counter()
    res = solve_mip(mip, time_limit_s=limit, mip_rel_gap=0.0)
    out["solve_wall_s"] = round(time.perf_counter() - t0, 1)
    out["status"] = str(res["status"])
    out["optimal_proven"] = "Optimal" in str(res["status"])
    out["has_incumbent"] = res["x"] is not None
    if res["x"] is not None:
        out["incumbent"] = res["objective"]
        out["mip_gap"] = res.get("gap")
        out["nodes"] = res.get("node_count")
        if res.get("gap") is not None and res["objective"]:
            out["derived_bound"] = res["objective"] * (1 - res["gap"])
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
