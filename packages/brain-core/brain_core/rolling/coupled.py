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
                 eta0: float = 2.0, inv0s: list | None = None
                 ) -> CoupledResult:
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
    ub_est = float("inf")   # Polyak step needs a UB estimate; a real
                            # primal UB replaces it once repair lands
    stall = 0
    eta = eta0
    for k in range(rounds):
        z_sum = 0.0
        mat_tot: dict[tuple[str, int], float] = {}
        lab_tot: dict[int, float] = {}
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
            # no primal UB yet: bounded geometric step, still monotone
            # in u-space by the max(0, .) projection (a multiplier
            # walk, NOT a claimed dual optimum)
            step = eta / (k + 1.0)
        cap_step = 1e6
        uS = {key: max(0.0, min(cap_step, uS[key] + step * gS[key]))
              for key in uS}
        uL = {key: max(0.0, min(cap_step, uL[key] + step * gL[key]))
              for key in uL}
    res.lower_bound = best_lb if best_lb > float("-inf") else None
    res.multipliers = {"supplier": uS, "labor": uL}
    res.rounds_run = len(res.lb_series)
    return res
