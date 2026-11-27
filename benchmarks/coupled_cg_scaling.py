"""Phase D column-generation scaling measurement (the master-worker
architecture). Same clusters/seeds as coupled_scaling.py (2/4/8/16
plants, 0.75x binding supplier caps); measures per size:
  - CG wall (sequential pricing: rounds x sum of plant solves),
    iterations, columns, converged flag, proven LB
  - integer restricted master wall, incumbent UB
  - proven gap (LB vs UB, both independent)
Also records the EXTRAPOLATED parallel wall (rounds x slowest plant
solve, dispatch overhead NOT included) for the fabric mapping.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))

from brain_core.synthetic import FnbParams, generate_fnb_factory
from brain_core.rolling.two_level import solve_buckets, ObjectiveWeights
from brain_core.rolling.coupled import _plant_usage
from brain_core.rolling.coupled_dw import (column_generation,
                                           integer_master)

DAYS = 7
CAP_FACTOR = 0.75
# Primal: alloc_every=0 leaves only the columns-only integer master, which
# measured UB 118,373,179 vs LB 60,940,576 (proven gap 0.485) on size 2
# while alloc_every=5 gave UB 60,941,104 (gap ~8.7e-6), same LB. A row with
# alloc_every=0 is 'primal not meaningful'.
WEIGHTS = ObjectiveWeights()   # passed explicitly and recorded in each row
ALLOC_EVERY = int(__import__('os').environ.get('CG_ALLOC_EVERY', '5'))
SEEDS = [101 * (i + 1) for i in range(16)]


def build_cluster(n):
    ps = [generate_fnb_factory(FnbParams(seed=SEEDS[i], n_lines=4,
                                         n_skus=12, days=2,
                                         active_fraction=0.9,
                                         utilization=0.6,
                                         n_raw_materials=6,
                                         families=("DAIRY", "BAKERY")))
          for i in range(n)]
    return ps, ps[0].params.horizon_start, \
        ps[0].day_capacity_minutes


def binding_caps(ps, hs, cap):
    mat_tot = {}
    slowest = 0.0
    for p in ps:
        t0 = time.perf_counter()
        b = solve_buckets(p.factory, hs, DAYS, cap, time_limit_s=30.0)
        slowest = max(slowest, time.perf_counter() - t0)
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    return {k: CAP_FACTOR * v for k, v in mat_tot.items()}, slowest


def run_one(n, mode):
    ps, hs, cap = build_cluster(n)
    caps, slowest = binding_caps(ps, hs, cap)
    dw = None
    t_cg = t_im = None
    if mode in ("cg", "both"):
        t0 = time.perf_counter()
        dw = column_generation([p.factory for p in ps], hs, DAYS, cap,
                               supplier_cap=caps, max_iter=60,
                               time_limit_s=30.0, alloc_every=ALLOC_EVERY, weights=WEIGHTS)
        t_cg = time.perf_counter() - t0
    if mode in ("im", "both"):
        if dw is None:
            dw = column_generation([p.factory for p in ps], hs, DAYS,
                                   cap, supplier_cap=caps, max_iter=60,
                                   time_limit_s=30.0,
                                   alloc_every=ALLOC_EVERY, weights=WEIGHTS)
        t0 = time.perf_counter()
        dw = integer_master(dw, [p.factory for p in ps], hs, DAYS,
                            time_limit_s=240.0, weights=WEIGHTS)
        t_im = time.perf_counter() - t0
    return dw, t_cg, t_im, slowest


def measure_row(n, mode):
    """One size end to end -> a plain JSON row (picklable, small: the
    DWResult with its column sets stays in the child)."""
    t_wall0 = time.perf_counter()
    dw, t_cg, t_im, slowest = run_one(n, mode)
    return {
        "plants": n, "seeds": SEEDS[:n], "cap_factor": CAP_FACTOR,
        "alloc_every": ALLOC_EVERY,
        "weights": {"setup": WEIGHTS.setup, "late": WEIGHTS.late,
                    "early": WEIGHTS.early, "energy": WEIGHTS.energy},
        "primal_note": ("primal not meaningful (alloc_every=0: columns-only "
                        "integer master)" if not ALLOC_EVERY else "ok"),
        "cg": {"wall_s": round(t_cg, 3) if t_cg is not None else None,
               "iterations": dw.iterations,
               "columns_per_plant": dw.columns_per_plant,
               "converged": dw.converged, "status": dw.status,
               "bound_certified": dw.bound_certified,
               "lower_bound": dw.lower_bound},
        "integer_master": {"wall_s": round(t_im, 3) if t_im is not None else None,
                           "upper_bound": dw.upper_bound},
        # ALL problems, not the last 3: a guard finding must never be
        # cut off the record
        "problems": list(dw.problems),
        "n_problems": len(dw.problems),
        "proven_gap": dw.proven_gap,
        "parallel_wall_extrapolated_s":
            round(dw.iterations * slowest, 2),
        "parallel_wall_note": "EXTRAPOLATED: iterations x slowest "
            "single-plant solve; dispatch overhead not included",
        "step_wall_s": round(time.perf_counter() - t_wall0, 3),
    }


def _git_sha():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parent,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main():
    import os
    from brain_core.guards.anomaly import check_record
    from brain_core.guards.durable import write_run_json
    from brain_core.guards.manifest import (Manifest, assert_manifest,
                                            observed_environment, stamp)
    from brain_core.guards.watchdog import run_step
    sizes = [int(x) for x in
             os.environ.get("CG_SIZES", "2,4,8,16").split(",")]
    mode = os.environ.get("CG_MODE", "both")
    step_timeout = float(os.environ.get("CG_STEP_TIMEOUT_S", "1800"))
    # no CG iteration for this long -> 'stalled' (one CG solve is
    # capped at 30 s, the integer master at 240 s); 0 disables
    stall = float(os.environ.get("CG_STALL_S", "900")) or None
    out_path = os.environ.get("CG_OUT", "/tmp/coupled-cg-scaling.json")
    env = observed_environment()
    manifest = Manifest({"runner": "coupled_cg_scaling", "days": DAYS,
                         "cap_factor": CAP_FACTOR, "mode": mode,
                         "max_iter": 60, "cg_time_limit_s": 30.0,
                         "im_time_limit_s": 240.0,
                         "git_sha": _git_sha(), **env})
    rows = []
    for n in sizes:
        # self-check before EVERY step: the code, the libraries and the
        # constants this row will be filed under are still the declared
        # ones (a mid-run pull or pip upgrade stops the run here)
        assert_manifest(manifest, {"runner": "coupled_cg_scaling",
                                   "days": DAYS, "cap_factor": CAP_FACTOR,
                                   "mode": mode, "max_iter": 60,
                                   "cg_time_limit_s": 30.0,
                                   "im_time_limit_s": 240.0,
                                   "git_sha": _git_sha(),
                                   **observed_environment()},
                        f"{n} plants")
        r = run_step(f"cg {n} plants", measure_row, (n, mode),
                     timeout_s=step_timeout, stall_s=stall)
        if r.status != "ok":
            row = {"plants": n, "seeds": SEEDS[:n], "status": r.status,
                   "detail": r.detail, "step_wall_s": round(r.wall_s, 3),
                   "measured": False}
            findings = [("step_failed", f"{r.status}: {r.detail[:300]}")]
        else:
            row = r.value
            rec = {"status": row["cg"]["status"],
                   "incumbent": row["integer_master"]["upper_bound"],
                   "bound": row["cg"]["lower_bound"],
                   "proven_gap": row["proven_gap"]}
            findings = [(x.rule, x.detail) for x in check_record(rec)
                        if not (rec["incumbent"] is None
                                and x.detail == "incumbent missing")]
            findings += [("invariant", p) for p in row["problems"]
                         if p.startswith("invariant")]
        row["guard_findings"] = findings
        rows.append(stamp(row, manifest))
        # after EVERY size, atomically, mirrored off /tmp: a kill at
        # size 16 keeps sizes 2..8 (before: one write at the very end)
        write_run_json(out_path, {"measured": True, "complete": False,
                                  "manifest_hash": manifest.hash(),
                                  "rows": rows})
        print(f"[done] {n} plants: {row.get('cg', row.get('status'))} "
              f"UB={row.get('integer_master', {}).get('upper_bound')} "
              f"gap={row.get('proven_gap')} findings={findings}",
              flush=True)
    write_run_json(out_path, {"measured": True, "complete": True,
                              "manifest_hash": manifest.hash(),
                              "rows": rows})
    print("WROTE", out_path, flush=True)


if __name__ == "__main__":
    main()
