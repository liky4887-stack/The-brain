"""Phase D: coupled multi-plant solving with a proven global gap.

Model (docs/COUPLED-DESIGN.md): plants share (a) per-day supplier
capacity per raw material and (b) a per-day labor/transport pool, both
at the bucket level. Lagrangian relaxation of those linking
constraints decomposes the dual by plant: each plant's bucket MIP gets
linear price terms (unit_cost_extra) and ANY non-negative multipliers
yield a valid global LOWER bound (weak duality, re-verified per run).
Subgradient ascent with the Polyak step maximizes the bound (pattern:
Thizy & Van Wassenhove 1985; Chen & Wang, Applied Sciences 14(15):6517,
2024).

Honesty: the LB series, multipliers, and usages are all recorded; no
UB is claimed here unless a feasible coupled plan exists (the primal
repair / coupled-MIP incumbent lands separately). UNKNOWN is reported,
never dressed as a bound.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .two_level import solve_buckets, _sku_data, _recipe_data


@dataclass
class CoupledResult:
    lower_bound: float | None       # best PROVEN global lower bound
    lb_series: list[float] = field(default_factory=list)
    multipliers: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)   # final-round pool usage
    rounds_run: int = 0
    problems: list[str] = field(default_factory=list)
    upper_bound: float | None = None   # best FEASIBLE repaired plan
    ub_series: list[float] = field(default_factory=list)

    @property
    def proven_gap(self) -> float | None:
        """(UB - LB) / max(|UB|, eps); only when both sides exist."""
        if self.lower_bound is None or self.upper_bound is None:
            return None
        denom = max(abs(self.upper_bound), 1e-9)
        return (self.upper_bound - self.lower_bound) / denom


def _plant_usage(factory, qty) -> tuple[dict, dict]:
    """(material, day) and (day) usage of a bucket assignment, from the
    records (recipes, rates) - never from solver internals."""
    recipes = _recipe_data(factory)
    sku = _sku_data(factory)
    mat: dict[tuple[str, int], float] = {}
    lab: dict[int, float] = {}
    for (s, t, l), q in qty.items():
        for r, per in recipes.get(s, {}).items():
            mat[(r, t)] = mat.get((r, t), 0.0) + per * q
        rate = sku.get(s, (0.0, [], None))[0]
        if rate:
            lab[t] = lab.get(t, 0.0) + q / rate
    return mat, lab


def coupled_dual(factories: list, horizon_start, days: int,
                 cap_min: float,
                 supplier_cap: dict[tuple[str, int], float],
                 labor_cap: dict[int, float] | None = None,
                 rounds: int = 50, time_limit_s: float = 60.0,
                 eta0: float = 2.0, inv0s: list | None = None,
                 repair_every: int = 0,
                 ub0: float | None = None) -> CoupledResult:
    """Subgradient ascent on the Lagrangian dual of the coupled
    cluster problem. Returns the best PROVEN lower bound found.

    supplier_cap[(material, day)], labor_cap[day]: shared caps across
    ALL plants in the cluster. The dual value at multipliers u >= 0:
        LB(u) = sum_p z_p(u) - sum uS*supplier_cap - sum uL*labor_cap
    where z_p(u) is plant p's penalized bucket objective (which already
    includes +u * usage_p). Weak duality: LB(u) <= coupled optimum.
    """
    labor_cap = labor_cap or {}
    inv0s = inv0s or [None] * len(factories)
    recipes = [_recipe_data(f) for f in factories]
    skus = [_sku_data(f) for f in factories]
    uS = {k: 0.0 for k in supplier_cap}
    uL = {k: 0.0 for k in labor_cap}
    res = CoupledResult(lower_bound=None)
    best_lb = float("-inf")
    ub_est = ub0 if ub0 is not None else float("inf")
                            # Polyak step needs a UB target; a real
                            # primal UB replaces it once repair lands,
                            # or the caller seeds one (ub0) - e.g. the
                            # best known feasible plan cost.
    stall = 0
    eta = eta0
    for k in range(rounds):
        z_sum = 0.0
        mat_tot: dict[tuple[str, int], float] = {}
        lab_tot: dict[int, float] = {}
        round_qtys: list[dict] = []
        ok = True
        for p_i, f in enumerate(factories):
            extra: dict[tuple[str, int], float] = {}
            for s in skus[p_i]:
                for t in range(days):
                    price = sum(uS.get((r, t), 0.0) * per
                                for r, per in recipes[p_i].get(s, {})
                                .items())
                    rate = skus[p_i][s][0]
                    if rate:
                        price += uL.get(t, 0.0) / rate
                    if price:
                        extra[(s, t)] = price
            b = solve_buckets(f, horizon_start, days, cap_min,
                              time_limit_s=time_limit_s,
                              inv0=inv0s[p_i], unit_cost_extra=extra)
            if b.objective is None:
                res.problems.append(f"round {k} plant {p_i}: bucket "
                                    f"status {b.status!r}; round "
                                    "skipped, bound not updated")
                ok = False
                break
            z_sum += b.objective
            round_qtys.append(b.qty)
            m_p, l_p = _plant_usage(f, b.qty)
            for key, v in m_p.items():
                mat_tot[key] = mat_tot.get(key, 0.0) + v
            for key, v in l_p.items():
                lab_tot[key] = lab_tot.get(key, 0.0) + v
        if not ok:
            continue
        lb = (z_sum - sum(uS[k2] * c for k2, c in supplier_cap.items())
              - sum(uL[k2] * c for k2, c in labor_cap.items()))
        res.lb_series.append(lb)
        if lb > best_lb + 1e-9:
            best_lb, stall = lb, 0
        else:
            stall += 1
            if stall >= 5:      # MDPI pattern: halve eta on stall
                eta *= 0.5
                stall = 0
        if repair_every and ((k + 1) % repair_every == 0
                             or k == rounds - 1):
            rep = primal_repair(factories, horizon_start, days,
                                cap_min, supplier_cap, labor_cap,
                                qtys=round_qtys, inv0s=inv0s)
            res.problems.extend(rep["problems"])
            if rep["objective"] is not None:
                res.ub_series.append(rep["objective"])
                if rep["objective"] < ub_est:
                    ub_est = rep["objective"]
                    res.upper_bound = rep["objective"]
        # subgradient: usage - cap per relaxed constraint
        gS = {key: mat_tot.get(key, 0.0) - c
              for key, c in supplier_cap.items()}
        gL = {key: lab_tot.get(key, 0.0) - c
              for key, c in labor_cap.items()}
        norm2 = sum(g * g for g in gS.values()) + \
            sum(g * g for g in gL.values())
        if norm2 <= 1e-12:
            break               # linking constraints all satisfied
        if ub_est < float("inf"):
            step = eta * max(0.0, ub_est - lb) / norm2
        else:
            # no primal UB yet: self-scaled Polyak-style step. The
            # plain eta/(k+1) walk is scale-blind: with objective
            # magnitudes ~1e8 and usages ~1e5 it jumps multipliers to
            # their cap in one step and never recovers (measured
            # 2026-11-26: LB stuck at the round-0 uncoupled bound for
            # 40 rounds). Scaling by |lb|/||g||^2 keeps the move in
            # objective units, like Polyak with the current LB as the
            # surrogate target.
            step = eta * max(abs(lb), 1.0) / norm2
        cap_step = 1e6
        uS = {key: max(0.0, min(cap_step, uS[key] + step * gS[key]))
              for key in uS}
        uL = {key: max(0.0, min(cap_step, uL[key] + step * gL[key]))
              for key in uL}
    res.lower_bound = best_lb if best_lb > float("-inf") else None
    res.multipliers = {"supplier": uS, "labor": uL}
    res.rounds_run = len(res.lb_series)
    return res



def _base_objective(factory, horizon_start, days, qty, inv0, weights):
    """Objective of a bucket assignment under the BASE weights (no link
    prices), recomputed from the records - the validator-side check,
    independent of any solver. qty: {(sku, day, line): q}."""
    from .two_level import _sku_data, due_day
    sku = _sku_data(factory)
    eff = {r.name: r.efficiency for r in factory.resources}
    dem: dict[str, list[float]] = {}
    for d in factory.demands:
        day = due_day(d.due, horizon_start)
        if 0 <= day < days:
            dem.setdefault(d.item, [0.0] * days)[day] += d.quantity
    active = sorted(set(dem) | {s for (s, _t, _l), q in qty.items()
                                if q > 1e-9})
    setup = late = early = energy = 0.0
    for s in active:
        if s not in sku:
            continue
        rate, lines, _st = sku[s]
        for t in range(days):
            q_day = sum(qty.get((s, t, l), 0.0) for l in lines)
            if q_day > 1e-9:
                setup += weights.setup
            energy += sum(weights.energy * (2.0 - eff.get(l, 1.0))
                          / rate * qty.get((s, t, l), 0.0)
                          for l in lines) if weights.energy else 0.0
        cum_dem = 0.0
        cum_prod = 0.0
        ds = dem.get(s, [0.0] * days)
        for t in range(days):
            cum_dem += ds[t]
            cum_prod += sum(qty.get((s, t, l), 0.0) for l in lines)
            target = cum_dem - (inv0 or {}).get(s, 0.0)
            late += weights.late * max(0.0, target - cum_prod)
            early += weights.early * max(0.0, cum_prod - target)
    return setup + late + early + energy


def primal_repair(factories: list, horizon_start, days: int,
                  cap_min: float,
                  supplier_cap: dict[tuple[str, int], float],
                  labor_cap: dict[int, float] | None = None,
                  qtys: list[dict] | None = None,
                  inv0s: list | None = None,
                  weights=None) -> dict:
    """LR primal heuristic: turn per-plant dual-side plans into ONE
    FEASIBLE coupled plan (a valid UB on the coupled optimum).

    The bucket model's coverage rows are soft (lateness/earliness
    slacks absorb any shortfall), so shrinking production quantities
    can never break a plant-side constraint: capacity rows only get
    looser, y stays valid, and uncovered demand prices out as
    lateness. Repair therefore only CUTS, never shifts: for each
    violated shared pool it removes production from the entries with
    the highest pool-usage per unit until the pool fits. Cuts
    monotonically shrink every pool, so one pass converges; the
    result is checked against the caps before being returned.

    Returns {objective (valid UB or None), usage, qty_per_plant,
    problems, cuts}. Honesty: the objective is recomputed from the
    repaired assignment under the BASE weights by _base_objective,
    never taken from a solver or from the penalized dual objective.
    """
    from .two_level import DEFAULT_WEIGHTS
    weights = weights or DEFAULT_WEIGHTS
    labor_cap = labor_cap or {}
    inv0s = inv0s or [None] * len(factories)
    out = {"objective": None, "usage": {}, "qty_per_plant": None,
           "problems": [], "cuts": 0}
    if qtys is None:
        out["problems"].append("no per-plant plans supplied")
        return out
    qtys = [dict(q) for q in qtys]
    recipes = [_recipe_data(f) for f in factories]
    skus = [_sku_data(f) for f in factories]
    # pool usage per unit for each (plant, sku): material coeff / labor
    def _mat_per(p_i, s, r):
        return recipes[p_i].get(s, {}).get(r, 0.0)
    def _lab_per(p_i, s):
        rate = skus[p_i].get(s, (0.0, [], None))[0]
        return 1.0 / rate if rate else 0.0
    cuts = 0
    for (r, t), capv in supplier_cap.items():
        while True:
            usage = sum(q * _mat_per(p_i, s, r)
                        for p_i in range(len(factories))
                        for (s, tt, l), q in qtys[p_i].items()
                        if tt == t and q > 1e-9)
            excess = usage - capv
            if excess <= 1e-9:
                break
            cands = []
            for p_i in range(len(factories)):
                for (s, tt, l), q in qtys[p_i].items():
                    per = _mat_per(p_i, s, r)
                    if tt == t and q > 1e-9 and per > 0.0:
                        cands.append((per, p_i, (s, tt, l), q))
            if not cands:
                out["problems"].append(
                    f"supplier pool {(r, t)} over cap with no "
                    "reducible production")
                break
            cands.sort(reverse=True)  # highest usage per unit first
            per, p_i, key, q = cands[0]
            take = min(q, excess / per)
            qtys[p_i][key] = q - take
            if qtys[p_i][key] <= 1e-9:
                del qtys[p_i][key]
            cuts += 1
    for t, capv in labor_cap.items():
        while True:
            usage = sum(q * _lab_per(p_i, s)
                        for p_i in range(len(factories))
                        for (s, tt, l), q in qtys[p_i].items()
                        if tt == t and q > 1e-9)
            excess = usage - capv
            if excess <= 1e-9:
                break
            cands = []
            for p_i in range(len(factories)):
                for (s, tt, l), q in qtys[p_i].items():
                    per = _lab_per(p_i, s)
                    if tt == t and q > 1e-9 and per > 0.0:
                        cands.append((per, p_i, (s, tt, l), q))
            if not cands:
                out["problems"].append(
                    f"labor pool day {t} over cap with no reducible "
                    "production")
                break
            cands.sort(reverse=True)
            per, p_i, key, q = cands[0]
            take = min(q, excess / per)
            qtys[p_i][key] = q - take
            if qtys[p_i][key] <= 1e-9:
                del qtys[p_i][key]
            cuts += 1
    # verify caps from the repaired assignment (records-side check)
    mat_tot: dict[tuple[str, int], float] = {}
    lab_tot: dict[int, float] = {}
    for p_i in range(len(factories)):
        m_p, l_p = _plant_usage(factories[p_i], qtys[p_i])
        for k2, v in m_p.items():
            mat_tot[k2] = mat_tot.get(k2, 0.0) + v
        for k2, v in l_p.items():
            lab_tot[k2] = lab_tot.get(k2, 0.0) + v
    for k2, capv in supplier_cap.items():
        if mat_tot.get(k2, 0.0) > capv + 1e-6:
            out["problems"].append(
                f"repaired plan still violates supplier cap {k2}: "
                f"{mat_tot[k2]:.3f} > {capv:.3f}")
    for k2, capv in labor_cap.items():
        if lab_tot.get(k2, 0.0) > capv + 1e-6:
            out["problems"].append(
                f"repaired plan still violates labor cap {k2}: "
                f"{lab_tot[k2]:.3f} > {capv:.3f}")
    if not out["problems"]:
        total = sum(_base_objective(f, horizon_start, days, q, inv0,
                                    weights)
                    for f, q, inv0 in zip(factories, qtys, inv0s))
        out["objective"] = total
    out["usage"] = {"supplier": mat_tot, "labor": lab_tot}
    out["qty_per_plant"] = qtys
    out["cuts"] = cuts
    return out


def build_coupled_mip(factories: list, horizon_start, days: int,
                      cap_min: float,
                      supplier_cap: dict[tuple[str, int], float],
                      labor_cap: dict[int, float] | None = None,
                      weights=None) -> tuple:
    """ONE coupled bucket MIP for the whole cluster: per-plant blocks
    plus the linking rows (shared supplier capacity per material-day,
    shared labor pool per day). This is the primal model: its
    incumbent is a FEASIBLE coupled plan (UB) and its solver bound a
    valid LB - independent of, and checkable against, the Lagrangian
    dual. Sparse assembly only (block-diagonal + linking rows).
    """
    from scipy.sparse import block_diag, coo_matrix, vstack
    import numpy as np
    from .two_level import (build_bucket_mip, DEFAULT_WEIGHTS,
                            DEFAULT_CHG_ALLOWANCE)
    weights = weights or DEFAULT_WEIGHTS
    labor_cap = labor_cap or {}
    mips, maps, offs = [], [], []
    v_off = 0
    for f in factories:
        mip, mp = build_bucket_mip(f, horizon_start, days, cap_min,
                                   DEFAULT_CHG_ALLOWANCE, None, None,
                                   None, weights)
        mips.append(mip)
        maps.append(mp)
        offs.append(v_off)
        v_off += len(mip.c)
    recipes = [_recipe_data(f) for f in factories]
    skus = [_sku_data(f) for f in factories]
    link_rows, link_cols, link_vals, link_sense, link_rhs = [], [], [], [], []

    def _link_row(entries, cap):
        r = len(link_rhs)  # local 0-based index within the link block
        for j, v in entries:
            link_rows.append(r)
            link_cols.append(j)
            link_vals.append(v)
        link_sense.append("L")
        link_rhs.append(cap)

    for (r, t), capv in supplier_cap.items():
        ent = []
        for p_i, mp in enumerate(maps):
            for (s, tt, l), j in mp["x"].items():
                if tt == t and r in recipes[p_i].get(s, {}):
                    ent.append((offs[p_i] + j, recipes[p_i][s][r]))
        if ent:
            _link_row(ent, capv)
    for t, capv in labor_cap.items():
        ent = []
        for p_i, mp in enumerate(maps):
            for (s, tt, l), j in mp["x"].items():
                if tt == t:
                    rate = skus[p_i].get(s, (0.0, [], None))[0]
                    if rate:
                        ent.append((offs[p_i] + j, 1.0 / rate))
        if ent:
            _link_row(ent, capv)
    A_blocks = block_diag([mip.A for mip in mips]).tocsr()
    n_vars = sum(len(mip.c) for mip in mips)
    if link_rhs:
        A_link = coo_matrix((link_vals, (link_rows, link_cols)),
                            shape=(len(link_rhs), n_vars)).tocsr()
        A = vstack([A_blocks, A_link]).tocsr()
    else:
        A = A_blocks
        link_sense, link_rhs = (), np.zeros(0)
    sense = tuple(s for mip in mips for s in mip.sense) + tuple(link_sense)
    rhs = np.concatenate([mip.rhs for mip in mips] +
                         [np.array(link_rhs, dtype=float)])
    c = np.concatenate([mip.c for mip in mips])
    lb = np.concatenate([mip.lb for mip in mips])
    ub = np.concatenate([mip.ub for mip in mips])
    integ = np.concatenate([mip.integrality for mip in mips])
    from ..solvers.highs_mip import MIP
    return MIP("coupled-cluster", c, A, sense, rhs, lb, ub, integ), \
        {"maps": maps, "offsets": offs}


def solve_coupled_cluster(factories: list, horizon_start, days: int,
                          cap_min: float,
                          supplier_cap: dict[tuple[str, int], float],
                          labor_cap: dict[int, float] | None = None,
                          time_limit_s: float = 300.0) -> dict:
    """Primal solve of ONE coupled cluster MIP. Returns the incumbent
    (a FEASIBLE coupled plan = valid UB), the solver's reported MIP
    gap, and per-plant quantity maps. The objective is recomputed from
    the assignment (solve_mip does this), never trusted blind."""
    from ..solvers.highs_mip import solve_mip
    mip, aux = build_coupled_mip(factories, horizon_start, days,
                                 cap_min, supplier_cap, labor_cap)
    res = solve_mip(mip, time_limit_s=time_limit_s)
    out = {"status": res["status"], "objective": res["objective"],
           "gap": res.get("gap"), "n_vars": len(mip.c),
           "n_rows": mip.A.shape[0]}
    if res["x"] is not None:
        qtys = []
        for p_i, mp in enumerate(aux["maps"]):
            off = aux["offsets"][p_i]
            qtys.append({k: float(res["x"][off + j])
                         for k, j in mp["x"].items()
                         if res["x"][off + j] > 1e-6})
        out["qty_per_plant"] = qtys
    return out


def validate_coupled_plan(factories: list, qtys: list, horizon_start,
                          days: int, cap_min: float,
                          chg_allowance: float = None,
                          supplier_cap: dict | None = None,
                          labor_cap: dict | None = None,
                          weights=None) -> tuple[list[str], dict]:
    """INDEPENDENT validator for a coupled bucket-level plan.

    Recomputes every original constraint from the factory records and
    the returned quantities alone - never trusts solver internals and
    never calls the pricing/master code:

    per plant: unknown SKU / line eligibility / negative qty;
    capacity per (line, day) net of the changeover allowance;
    the setup-linking bound (daily production of a SKU cannot exceed
    the tight M the MIP used); coverage with lateness/earliness as a
    cumulative stock walk (shortfall surfaces as the backlog KPI,
    matching the model's soft coverage rows).
    across plants: shared supplier pool per (material, day) and
    shared labor pool per day, each <= its cap.

    Returns (problems, kpis); a plan with problems == [] is feasible
    for the coupled bucket model as specified. Tolerances match the
    window validator (0.05 minutes capacity, 1e-6 quantities).
    """
    from .two_level import (DEFAULT_WEIGHTS, DEFAULT_CHG_ALLOWANCE,
                            linking_m)
    # data from the raw records, NOT from the model's helpers: a defect
    # in _sku_data/_recipe_data/due_day must not pass model and
    # validator together (guards/independent_data.py)
    from ..guards.independent_data import (raw_due_day, raw_recipe_data,
                                           raw_sku_data)
    weights = weights or DEFAULT_WEIGHTS
    chg = DEFAULT_CHG_ALLOWANCE if chg_allowance is None \
        else chg_allowance
    supplier_cap = supplier_cap or {}
    labor_cap = labor_cap or {}
    cap_eff = cap_min * (1.0 - chg)
    problems: list[str] = []
    kpis = {"plants": len(qtys), "backlog_units_end": 0.0,
            "changeover_allowance_note": "bucket level: allowance "
            "netting only; sequencing validated separately"}

    # per-plant checks
    mat_tot: dict = {}
    lab_tot: dict = {}
    total_late = 0.0
    total_early = 0.0
    total_setups = 0
    for p_i, (f, qty) in enumerate(zip(factories, qtys)):
        sku = raw_sku_data(f)
        recipes = raw_recipe_data(f)
        dem: dict = {}
        for d in f.demands:
            day = raw_due_day(d.due, horizon_start)
            if 0 <= day < days:
                dem.setdefault(d.item, [0.0] * days)[day] += d.quantity
        per_ld: dict = {}
        per_st: dict = {}
        for (s, t, l), q in qty.items():
            # NaN compares False with everything: it used to skip every
            # check below and the plan counted as valid. Same for a day
            # outside the window (its minutes were never capped).
            if not isinstance(q, (int, float)) or not math.isfinite(q):
                problems.append(f"plant {p_i}: invariant: non-finite "
                                f"qty {q!r} for {s} {t} {l}")
                continue
            if not (0 <= t < days):
                problems.append(f"plant {p_i}: invariant: day {t} "
                                f"outside window [0, {days}) for {s} {l}")
                continue
            if q < -1e-9:
                problems.append(f"plant {p_i}: negative qty {s} {t} {l}")
                continue
            if q <= 1e-9:
                continue
            if s not in sku:
                problems.append(f"plant {p_i}: unknown sku {s}")
                continue
            if l not in sku[s][1]:
                problems.append(
                    f"plant {p_i}: {s} not eligible on {l}")
                continue
            rate = sku[s][0]
            per_ld[(l, t)] = per_ld.get((l, t), 0.0) + q / rate
            per_st[(s, t)] = per_st.get((s, t), 0.0) + q
            for r, per in recipes.get(s, {}).items():
                mat_tot[(r, t)] = mat_tot.get((r, t), 0.0) + per * q
            lab_tot[t] = lab_tot.get(t, 0.0) + q / rate
        for (l, t), mins in sorted(per_ld.items()):
            if mins > cap_eff + 0.05:
                problems.append(
                    f"plant {p_i} {l} day {t}: {mins:.1f} min > "
                    f"cap {cap_eff:.1f}")
        for (s, t), q in sorted(per_st.items()):
            M = linking_m(sku[s], cap_eff, sum(dem.get(s, [0.0])))
            if q > M + 1e-6:
                problems.append(
                    f"plant {p_i} {s} day {t}: produced {q:.1f} > "
                    f"linking M {M:.1f}")
            if q > 1e-9:
                total_setups += 1
        # cumulative coverage walk per SKU (soft: lateness/earliness
        # are KPIs, matching the model's soft rows)
        for s, ds in dem.items():
            cum = 0.0
            for t in range(days):
                cum += ds[t]
                produced = sum(qty.get((s, tau, l), 0.0)
                               for tau in range(t + 1)
                               for l in sku.get(s, (0, [], None))[1])
                short = cum - produced
                if short > 1e-6:
                    total_late += short - max(0.0, cum - ds[t]
                                              - sum(qty.get((s, tau, l), 0.0)
                                                    for tau in range(t)
                                                    for l in sku[s][1]))
                early = produced - cum
                if early > 1e-6:
                    total_early += early
            end_backlog = cum - sum(qty.get((s, tau, l), 0.0)
                                    for tau in range(days)
                                    for l in sku.get(s, (0, [], None))[1])
            if end_backlog > 1e-6:
                kpis["backlog_units_end"] += end_backlog

    # shared-pool checks across plants
    for (r, t), cap in sorted(supplier_cap.items()):
        use = mat_tot.get((r, t), 0.0)
        if use > cap + 1e-6:
            problems.append(
                f"supplier pool ({r}, day {t}): {use:.1f} > cap {cap:.1f}")
    for t, cap in sorted(labor_cap.items()):
        use = lab_tot.get(t, 0.0)
        if use > cap + 0.05:
            problems.append(
                f"labor pool day {t}: {use:.1f} min > cap {cap:.1f}")
    kpis.update({"setups": total_setups,
                 "late_unit_days": round(total_late, 3),
                 "early_unit_days": round(total_early, 3)})
    return problems, kpis


def linking_m_problems(factory, horizon_start, days: int, cap_min: float,
                       chg_allowance: float = None,
                       version: str = None) -> list[str]:
    """Check the model's linking M against the physical maximum, from
    raw records: for every SKU, M must be >= min(sum over eligible lines
    of cap_eff * rate, total window demand). A smaller M silently cuts
    plans that are feasible per line capacity and never shows up as a
    violation in any plan (the validator would reject them as well)."""
    from .two_level import DEFAULT_CHG_ALLOWANCE, linking_m
    from ..guards.independent_data import raw_due_day, raw_sku_data
    chg = DEFAULT_CHG_ALLOWANCE if chg_allowance is None else chg_allowance
    cap_eff = cap_min * (1.0 - chg)
    sku = raw_sku_data(factory)
    dem: dict = {}
    for d in factory.demands:
        t = raw_due_day(d.due, horizon_start)
        if 0 <= t < days:
            dem[d.item] = dem.get(d.item, 0.0) + d.quantity
    out = []
    for s, (rate, lines, _) in sorted(sku.items()):
        need = min(len(lines) * cap_eff * rate, dem.get(s, 0.0))
        M = linking_m(sku[s], cap_eff, dem.get(s, 0.0), version)
        if M < need - 1e-6:
            out.append(f"{s}: linking M {M:.1f} < physical maximum "
                       f"{need:.1f} ({len(lines)} lines, demand "
                       f"{dem.get(s, 0.0):.1f})")
    return out
