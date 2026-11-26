"""Phase D: Dantzig-Wolfe column generation for the coupled cluster.

The user's architecture, exactly: parallel per-plant PRICING workers
(each solves its own bucket MIP with link prices) feed ONE master
problem. Two master forms, both linear:

  1. Restricted master LP (convexification form): one convexity row
     per plant + the shared-pool linking rows; columns = whole plant
     plans. Solved to convergence it attains the convexification
     bound, which EQUALS the Lagrangian dual bound (LP duality; the
     standard DW/LR equivalence, cf. docs/COUPLED-DESIGN.md). Unlike
     subgradient ascent it attains that bound exactly and certifies
     it (all reduced costs >= -tol). It is NOT a stronger bound than
     LR in theory; it is the same bound, reached exactly.
  2. Integer restricted master (one MIP, binary column selection):
     any incumbent is a FEASIBLE coupled plan = valid UB.

Honesty: per-iteration master values are NOT valid bounds until
convergence; the valid per-iteration lower bound recorded is the
Farley bound z_RMP + sum_p min(0, rc_p). If pricing hits the
iteration cap before convergence, lower_bound falls back to the last
Farley bound and status says NOT CONVERGED. Artificial columns keep
the restricted master feasible while the column pool is thin; a
master or integer master still using them is reported, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .coupled import _base_objective, _plant_usage
from .two_level import solve_buckets, _recipe_data, _sku_data

BIGM = 1e12          # artificial-column cost (real objectives ~1e8)
TOL = 1e-6


@dataclass
class DWResult:
    lower_bound: float | None          # converged LP bound, or last
                                       # Farley bound when capped
    upper_bound: float | None = None   # integer restricted master
    lb_series: list[float] = field(default_factory=list)   # Farley
    master_series: list[float] = field(default_factory=list)
    iterations: int = 0
    columns_per_plant: list[int] = field(default_factory=list)
    converged: bool = False
    bound_certified: bool = False   # True only when the final pricing
                                    # round solved EVERY subproblem to
                                    # proven optimality: the converged
                                    # master value is then a certified
                                    # convexification bound. A
                                    # time-limited incumbent can fake
                                    # "no negative reduced cost", so
                                    # without this flag the value is a
                                    # measured number, not a bound.
    status: str = ""
    selected_qtys: list | None = None  # per-plant qty maps of the UB
    problems: list[str] = field(default_factory=list)

    @property
    def proven_gap(self) -> float | None:
        if self.lower_bound is None or self.upper_bound is None:
            return None
        return (self.upper_bound - self.lower_bound) / \
            max(abs(self.upper_bound), 1e-9)


def _column(factory, hs, days, qty, inv0, weights):
    """(cost, usage_per_pool, qty) of one plant plan, all recomputed
    from the records."""
    from .coupled import _base_objective as base
    cost = base(factory, hs, days, qty, inv0, weights)
    mat, lab = _plant_usage(factory, qty)
    return {"cost": cost, "mat": mat, "lab": lab, "qty": qty}


def _proven_optimal(b) -> bool:
    """A bucket solve certifies pricing only when proven optimal (or
    trivially empty). A time-limit incumbent is a VALID COLUMN but
    proves nothing about the minimum reduced cost."""
    return b.objective is not None and \
        ("Optimal" in b.status or b.status == "no-demand")


def _solve_master(colsets, pools, caps):
    """Restricted master LP. pools: ordered pool keys; caps: aligned.
    Returns (objective, link_duals (u_r <= 0), conv_duals (sigma_p),
    artificial_usage, status). scipy/HiGHS LP, sparse."""
    import numpy as np
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix
    n_pools = len(pools)
    n_plants = len(colsets)
    cols = []          # (plant or None, cost, usage vector)
    for p_i, cs in enumerate(colsets):
        for c in cs:
            cols.append((p_i, c["cost"],
                         np.array([c["mat"].get(k, 0.0) +
                                   c["lab"].get(k, 0.0)
                                   for k in pools])))
    art0 = len(cols)
    for r in range(n_pools):
        e = np.zeros(n_pools)
        e[r] = -1.0     # artificial = cap borrowing: usage - art <= cap
        cols.append((None, BIGM, e))
    n = len(cols)
    c = np.array([cc for _p, cc, _u in cols])
    A_ub = lil_matrix((n_pools, n))
    for j, (_p, _cc, u) in enumerate(cols):
        for r in range(n_pools):
            if u[r]:
                A_ub[r, j] = u[r]
    A_eq = lil_matrix((n_plants, n))
    for j, (p_i, _cc, _u) in enumerate(cols):
        if p_i is not None:
            A_eq[p_i, j] = 1.0
    res = linprog(c, A_ub=A_ub.tocsr(),
                  b_ub=np.array(caps, dtype=float),
                  A_eq=A_eq.tocsr(), b_eq=np.ones(n_plants),
                  bounds=(0.0, None), method="highs")
    if res.status != 0:
        return None, None, None, None, f"master LP status " \
            f"{res.status}: {res.message}"
    u = np.asarray(res.ineqlin.marginals)      # <= 0 for min / <= rows
    sigma = np.asarray(res.eqlin.marginals)    # free
    art = float(res.x[art0:].sum())
    return float(res.fun), u, sigma, art, "optimal"


def column_generation(factories: list, horizon_start, days: int,
                      cap_min: float,
                      supplier_cap: dict[tuple[str, int], float],
                      labor_cap: dict[int, float] | None = None,
                      max_iter: int = 60, time_limit_s: float = 30.0,
                      inv0s: list | None = None, weights=None,
                      tol: float = TOL) -> DWResult:
    """Full CG loop: seed columns = uncoupled optima; each iteration
    solves the restricted master LP, prices every plant (the parallel
    worker step; sequential HERE, so wall = sum of plant solves per
    round - see docs/COUPLED-DESIGN.md), adds every negative
    reduced-cost column, stops when none price below -tol."""
    from .two_level import DEFAULT_WEIGHTS
    weights = weights or DEFAULT_WEIGHTS
    labor_cap = labor_cap or {}
    inv0s = inv0s or [None] * len(factories)
    recipes = [_recipe_data(f) for f in factories]
    skus = [_sku_data(f) for f in factories]
    pools = sorted(set(supplier_cap) | set(labor_cap))
    caps = [supplier_cap.get(k, labor_cap.get(k)) for k in pools]
    res = DWResult(lower_bound=None)
    # seed: uncoupled optima (u = 0)
    colsets: list[list[dict]] = []
    for p_i, f in enumerate(factories):
        b = solve_buckets(f, horizon_start, days, cap_min,
                          time_limit_s=time_limit_s,
                          inv0=inv0s[p_i])
        if b.objective is None:
            res.problems.append(f"seed plant {p_i}: bucket status "
                                f"{b.status!r}; plant skipped")
            colsets.append([])
            continue
        colsets.append([_column(f, horizon_start, days, b.qty,
                                inv0s[p_i], weights)])
    for it in range(max_iter):
        obj, u, sigma, art, st = _solve_master(colsets, pools, caps)
        if obj is None:
            res.problems.append(f"iter {it}: {st}")
            res.status = "master failed"
            break
        if art > 1e-6:
            res.problems.append(f"iter {it}: master used artificial "
                                f"columns ({art:.3g}); column pool "
                                "does not yet span a feasible plan")
        res.master_series.append(obj)
        # price every plant (the worker step)
        new_cols = 0
        farley = obj
        round_exact = True
        for p_i, f in enumerate(factories):
            # price only pools whose DAY matches t: a supplier pool
            # (material, day) or labor pool (day) binds production on
            # that day only
            per_day: dict[int, list[tuple[float, float]]] = {}
            for r_i, k in enumerate(pools):
                if k in supplier_cap:
                    mat, d0 = k
                    for s in skus[p_i]:
                        per = recipes[p_i].get(s, {}).get(mat, 0.0)
                        if per:
                            per_day.setdefault(d0, []).append(
                                (s, -u[r_i] * per))
                else:
                    for s in skus[p_i]:
                        rate = skus[p_i][s][0]
                        if rate:
                            per_day.setdefault(k, []).append(
                                (s, -u[r_i] / rate))
            extra: dict[tuple[str, int], float] = {}
            for t, entries in per_day.items():
                if not (0 <= t < days):
                    continue
                acc: dict[str, float] = {}
                for s, v in entries:
                    acc[s] = acc.get(s, 0.0) + v
                for s, v in acc.items():
                    if v:
                        extra[(s, t)] = v
            b = solve_buckets(f, horizon_start, days, cap_min,
                              time_limit_s=time_limit_s,
                              inv0=inv0s[p_i], unit_cost_extra=extra)
            if b.objective is None:
                res.problems.append(f"iter {it} plant {p_i}: bucket "
                                    f"status {b.status!r}; priced "
                                    "column skipped")
                round_exact = False    # rc unknown for this plant
                continue
            if not _proven_optimal(b):
                res.problems.append(
                    f"iter {it} plant {p_i}: pricing NOT proven "
                    f"optimal ({b.status!r}); incumbent kept as a "
                    "valid column but this round certifies nothing")
                round_exact = False
            rc = b.objective - sigma[p_i]
            farley += min(0.0, rc)
            if rc < -tol:
                colsets[p_i].append(_column(f, horizon_start, days,
                                            b.qty, inv0s[p_i],
                                            weights))
                new_cols += 1
        # Farley bound is valid ONLY under exact pricing: rc from an
        # incumbent upper-estimates the true min reduced cost, which
        # would overstate the bound.
        res.lb_series.append(farley if round_exact else None)
        res.iterations = it + 1
        if new_cols == 0:
            if round_exact:
                res.converged = True
                res.bound_certified = True
                res.lower_bound = obj   # certified convexification bd
                res.status = "converged (certified: exact pricing)"
            else:
                # no new columns but the no-column proof is not exact:
                # honest stop, NOT a certified convergence
                res.status = ("stalled: no new columns but final "
                              "pricing not proven exact - bound NOT "
                              "certified")
            break
    else:
        pass
    if not res.converged:
        certified = [v for v in res.lb_series if v is not None]
        if certified:
            res.lower_bound = max(certified)
            res.status = res.status or (
                f"NOT CONVERGED after {res.iterations} iterations; "
                "reporting best CERTIFIED Farley bound")
        elif res.lb_series:
            res.lower_bound = None
            res.status = res.status or (
                f"NOT CONVERGED after {res.iterations} iterations and "
                "no pricing round was exact - NO valid lower bound")
    res.columns_per_plant = [len(cs) for cs in colsets]
    res._colsets = colsets          # internal: for the integer master
    res._pools, res._caps = pools, caps
    return res


def integer_master(dw: DWResult, factories: list, horizon_start,
                   days: int, weights=None,
                   time_limit_s: float = 120.0) -> DWResult:
    """ONE integer restricted master over the generated columns:
    binary lambda, one column per plant. Any incumbent whose
    artificial usage is zero is a FEASIBLE coupled plan: its cost is
    a valid UB, recomputed here from the records. Mutates and returns
    dw."""
    import numpy as np
    from scipy.sparse import lil_matrix
    from ..solvers.highs_mip import MIP, solve_mip
    colsets = dw._colsets
    pools, caps = dw._pools, dw._caps
    n_pools, n_plants = len(pools), len(colsets)
    cols = []
    for p_i, cs in enumerate(colsets):
        for c in cs:
            cols.append((p_i, c["cost"],
                         np.array([c["mat"].get(k, 0.0) +
                                   c["lab"].get(k, 0.0)
                                   for k in pools])))
    art0 = len(cols)
    for r in range(n_pools):
        e = np.zeros(n_pools)
        e[r] = -1.0     # artificial = cap borrowing: usage - art <= cap
        cols.append((None, BIGM, e))
    n = len(cols)
    A = lil_matrix((n_pools + n_plants, n))
    for j, (p_i, _cc, u) in enumerate(cols):
        for r in range(n_pools):
            if u[r]:
                A[r, j] = u[r]
        if p_i is not None:
            A[n_pools + p_i, j] = 1.0
    sense = tuple(["L"] * n_pools + ["E"] * n_plants)
    rhs = np.concatenate([np.array(caps, dtype=float),
                          np.ones(n_plants)])
    c = np.array([cc for _p, cc, _u in cols])
    mip = MIP("dw-integer-master", c, A.tocsr(), sense, rhs,
              np.zeros(n), np.ones(n), np.ones(n))
    sol = solve_mip(mip, time_limit_s=time_limit_s)
    if sol["x"] is None:
        dw.problems.append(f"integer master: status "
                           f"{sol['status']!r}; no incumbent, UB "
                           "stays UNKNOWN")
        return dw
    x = sol["x"]
    if x[art0:].sum() > 1e-6:
        dw.problems.append("integer master incumbent uses artificial "
                           "columns: not a feasible coupled plan, UB "
                           "stays UNKNOWN")
        return dw
    # recompute the UB from the selected columns, records-side
    total = 0.0
    selected = []
    for p_i, cs in enumerate(colsets):
        pick = next((j for j in range(len(cs))
                     if cols[sum(len(c) for c in colsets[:p_i]) + j][0]
                     == p_i and x[sum(len(c) for c in colsets[:p_i])
                                  + j] > 0.5), None)
        if pick is None:
            dw.problems.append(f"integer master: plant {p_i} has no "
                               "selected column; UB stays UNKNOWN")
            return dw
        total += cs[pick]["cost"]
        selected.append(cs[pick]["qty"])
    dw.upper_bound = total
    dw.selected_qtys = selected
    return dw
