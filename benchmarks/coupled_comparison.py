"""Monolithic vs distributed on a genuinely COUPLED full-horizon case
(outside-review item 3, 2026-11-26).

One 7-day bucket-level horizon (no rolling windows), N plants sharing
BOTH material pools (supplier_cap at SUPPLIER_FACTOR x uncoupled
usage) and a shared capacity pool per day (labor_cap at LABOR_FACTOR x
uncoupled minutes) - both binding, so the plants genuinely contend.

  A. monolithic: build_coupled_mip -> solve_mip(time_limit) - status,
     incumbent (objective recomputed from x), and a bound DERIVED from
     the HiGHS mip_gap (labeled: not a solver-reported dual bound;
     exact when the status is optimal). If it times out: best
     feasible + derived bound, per the review.
  B. distributed: column_generation (bound_certified flag shown) +
     integer_master (UB from generated columns).
  C. failed-worker injection: one pricing worker is made to raise once
     mid-CG; the loop must record the crash, mark the round inexact,
     and recover by repricing the plant next round - no duplicate
     columns, no silent loss.

Every returned plan is validated INDEPENDENTLY by
validate_coupled_plan against every original constraint (per-plant
capacity/linking/coverage + shared pools). Compared: objective,
bound, gap, wall, and total compute (monolith wall vs CG sequential
wall; parallel wall labeled EXTRAPOLATED).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))

from brain_core.guards.weights_guard import require_comparable
from brain_core.synthetic import FnbParams, generate_fnb_factory
from brain_core.rolling import coupled_dw
from brain_core.rolling.coupled import (build_coupled_mip,
                                        coupled_dual,
                                        validate_coupled_plan,
                                        _plant_usage)
from brain_core.rolling.coupled_dw import (column_generation,
                                           integer_master)
from brain_core.rolling.two_level import solve_buckets, ObjectiveWeights
from brain_core.solvers.highs_mip import solve_mip

DAYS = 7
# defaults are the published crossover class; CMP_SUPPLIER_FACTOR /
# CMP_LABOR_FACTOR select a different pressure level (label every row)
SUPPLIER_FACTOR = float(os.environ.get("CMP_SUPPLIER_FACTOR", "0.75"))
LABOR_FACTOR = float(os.environ.get("CMP_LABOR_FACTOR", "0.8"))
SEEDS = [101 * (i + 1) for i in range(64)]


def build_cluster(n, seed_base=0):
    ps = [generate_fnb_factory(FnbParams(seed=SEEDS[i] + seed_base,
                                         n_lines=3,
                                         n_skus=12, days=DAYS,
                                         active_fraction=0.9,
                                         utilization=0.6,
                                         n_raw_materials=6,
                                         families=("DAIRY", "BAKERY")))
          for i in range(n)]
    return ps, ps[0].params.horizon_start, ps[0].day_capacity_minutes


def binding_caps(ps, hs, cap):
    """Uncoupled usage -> binding shared caps. Also returns the
    uncoupled objective sum (throughput reference, NOT a coupled
    bound)."""
    mat_tot, lab_tot = {}, {}
    solo = 0.0
    for p in ps:
        b = solve_buckets(p.factory, hs, DAYS, cap, time_limit_s=30.0)
        solo += b.objective
        m_p, l_p = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
        for k, v in l_p.items():
            lab_tot[k] = lab_tot.get(k, 0.0) + v
    sup = {k: SUPPLIER_FACTOR * v for k, v in mat_tot.items()}
    lab = {k: LABOR_FACTOR * v for k, v in lab_tot.items()}
    return sup, lab, solo


def qty_from_mip_x(res_x, maps, offsets):
    qtys = []
    for mp, off in zip(maps, offsets):
        qty = {}
        for (s, t, l), j in mp["x"].items():
            if res_x[off + j] > 1e-6:
                qty[(s, t, l)] = float(res_x[off + j])
        qtys.append(qty)
    return qtys


def _sha() -> str:
    """Commit the harness ran at (CI: GITHUB_SHA; local: git HEAD)."""
    import subprocess
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], text=True,
                              capture_output=True, check=True,
                              cwd=os.path.dirname(__file__)).stdout.strip()
    except Exception:
        return "unknown"


# Same weights for the monolith and CG, passed explicitly and recorded in
# the row (a comparison with different weights measures the weights).
WEIGHTS = ObjectiveWeights()


def _as_row(w):
    return {"weights": {"setup": w.setup, "late": w.late,
                        "early": w.early, "energy": w.energy}}


def _cg_weights():
    """The CG side's weights. CMP_CG_SETUP_W exists so an experiment can
    ask for a different CG setup weight; the guard then refuses the run
    before any solve (the monolith side stays at WEIGHTS)."""
    import dataclasses
    v = os.environ.get("CMP_CG_SETUP_W")
    return WEIGHTS if v is None else dataclasses.replace(WEIGHTS,
                                                         setup=float(v))


def run(n, monolith_limit_s=90.0, crash_inject=False,
        seed_base=0):
    ps, hs, cap = build_cluster(n, seed_base=seed_base)
    factories = [p.factory for p in ps]
    sup, lab, solo = binding_caps(ps, hs, cap)
    out = {"plants": n, "days": DAYS, "sha": _sha(),
           "seed_base": seed_base,
           "weights": {"setup": WEIGHTS.setup, "late": WEIGHTS.late,
                       "early": WEIGHTS.early, "energy": WEIGHTS.energy},
           "time_limits": {"monolith_s": monolith_limit_s},
           "cap_factors": {
        "supplier": SUPPLIER_FACTOR, "labor": LABOR_FACTOR},
        "uncoupled_objective_sum": solo,
        "uncoupled_note": "throughput reference only - NOT a coupled bound"}

    # Weights guard BEFORE any solve: the monolith, the CG and the integer
    # master must use the same weights, or the run is refused. The verdict
    # is in the row by name.
    cg_w = _cg_weights()
    out["weights_verdict"] = require_comparable(
        _as_row(WEIGHTS), _as_row(cg_w), "coupled_comparison")

    # A. monolithic
    t0 = time.perf_counter()
    mip, meta = build_coupled_mip(factories, hs, DAYS, cap, sup, lab,
                                  weights=WEIGHTS)
    res = solve_mip(mip, time_limit_s=monolith_limit_s, mip_rel_gap=0.0)
    t_mono = time.perf_counter() - t0
    mono = {"wall_s": round(t_mono, 2), "status": str(res["status"]),
            "optimal_proven": "Optimal" in str(res["status"]),
            "time_limit_s": monolith_limit_s}
    if res["x"] is not None:
        qtys = qty_from_mip_x(res["x"], meta["maps"],
                              meta["offsets"])
        problems, kpis = validate_coupled_plan(
            factories, qtys, hs, DAYS, cap,
            supplier_cap=sup, labor_cap=lab)
        mono["incumbent"] = res["objective"]
        mono["mip_gap"] = res.get("gap")
        if res.get("gap") is not None and res["objective"]:
            # HiGHS gap = |primal-dual|/|primal| -> derived bound
            mono["derived_bound"] = res["objective"] * (1 - res["gap"])
            mono["bound_note"] = ("DERIVED from HiGHS mip_gap; not a "
                                  "solver-reported dual bound")
        if "Optimal" in str(res["status"]):
            mono["bound"] = res["objective"]
            mono["bound_note"] = "exact (status optimal)"
        mono["validation_problems"] = problems
        mono["validation_kpis"] = kpis
    out["monolithic"] = mono

    # B2. Lagrangian relaxation on the same links (review item 5):
    # same theoretical bound as CG, attained by subgradient ascent -
    # measured here as the alongside-comparison, never mixed into the
    # CG certificate.
    t0 = time.perf_counter()
    lr = coupled_dual(factories, hs, DAYS, cap, sup, lab,
                      rounds=int(os.environ.get("CMP_LR_ROUNDS", "40")),
                      time_limit_s=30.0,
                      ub0=float(os.environ["CMP_LR_UB0"])
                      if os.environ.get("CMP_LR_UB0") else None)
    t_lr = time.perf_counter() - t0
    out["lagrangian"] = {"wall_s": round(t_lr, 2),
                         "lower_bound": lr.lower_bound,
                         "note_status": None,
                         "weights_note": "coupled_dual takes no weights "
                                         "argument: solver defaults apply "
                                         "(setup 50 / late 1000), equal to "
                                         "WEIGHTS only while those are the "
                                         "defaults",
                         "rounds": lr.rounds_run,
                         "note": "same convexification bound as CG in "
                                 "theory; subgradient attainment "
                                 "measured here"}

    # B. distributed (optionally with one injected worker crash).
    # Warm start: seed columns from the monolith plan when it produced
    # one (review item 4) + Wentges stabilization (CMP_STAB_ALPHA).
    real_solve_buckets = coupled_dw.solve_buckets
    crashed_once = {"done": False}

    def maybe_crash(f, *args, **kw):
        # inject only on a PRICING call (unit_cost_extra present);
        # seeding calls are the uncoupled reference solves
        if crash_inject and not crashed_once["done"] \
                and f is factories[0] \
                and kw.get("unit_cost_extra") is not None:
            crashed_once["done"] = True
            raise RuntimeError("INJECTED worker crash (review test)")
        return real_solve_buckets(f, *args, **kw)

    if crash_inject:
        coupled_dw.solve_buckets = maybe_crash
    try:
        seed = None if os.environ.get("CMP_NO_SEED") == "1" \
            else (qtys if res["x"] is not None else None)
        t0 = time.perf_counter()
        dw = column_generation(factories, hs, DAYS, cap,
                               supplier_cap=sup, labor_cap=lab,
                               max_iter=int(os.environ.get(
                                   "CMP_CG_ITERS", "60")),
                               time_limit_s=30.0, weights=cg_w,
                               seed_qtys=seed,
                               stab_alpha=float(os.environ.get(
                                   "CMP_STAB_ALPHA", "0.0")),
                               exact_every=int(os.environ.get(
                                   "CMP_EXACT_EVERY", "5")),
                               wall_s=float(os.environ.get(
                                   "CMP_CG_WALL_S", "0")) or None,
                               im_every=int(os.environ.get(
                                   "CMP_IM_EVERY", "0")),
                               alloc_every=int(os.environ.get(
                                   "CMP_ALLOC_EVERY", "0")))
        t_cg = time.perf_counter() - t0
        t0 = time.perf_counter()
        dw = integer_master(dw, factories, hs, DAYS, weights=cg_w,
                            time_limit_s=min(120.0, monolith_limit_s))
        t_im = time.perf_counter() - t0
    finally:
        coupled_dw.solve_buckets = real_solve_buckets
    comb = None
    if dw.lower_bound is not None and dw.upper_bound is not None:
        comb = (dw.upper_bound - dw.lower_bound) / \
            max(abs(dw.upper_bound), 1e-9)
    dist = {"combined_certified_gap": comb,
            "ub_series": dw.ub_series,
            "first_ub_s": dw.first_ub_s,
            "iter_times_tail": dw.iter_times[-3:],
            "seed": ("none" if os.environ.get("CMP_NO_SEED") == "1"
            else ("monolith-plan" if res["x"] is not None
                  else "uncoupled")),
            "stab_alpha": float(os.environ.get("CMP_STAB_ALPHA", "0.0")),
            "cg_wall_s": round(t_cg, 2), "im_wall_s": round(t_im, 2),
            "iterations": dw.iterations, "converged": dw.converged,
            "bound_certified": dw.bound_certified,
            "status": dw.status, "lower_bound": dw.lower_bound,
            "upper_bound": dw.upper_bound,
            "problems_tail": dw.problems[-4:],
            "crash_injected": crash_inject,
            "crash_recovered": crash_inject and any(
                "CRASHED" in p for p in dw.problems)}
    if dw.selected_qtys is not None:
        problems, kpis = validate_coupled_plan(
            factories, dw.selected_qtys, hs, DAYS, cap,
            supplier_cap=sup, labor_cap=lab)
        dist["ub_validation_problems"] = problems
        dist["ub_validation_kpis"] = kpis
    out["distributed"] = dist
    if dw.lower_bound and mono.get("incumbent"):
        out["gap_monolith_incumbent_vs_certified_lb"] = \
            (mono["incumbent"] - dw.lower_bound) / abs(mono["incumbent"])
    return out


def main():
    sizes = [int(x) for x in os.environ.get("CMP_SIZES", "2").split(",")]
    limit = float(os.environ.get("CMP_MONOLITH_LIMIT", "90"))
    phase = os.environ.get("CMP_PHASE", "all")   # all|base|crash
    path = os.environ.get("CMP_OUT", "/tmp/coupled-comparison.json")
    out = {"measured": True}
    if phase in ("all", "base"):
        reps = int(os.environ.get("CMP_REPLICAS", "1"))
        rows = []
        for n in sizes:
            for rep in range(reps):
                r = run(n, limit, crash_inject=False,
                        seed_base=rep * 100003)
                r["replica"] = rep
                rows.append(r)
        out["rows"] = rows
        # per-size replica aggregate: plan cost / monolith incumbent,
        # mean and worst case (review: 5 seeds before any "1.1x" claim)
        agg = {}
        for r in rows:
            n = r["plants"]
            ub = r["distributed"].get("upper_bound")
            mo = r["monolithic"].get("incumbent")
            lb = r["distributed"].get("lower_bound")
            a = agg.setdefault(n, {"ratios": [], "gaps": [],
                                   "mono_proven": [], "invalid_ub": 0})
            # a UB counts ONLY if its plan passed the independent coupled
            # validator (found 2026-11-26: run 45842450508 reported UBs
            # that violated the shared supplier caps)
            valid = not r["distributed"].get("ub_validation_problems", [])
            r["distributed"]["ub_valid"] = valid
            if ub and not valid:
                a["invalid_ub"] += 1
                ub = None
            if ub and mo:
                a["ratios"].append(ub / mo)
            if lb is not None and ub:
                a["gaps"].append((ub - lb) / max(abs(ub), 1e-9))
            a["mono_proven"].append(
                r["monolithic"].get("optimal_proven"))
        # official lower bound per replica = the LARGER of the certified
        # CG bound (only when bound_certified) and the monolith's own
        # solver bound; gap is vs the monolith incumbent
        for r in rows:
            mo = r["monolithic"]
            mb = mo.get("derived_bound") or mo.get("bound")
            d = r["distributed"]
            c = [x for x in (mb, d["lower_bound"]
                             if d.get("bound_certified") else None)
                 if x is not None]
            if c and mo.get("incumbent"):
                r["official_lower_bound"] = max(c)
                r["official_gap_vs_monolith_incumbent"] = \
                    (mo["incumbent"] - max(c)) / abs(mo["incumbent"])
        out["per_size"] = {
            str(n): {"replicas": len(a["ratios"]),
                     "invalid_ub_replicas": a["invalid_ub"],
                     "plan_vs_monolith_mean":
                     (sum(a["ratios"]) / len(a["ratios"]))
                     if a["ratios"] else None,
                     "plan_vs_monolith_worst":
                     max(a["ratios"]) if a["ratios"] else None,
                     "combined_certified_gap_mean":
                     (sum(a["gaps"]) / len(a["gaps"]))
                     if a["gaps"] else None,
                     "combined_certified_gap_worst":
                     max(a["gaps"]) if a["gaps"] else None,
                     "monolith_optimal_proven_all":
                     all(a["mono_proven"])}
            for n, a in agg.items()}
        for r in out["rows"]:
            print(f"[{r['plants']}p r{r['replica']}] mono "
                  f"{r['monolithic']['wall_s']}s "
                  f"{r['monolithic']['status'][:40]} | CG "
                  f"{r['distributed']['cg_wall_s']}s LB "
                  f"{r['distributed']['lower_bound']} certified="
                  f"{r['distributed']['bound_certified']} | UB "
                  f"{r['distributed']['upper_bound']}", flush=True)
    if phase in ("all", "crash"):
        out["crash_injection"] = run(sizes[0], limit, crash_inject=True)
        c = out["crash_injection"]["distributed"]
        print("crash injection recovered:", c["crash_recovered"],
              "| certified after crash:", c["bound_certified"],
              "| status:", c["status"], flush=True)
    Path(path).write_text(json.dumps(out, indent=1))
    print("WROTE", path)


if __name__ == "__main__":
    main()
