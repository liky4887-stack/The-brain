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
    iter_times: list[float] = field(default_factory=list)
    ub_series: list[float] = field(default_factory=list)
    first_ub_s: float | None = None   # wall time of first valid plan
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
    first_msg = None
    res = None
    # default HiGHS first; a numerical failure (observed: status 4
    # "model_status Unknown" late in CG with BIGM 1e12 next to costs
    # near 1e8) is retried with the other HiGHS algorithms and the
    # retry is RECORDED in the returned status, never silent
    for method in ("highs", "highs-ipm", "highs-ds"):
        res = linprog(c, A_ub=A_ub.tocsr(),
                      b_ub=np.array(caps, dtype=float),
                      A_eq=A_eq.tocsr(), b_eq=np.ones(n_plants),
                      bounds=(0.0, None), method=method)
        if res.status == 0:
            break
        if first_msg is None:
            first_msg = (f"master LP {method} status {res.status}: "
                         f"{res.message}")
    if res.status != 0:
        return (None, None, None, None,
                f"{first_msg}; retries highs-ipm/highs-ds also failed "
                f"(last status {res.status}: {res.message})",
                None)
    u = np.asarray(res.ineqlin.marginals)      # <= 0 for min / <= rows
    sigma = np.asarray(res.eqlin.marginals)    # free
    art = float(res.x[art0:].sum())
    lam = np.asarray(res.x[:art0])             # column weights
    status = "optimal" if first_msg is None else \
        f"optimal after retry ({first_msg}; solved with {method})"
    return float(res.fun), u, sigma, art, status, lam


def column_generation(factories: list, horizon_start, days: int,
                      cap_min: float,
                      supplier_cap: dict[tuple[str, int], float],
                      labor_cap: dict[int, float] | None = None,
                      max_iter: int = 60, time_limit_s: float = 30.0,
                      inv0s: list | None = None, weights=None,
                      tol: float = TOL,
                      seed_qtys: list | None = None,
                      stab_alpha: float = 0.0,
                      exact_every: int = 5,
                      wall_s: float | None = None,
                      im_every: int = 0,
                      alloc_every: int = 0,
                      dive: bool = True,
                      progress_window: int | None = None,
                      progress_rel_tol: float = 1e-9) -> DWResult:
    """Full CG loop: seed columns = uncoupled optima (or seed_qtys -
    e.g. a heuristic or monolithic coupled plan, one qty map per
    plant: warm start with an already-feasible coupled solution);
    each iteration solves the restricted master LP, prices every
    plant (the parallel worker step; sequential HERE, so wall = sum
    of plant solves per round - see docs/COUPLED-DESIGN.md), adds
    every negative reduced-cost column, stops when none price below
    -tol.

    Dual stabilization (Wentges smoothing): with stab_alpha in (0,1),
    pricing uses u_price = alpha*u_master + (1-alpha)*u_center; the
    center moves to u_master whenever the master objective improves.
    Columns from smoothed rounds are valid columns, but convergence
    and bounds are judged ONLY on exact rounds (priced at u_master):
    every exact_every-th round and the candidate-final round are
    priced exactly. The certificate rule is unchanged: an exact
    round certifies only if every subproblem is proven optimal."""
    from .two_level import DEFAULT_WEIGHTS
    weights = weights or DEFAULT_WEIGHTS
    labor_cap = labor_cap or {}
    inv0s = inv0s or [None] * len(factories)
    recipes = [_recipe_data(f) for f in factories]
    skus = [_sku_data(f) for f in factories]
    # mixed key types: (material, day) tuples and labor day
    # ints - order only needs determinism, not comparability
    pools = sorted(set(supplier_cap) | set(labor_cap), key=repr)
    caps = [supplier_cap.get(k, labor_cap.get(k)) for k in pools]
    res = DWResult(lower_bound=None)
    # seed: warm-start columns if given (one feasible coupled plan),
    # else uncoupled optima (u = 0)
    colsets: list[list[dict]] = []
    for p_i, f in enumerate(factories):
        if seed_qtys is not None and seed_qtys[p_i]:
            colsets.append([_column(f, horizon_start, days,
                                    seed_qtys[p_i], inv0s[p_i],
                                    weights)])
            continue
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
    import time as _time
    t_start = _time.monotonic()
    u_center = None
    best_master = None
    force_exact_next = False
    next_alloc_it = 0
    _flat = None
    if progress_window:
        from ..guards.progress import FlatProgress
        _flat = FlatProgress(progress_window, progress_rel_tol,
                             False, "CG restricted-master objective")
    for it in range(max_iter):
        _it_t0 = _time.monotonic()
        obj, u, sigma, art, st, lam = _solve_master(colsets,
                                                      pools,
                                                      caps)
        if obj is None:
            res.problems.append(f"iter {it}: {st}")
            res.status = "master failed"
            break
        if st != "optimal":
            res.problems.append(f"iter {it}: {st}")
        if art > 1e-6:
            res.problems.append(f"iter {it}: master used artificial "
                                f"columns ({art:.3g}); column pool "
                                "does not yet span a feasible plan")
        res.master_series.append(obj)
        if _flat is not None and _flat.update(obj):
            res.problems.append(f"iter {it}: {_flat.reason()}")
            res.status = "stalled: bound flat (progress guard)"
            break
        # Wentges stabilization: price at smoothed duals except on
        # exact rounds; move the center when the master improves.
        if u_center is None:
            u_center = u.copy()
        if best_master is None or obj < best_master - 1e-9:
            # minimization: the center moves when the master IMPROVES
            best_master = obj
            u_center = u.copy()
        at_master = (stab_alpha <= 0.0 or force_exact_next
                     or it % exact_every == 0)
        force_exact_next = False
        u_price = u if at_master else stab_alpha * u + \
            (1.0 - stab_alpha) * u_center
        if (alloc_every and at_master and art <= 1e-6
                and it >= next_alloc_it):
            # allocate-then-solve on the CURRENT master (colsets and
            # lam aligned - pricing below has not appended yet)
            at_cost, at_qtys, at_probs = allocate_solve(
                colsets, lam, factories, horizon_start, days,
                cap_min, inv0s=inv0s, weights=weights,
                time_limit_s=time_limit_s, pools=pools)
            res.problems.extend(at_probs)
            if at_cost is not None and not _ub_plan_valid(
                    res, at_qtys, factories, horizon_start, days,
                    cap_min, pools, caps, "allocate_solve"):
                at_cost = None
            if at_cost is not None and (
                    res.upper_bound is None
                    or at_cost < res.upper_bound - 1e-9):
                res.upper_bound = at_cost
                res.selected_qtys = at_qtys
                res.ub_series.append(at_cost)
                if res.first_ub_s is None:
                    res.first_ub_s = round(
                        _time.monotonic() - t_start, 2)
            next_alloc_it = it + alloc_every
            if dive:
                dv_cost, dv_qtys = diving_select(colsets, pools, caps)
                if dv_cost is not None and not _ub_plan_valid(
                        res, dv_qtys, factories, horizon_start, days,
                        cap_min, pools, caps, "diving"):
                    dv_cost = None
                if dv_cost is not None and (
                        res.upper_bound is None
                        or dv_cost < res.upper_bound - 1e-9):
                    res.upper_bound = dv_cost
                    res.selected_qtys = dv_qtys
                    res.ub_series.append(dv_cost)
                    if res.first_ub_s is None:
                        res.first_ub_s = round(
                            _time.monotonic() - t_start, 2)
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
                                (s, -u_price[r_i] * per))
                else:
                    for s in skus[p_i]:
                        rate = skus[p_i][s][0]
                        if rate:
                            per_day.setdefault(k, []).append(
                                (s, -u_price[r_i] / rate))
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
            try:
                b = solve_buckets(f, horizon_start, days, cap_min,
                                  time_limit_s=time_limit_s,
                                  inv0=inv0s[p_i],
                                  unit_cost_extra=extra)
            except Exception as exc:
                # worker crash: recorded, round inexact, plant repriced
                # next round - recovery without duplicate columns
                res.problems.append(
                    f"iter {it} plant {p_i}: pricing worker CRASHED "
                    f"({type(exc).__name__}: {exc}); round inexact, "
                    "plant repriced next round")
                round_exact = False
                continue
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
        # Farley bound is valid ONLY under exact pricing at the TRUE
        # master duals: rc from an incumbent upper-estimates the true
        # min reduced cost, which would overstate the bound; a
        # smoothed round's rc is not at u_master at all.
        res.lb_series.append(
            farley if (round_exact and at_master) else None)
        res.iter_times.append(round(_time.monotonic() - _it_t0, 3))
        res.iterations = it + 1
        if im_every and (it + 1) % im_every == 0:
            # periodic restricted integer master (primal side): the
            # pool refs live on res for the integer master to read
            res._colsets = colsets
            res._pools, res._caps = pools, caps
            res._cap_min = cap_min
            prev_ub = res.upper_bound
            integer_master(res, factories, horizon_start, days,
                           time_limit_s=time_limit_s)
            if (res.upper_bound is not None
                    and res.upper_bound != prev_ub):
                res.ub_series.append(res.upper_bound)
                if res.first_ub_s is None:
                    res.first_ub_s = round(
                        _time.monotonic() - t_start, 2)
        if (wall_s is not None
                and _time.monotonic() - t_start > wall_s):
            res.problems.append(f"iter {it}: wall budget "
                                f"{wall_s:.0f}s reached")
            break
        if new_cols == 0 and not at_master:
            # candidate convergence under smoothed pricing: re-price
            # at the true master duals before deciding
            force_exact_next = True
            continue
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
    res._cap_min = cap_min
    from ..guards.invariants import dw_bound_findings, enforce
    res.problems.extend(x for x in enforce(dw_bound_findings(res),
                                           "column_generation")
                        if x not in res.problems)
    return res


def diving_select(colsets, pools, caps, max_rounds: int = 200):
    """Diving: restricted master LP; fix the plant column whose LP
    weight is closest to 1; re-solve; repeat until every plant is
    fixed to one column. A fixed plant is represented by a singleton
    colset (convexity forces lambda=1). Returns (total_cost,
    selected_per_plant) when the final master needs NO artificial
    columns (a feasible coupled plan => valid UB), else (None, None).
    LP solves only - no per-plant MIP re-solves."""
    cur = [list(cs) for cs in colsets]
    for _ in range(min(max_rounds, len(cur))):
        obj, u, sigma, art, st, lam = _solve_master(cur, pools, caps)
        if obj is None:
            return None, None
        # all plants already fixed?
        if all(len(cs) == 1 for cs in cur):
            if art <= 1e-6:
                total = sum(cs[0]["cost"] for cs in cur)
                return total, [cs[0]["qty"] for cs in cur]
            return None, None
        # dive on the non-fixed plant column with lambda closest to 1
        best = None   # (1 - lam, plant, column_index)
        idx = 0
        for p_i, cs in enumerate(cur):
            for j, c in enumerate(cs):
                w = float(lam[idx])
                idx += 1
                if len(cs) <= 1:
                    continue
                score = abs(1.0 - w)
                if best is None or score < best[0]:
                    best = (score, p_i, j)
        if best is None:
            return None, None
        _sc, p_i, j = best
        cur[p_i] = [cur[p_i][j]]
    return None, None


def _ub_plan_valid(res, qtys, factories, horizon_start, days, cap_min,
                   pools, caps, source) -> bool:
    """Gate EVERY upper-bound write: the plan must pass the independent
    coupled validator (shared pools included). Failures are loud: a
    problem line is recorded and the plan is NOT used as a UB."""
    from .coupled import validate_coupled_plan
    if cap_min is None:
        cap_min = getattr(res, "_cap_min", None)
    sup = {k: c for k, c in zip(pools, caps) if isinstance(k, tuple)}
    lab = {k: c for k, c in zip(pools, caps) if not isinstance(k, tuple)}
    probs, _k = validate_coupled_plan(factories, qtys, horizon_start,
                                      days, cap_min, supplier_cap=sup,
                                      labor_cap=lab)
    if probs:
        res.problems.append(
            f"{source}: candidate UB plan REJECTED by the independent "
            f"validator ({len(probs)} problems, first: {probs[0]}); "
            "UB not updated")
        return False
    return True


def allocate_solve(colsets, lam, factories, horizon_start, days,
                   cap_min, inv0s=None, weights=None,
                   time_limit_s=30.0, pools=None):
    """Allocate-then-solve-exactly (primal heuristic): take each
    plant's share of every shared pool from the master LP convex
    combination (share_p[r] = sum_c lam_c * usage_c[r]), then solve
    each plant ALONE with its shares as hard limits. The union is a
    feasible coupled plan because sum_p share_p[r] <= cap[r] in the
    master; each per-plant solve re-optimizes within its allowance,
    so the total is a valid UB no worse than the master combination.
    Returns (total_cost, qtys, problems)."""
    from .two_level import solve_buckets
    inv0s = inv0s or [None] * len(factories)
    shares = [dict() for _ in factories]
    idx = 0
    for p_i, cs in enumerate(colsets):
        for c in cs:
            w = float(lam[idx])
            idx += 1
            if w <= 1e-9:
                continue
            for k, v in c["mat"].items():
                shares[p_i][k] = shares[p_i].get(k, 0.0) + w * v
            for k, v in c["lab"].items():
                shares[p_i][k] = shares[p_i].get(k, 0.0) + w * v
    # A pool a plant's columns never touch has share 0, NOT "no limit":
    # omitting the key left that plant unconstrained and the union
    # exceeded the shared cap (known failure f7ca2901b4bd)
    for k in (pools or ()):
        for sh in shares:
            sh.setdefault(k, 0.0)
    total = 0.0
    qtys = []
    problems = []
    for p_i, f in enumerate(factories):
        mat_cap = {k: v for k, v in shares[p_i].items()
                   if isinstance(k, tuple)}
        lab_cap = {k: v for k, v in shares[p_i].items()
                   if not isinstance(k, tuple)}
        b = solve_buckets(f, horizon_start, days, cap_min,
                          time_limit_s=time_limit_s,
                          inv0=inv0s[p_i], mat_cap=mat_cap,
                          lab_cap=lab_cap)
        if b.objective is None:
            problems.append(f"allocate_solve plant {p_i}: bucket "
                            f"status {b.status!r}")
            return None, None, problems
        total += b.objective
        qtys.append(b.qty)
    return total, qtys, problems


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
    if not _ub_plan_valid(dw, selected, factories, horizon_start, days,
                          None, pools, caps, "integer_master"):
        return dw
    if dw.upper_bound is None or total < dw.upper_bound - 1e-9:
        dw.upper_bound = total
        dw.selected_qtys = selected
    # a worse integer-master incumbent never displaces a better UB
    # found by another primal path (e.g. allocate_solve)
    from ..guards.invariants import dw_bound_findings, enforce
    dw.problems.extend(x for x in enforce(dw_bound_findings(dw),
                                          "integer_master")
                       if x not in dw.problems)
    return dw
