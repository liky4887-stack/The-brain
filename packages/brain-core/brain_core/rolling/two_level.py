"""Two-level rolling-window solve: MILP buckets, then CP-SAT sequencing.

Level 1 (buckets, HiGHS via solvers/highs_mip.py): assigns production
quantities to (SKU, day, eligible line) over a window of days. One
setup binary per SKU-day, cumulative coverage constraints with explicit
lateness variables, earliness variables as holding cost (unit-days).
Capacity per line-day is reduced by a measured changeover allowance:
exact changeovers are sequence-dependent and only known after
sequencing, so the bucket level plans against an allowance and the
sequencing level checks the truth. An allowance miss is reported,
never hidden (honesty rules).

Level 2 (sequencing, CP-SAT): per line-day, the lots assigned by
level 1 are sequenced with the exact setup matrix via a circuit model
(minimize total changeover; hard capacity on production + changeover
minutes). Tens of lots per line-day: exact and fast.

Rolling driver: solve the window, freeze the first `freeze_days`,
net inventory/backorders per SKU, roll forward. The product's cadence
is a weekly plan (freeze_days=7); freeze_days=1 is a daily replan.

Bounds and honesty: the bucket MILP relaxes capacity (allowance) and
approximates changeovers by a setup count, so its objective is a lower
bound on the true sequenced proxy cost; the reported gap compares the
recomputed plan cost (same weights) against that bound and is labeled
as such. Solver statuses are never taken on faith: validate_window_plan
and validate_full_run recompute everything from the returned
assignments and the records alone.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from scipy.sparse import coo_matrix

from ..records.models import Factory
from ..solvers.highs_mip import MIP, solve_mip

SETUP_W = 50.0      # one SKU-day setup ~ a campaign break
LATE_W = 1000.0     # one unit late one day: avoid whenever possible
EARLY_W = 0.001     # one unit held one day: tie-breaks front-loading


@dataclass(frozen=True)
class ObjectiveWeights:
    """The objective sliders (Stage 3): what the planner cares about.

    setup: per SKU-day campaign-break cost (the changeovers slider).
    late: per unit-day lateness (the on-time slider).
    early: per unit-day earliness (inventory aversion).
    energy: per production-minute weight, scaled per line by
        (2 - efficiency) - a documented PROXY: the records carry
        line efficiency, not power draw, so "energy" here means
        "prefer the efficient lines".
    """
    setup: float = SETUP_W
    late: float = LATE_W
    early: float = EARLY_W
    energy: float = 0.0


DEFAULT_WEIGHTS = ObjectiveWeights()
DEFAULT_CHG_ALLOWANCE = 0.15  # share of line-day reserved for changeovers

MAX_DAY_REPAIRS = 4   # evictions per infeasible day before reporting
DENSE_DAY_CHUNKS = 110   # measured: UNKNOWNs at 121-124 chunks
# (fc9f56ec5ce7), none at <=110 in 249,179 assignments
DENSE_DAY_BUDGET_S = 300.0
DENSE_DAY_MAX_S = 600.0


def _min_incoming_changeover(factory: Factory) -> dict:
    """state -> smallest non-self changeover into it across all setup
    matrices (minutes). Allergen-class states surface as high values.
    """
    out: dict[str, float] = {}
    for mtx in factory.setup_matrices:
        for r in mtx.rules:
            minutes = r.duration.total_seconds() / 60.0
            cur = out.get(r.to_setup)
            if cur is None or minutes < cur:
                out[r.to_setup] = minutes
    return out
_EPS = timedelta(microseconds=1)


@dataclass(frozen=True)
class LotAssignment:
    line: str
    day: int                # absolute day index from the run's horizon
    sku: str
    qty: float
    seq_pos: int            # 0-based position on the line-day
    chg_from_prev_min: float


@dataclass(frozen=True)
class BucketResult:
    status: str
    objective: float | None  # recomputed from x; None when unsolved
    mip_gap: float | None
    qty: dict                # (sku, day, line) -> float, nonzero only
    skipped_future_demands: int
    n_binaries: int
    n_vars: int
    n_rows: int = 0  # model-size provenance for scale evidence


@dataclass
class WindowPlan:
    horizon_start: datetime
    days: int
    assignments: list[LotAssignment]
    bucket: BucketResult | None
    seq_status: str
    kpis: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


LINKING_M_VERSIONS = ("v1", "v2")


def linking_m_version() -> str:
    """Model version of the setup-linking M (env BRAIN_LINKING_M, default
    v1 = the M every number published before 2026-11-27 used).
      v1  M = min(cap_eff * rate, total demand + 1): ONE line-day of
          capacity, although the linking row sums x over ALL eligible
          lines, so a SKU eligible on 3 lines could not use more than
          one line-day per day (measured: 104,422 demanded, 47,465
          delivered with 3 lines idle enough to make all of it).
      v2  M = min(sum over eligible lines of cap_eff_l * rate_l,
          total demand + 1): the true per-line sum, still tight.
    Numbers of different versions are never compared (the version is in
    the run manifest and the regression class key)."""
    import os
    v = os.environ.get("BRAIN_LINKING_M", "v1")
    if v not in LINKING_M_VERSIONS:
        raise ValueError(f"BRAIN_LINKING_M={v!r}; expected one of "
                         f"{LINKING_M_VERSIONS}")
    return v


def linking_m(sku_entry, cap_eff: float, total_demand: float,
              version: str | None = None, line_cap: dict | None = None
              ) -> float:
    """sku_entry = (rate per minute, [eligible lines], setup state).
    line_cap: optional per-line effective minutes (default cap_eff for
    every line)."""
    rate, lines = sku_entry[0], sku_entry[1]
    version = version or linking_m_version()
    if version == "v1":
        return min(cap_eff * rate, total_demand + 1.0)
    per_line = sum((line_cap or {}).get(l, cap_eff) * rate for l in lines)
    return min(per_line, total_demand + 1.0)


def due_day(due: datetime, horizon_start: datetime) -> int:
    """Day index whose END is `due`: due at midnight ending day d -> d.

    Demands are due at the end of a production day; production during
    day d may serve dues ending day d. The microsecond epsilon maps a
    midnight due to the day it closes, not the day it opens.
    """
    return (due - horizon_start - _EPS).days


def _sku_data(factory: Factory) -> dict:
    """sku -> (rate_per_min, [eligible lines], setup state). Records only."""
    out = {}
    for op in factory.operations:
        produced = [m.item for m in op.materials if m.quantity > 0]
        if not produced or op.duration_per <= timedelta(0):
            continue
        rate = 1.0 / (op.duration_per.total_seconds() / 60.0)
        # de-duplicate, keep order: a plant generated with 2 lines lists
        # every line twice, which orphaned MIP columns and doubled the
        # coefficients of x in the coverage / link rows (found 2026-11-26
        # by the brute-force fix-test of the monolith probe)
        lines = list(dict.fromkeys(ld.resource for ld in op.loads))
        state = next((ld.setup for ld in op.loads if ld.setup), None)
        out[produced[0]] = (rate, lines, state)
    return out


def _recipe_data(factory: Factory) -> dict:
    """sku -> {raw material: units consumed per unit produced}. Records
    only; the per-day shared supplier pools price these."""
    out = {}
    for op in factory.operations:
        produced = [m.item for m in op.materials if m.quantity > 0]
        consumed = {m.item: -m.quantity for m in op.materials
                    if m.quantity < 0}
        if produced and consumed:
            out[produced[0]] = consumed
    return out


def build_bucket_mip(factory: Factory, horizon_start: datetime, days: int,
                     cap_min: float, chg_allowance: float,
                     inv0: dict | None = None,
                     extra_due_day0: dict | None = None,
                     cap_override: dict | None = None,
                     weights: ObjectiveWeights = DEFAULT_WEIGHTS,
                     unit_cost_extra: dict | None = None,
                     mat_cap: dict | None = None,
                     lab_cap: dict | None = None
                     ) -> tuple[MIP, dict]:
    """Assemble the level-1 MIP over [horizon_start, +days).

    Demands due outside the window are skipped and counted (rolling
    windows re-encounter them later; pre-window dues must already be
    folded into inv0 / extra_due_day0 by the rolling driver).
    """
    sku = _sku_data(factory)
    inv0 = inv0 or {}
    back0 = extra_due_day0 or {}
    dem: dict[str, list[float]] = {}
    skipped = 0
    for d in factory.demands:
        day = due_day(d.due, horizon_start)
        if not (0 <= day < days):
            skipped += 1
            continue
        dem.setdefault(d.item, [0.0] * days)[day] += d.quantity
    for s, q in back0.items():
        dem.setdefault(s, [0.0] * days)[0] += q
    active = sorted(s for s, ds in dem.items()
                    if s in sku and sum(ds) > inv0.get(s, 0.0) - 1e-9)
    lines = sorted({l for s in active for l in sku[s][1]})
    cap_eff = cap_min * (1.0 - chg_allowance)

    xidx, yidx, loidx, eidx = {}, {}, {}, {}
    n = 0
    for s in active:
        for t in range(days):
            for l in sku[s][1]:
                xidx[(s, t, l)] = n; n += 1
    for s in active:
        for t in range(days):
            yidx[(s, t)] = n; n += 1
            loidx[(s, t)] = n; n += 1
            eidx[(s, t)] = n; n += 1
    n_vars = n

    eff = {r.name: r.efficiency for r in factory.resources}
    c = np.zeros(n_vars)
    for j in yidx.values():
        c[j] = weights.setup
    for j in loidx.values():
        c[j] = weights.late
    for j in eidx.values():
        c[j] = weights.early
    if weights.energy:
        for (s, t, l), j in xidx.items():
            c[j] = weights.energy * (2.0 - eff.get(l, 1.0)) / sku[s][0]
    # Lagrangian link prices (Phase D): per-unit penalty on sku-day
    # production, from shared-pool multipliers. Linear, exact.
    if unit_cost_extra:
        for (s, t, l), j in xidx.items():
            c[j] += unit_cost_extra.get((s, t), 0.0)

    rows, cols, vals, sense, rhs = [], [], [], [], []

    fam_rows = []

    def add_row(entries, sn, rh, fam="unlabelled"):
        fam_rows.append(fam)
        r = len(rhs)
        for j, v in entries:
            rows.append(r); cols.append(j); vals.append(v)
        sense.append(sn); rhs.append(rh)

    # capacity per (line, day), net of the changeover allowance;
    # cap_override[(line, day)] replaces the RHS (0.0 = line down)
    cap_override = cap_override or {}
    for l in lines:
        for t in range(days):
            ent = [(xidx[(s, t, l)], 1.0 / sku[s][0])
                   for s in active if (s, t, l) in xidx]
            if ent:
                add_row(ent, "L", cap_override.get((l, t), cap_eff), "line-day capacity")
    # linking: sum_l x_itl <= M_it * y_it, tight M
    for s in active:
        M = linking_m(sku[s], cap_eff, sum(dem[s]))
        for t in range(days):
            ent = [(xidx[(s, t, l)], 1.0) for l in sku[s][1]]
            ent.append((yidx[(s, t)], -M))
            add_row(ent, "L", 0.0, "setup linking (includes line capacity)")
    # hard shared-resource limits (allocate-then-solve shares):
    # mat_cap[(material, day)] caps material consumed by that day's
    # production; lab_cap[day] caps line-minutes used that day
    if mat_cap or lab_cap:
        recipes = _recipe_data(factory)
        for (r, t), capv in (mat_cap or {}).items():
            ent = [(xidx[(s, t, l)], recipes.get(s, {}).get(r, 0.0))
                   for s in active for l in sku[s][1]
                   if (s, t, l) in xidx
                   and recipes.get(s, {}).get(r, 0.0)]
            if ent:
                add_row(ent, "L", capv, "shared material cap")
        for t, capv in (lab_cap or {}).items():
            ent = [(xidx[(s, t, l)], 1.0 / sku[s][0])
                   for s in active for l in sku[s][1]
                   if (s, t, l) in xidx]
            if ent:
                add_row(ent, "L", capv, "shared labour cap")
    # coverage with lateness / earliness (cumulative, per SKU-day)
    for s in active:
        cum = 0.0
        for t in range(days):
            cum += dem[s][t]
            target = cum - inv0.get(s, 0.0)
            ent = [(xidx[(s, tau, l)], 1.0)
                   for tau in range(t + 1) for l in sku[s][1]]
            ent.append((loidx[(s, t)], 1.0))
            add_row(ent, "G", target, "demand coverage (late var)")
            ent_e = [(xidx[(s, tau, l)], 1.0)
                     for tau in range(t + 1) for l in sku[s][1]]
            ent_e.append((eidx[(s, t)], -1.0))
            add_row(ent_e, "L", target, "earliness")

    lb = np.zeros(n_vars)
    ub = np.full(n_vars, np.inf)
    integ = np.zeros(n_vars)
    for j in yidx.values():
        ub[j] = 1.0
        integ[j] = 1
    A = coo_matrix((vals, (rows, cols)), shape=(len(rhs), n_vars)).tocsr()
    mip = MIP("buckets", c, A, tuple(sense), np.array(rhs, dtype=float),
              lb, ub, integ, tuple(fam_rows))
    return mip, {"x": xidx, "y": yidx, "active": active, "sku": sku,
                 "skipped": skipped}


def solve_buckets(factory: Factory, horizon_start: datetime, days: int,
                  cap_min: float, chg_allowance: float = DEFAULT_CHG_ALLOWANCE,
                  time_limit_s: float = 60.0, inv0: dict | None = None,
                  extra_due_day0: dict | None = None,
                  cap_override: dict | None = None,
                  weights: ObjectiveWeights = DEFAULT_WEIGHTS,
                  unit_cost_extra: dict | None = None,
                  mat_cap: dict | None = None,
                  lab_cap: dict | None = None
                  ) -> BucketResult:
    """Level 1 solve; objective recomputed from the assignment.

    unit_cost_extra: optional {(sku, day): per-unit penalty} - the
    Lagrangian link prices of Phase D. When given, the RETURNED
    objective INCLUDES the penalties: that penalized value is exactly
    the per-plant Lagrangian dual value, which is what the coupled
    coordinator needs. True-cost recomputation from the assignment is
    the coupled module's job, never assumed here."""
    mip, maps = build_bucket_mip(factory, horizon_start, days, cap_min,
                                 chg_allowance, inv0, extra_due_day0,
                                 cap_override, weights, unit_cost_extra,
                                 mat_cap=mat_cap, lab_cap=lab_cap)
    if not maps["active"]:
        return BucketResult("no-demand", 0.0, 0.0, {}, maps["skipped"], 0, 0)
    res = solve_mip(mip, time_limit_s=time_limit_s, mip_rel_gap=0.0)
    n_bin = int(mip.integrality.sum())
    n_rows = int(mip.A.shape[0])
    if res["x"] is None:
        return BucketResult(str(res["status"]), None, None, {},
                            maps["skipped"], n_bin, len(mip.c), n_rows)
    x = res["x"]
    qty = {k: float(x[j]) for k, j in maps["x"].items() if x[j] > 1e-6}
    return BucketResult(str(res["status"]), res["objective"],
                        res.get("gap"), qty, maps["skipped"], n_bin,
                        len(mip.c), n_rows)


def solve_day_sequences(factory: Factory, bucket: BucketResult,
                        cap_min: float, window_start_day: int = 0,
                        time_limit_s: float = 10.0
                        ) -> tuple[list[LotAssignment], list[str]]:
    """Level 2: exact per line-day sequencing with the setup matrix.

    One CP-SAT circuit per line-day over its assigned lots plus a dummy
    start node; minimize total changeover subject to the line-day
    capacity. Emits absolute day indexes (window_start_day + t).
    """
    from ortools.sat.python import cp_model

    sku = _sku_data(factory)
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix)
               for r in factory.resources}
    by_ld: dict[tuple[str, int], list[tuple[str, float]]] = {}
    for (s, t, l), q in bucket.qty.items():
        by_ld.setdefault((l, t), []).append((s, q))
    assignments: list[LotAssignment] = []
    problems: list[str] = []
    for (l, t) in sorted(by_ld):
        lots = sorted(by_ld[(l, t)])
        mtx = res_mtx.get(l)
        if mtx is None:
            problems.append(f"{l} day {t}: no setup matrix")
            continue
        prod = [math.ceil(q / sku[s.split("#")[0]][0] - 1e-9)
                for s, q in lots]
        states = [sku[s.split("#")[0]][2] for s, q in lots]
        n = len(lots)
        budget = int(cap_min) - sum(prod)
        if budget < 0:
            problems.append(f"{l} day {t}: production {sum(prod)} min "
                            f"alone exceeds capacity {cap_min}")
            continue
        m = cp_model.CpModel()
        arcs, arc_cost = [], []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                lit = m.new_bool_var(f"a{i}_{j}")
                arcs.append((i, j, lit))
                d = mtx.duration_between(states[i], states[j])
                if d is None:
                    problems.append(f"{l} day {t}: no changeover rule "
                                    f"{states[i]} -> {states[j]}")
                    continue
                arc_cost.append((lit, int(d.total_seconds() // 60)))
        for i in range(n):
            lit = m.new_bool_var(f"start_{i}")
            arcs.append((n, i, lit)); arc_cost.append((lit, 0))
            lit = m.new_bool_var(f"end_{i}")
            arcs.append((i, n, lit)); arc_cost.append((lit, 0))
        m.add_circuit(arcs)
        total_chg = sum(lit * cst for lit, cst in arc_cost)
        m.add(total_chg <= budget)
        m.minimize(total_chg)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        status = solver.solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            problems.append(f"{l} day {t}: sequencing infeasible "
                            f"({solver.status_name(status)}); changeover "
                            "allowance too tight for this mix")
            continue
        succ = {i: j for (i, j, lit) in arcs if solver.value(lit)}
        order, node = [], n
        for _ in range(n):
            node = succ[node]
            order.append(node)
        prev = None
        for pos, i in enumerate(order):
            chg = 0.0 if prev is None else matrices_duration(mtx, prev,
                                                             states[i])
            assignments.append(LotAssignment(l, window_start_day + t,
                                             lots[i][0].split("#")[0],
                                             lots[i][1], pos, chg))
            prev = states[i]
    return assignments, problems


def matrices_duration(mtx, a: str, b: str) -> float:
    d = mtx.duration_between(a, b)
    return math.inf if d is None else d.total_seconds() / 60.0


def chunk_lots(sku: dict, qty: dict, cap_min: float
               ) -> dict[int, list[tuple[str, float]]]:
    """(sku, day) quantities -> per-day chunked lots named 'SKU#k'.

    Chunks never exceed half a line-day of production so any two share
    a line; chunks of one SKU share its setup state, so sequencing
    places them adjacently at zero changeover when useful.
    """
    day_lots: dict[int, list[tuple[str, float]]] = {}
    for (s, t), q in sorted(qty.items()):
        rate = sku[s][0]
        max_chunk = math.floor(0.5 * cap_min * rate)
        n_chunks = max(1, math.ceil(q / max_chunk))
        for k in range(n_chunks):
            lo = k * max_chunk
            chunk = min(q, lo + max_chunk) - lo
            if chunk > 1e-6:
                day_lots.setdefault(t, []).append((f"{s}#{k}", chunk))
    return day_lots



def _identical_line_groups(lines: list[str],
                           chunks: list[tuple[str, float]],
                           sku: dict, res_mtx: dict
                           ) -> list[list[str]]:
    """Groups of lines that are interchangeable for this day's model:
    same eligible-SKU set over the day's SKUs and same setup matrix.
    Only groups of size >= 2 are returned (nothing to order in a
    singleton). Williams ch.6 symmetry."""
    day_skus = sorted({name.split("#")[0] for name, _ in chunks})
    groups: dict[tuple, list[str]] = {}
    for l in lines:
        elig = frozenset(snm for snm in day_skus if l in sku[snm][1])
        mtx = res_mtx.get(l)
        groups.setdefault((elig, getattr(mtx, "name", None)),
                          []).append(l)
    return [sorted(g) for g in groups.values() if len(g) >= 2]

def solve_day_exact(factory: Factory, chunks: list[tuple[str, float]],
                    day: int, cap_min: float, window_start_day: int = 0,
                    time_limit_s: float = 60.0,
                    hint: dict | None = None,
                    fixed: dict | None = None,
                    line_blacklist: frozenset | None = None,
                    weights: "ObjectiveWeights" = None,
                    num_workers: int | None = None,
                    unknown_attempts: int = 3,
                    notes: list | None = None,
                    max_limit_s: float = 120.0
                    ) -> tuple[list[LotAssignment], list[str]]:
    """One day, one integrated CP-SAT model, exact at the true cost level.

    Lots of the same setup state are interchangeable for changeover
    purposes (same state -> zero changeover), so the model decides:
    (i) which eligible line each chunk runs on (exactly one),
    (ii) per line, a circuit over the distinct STATES present on it.
    The exact lot-level cost follows: concatenate each state group's
    chunks; changeovers happen only between state groups, priced by the
    setup matrix. Capacity per line-day: production + exact state-tour
    changeovers <= cap_min. No allowances, no reserves at this level.
    A hint (chunk -> line, e.g. from the bucket level) seeds the search
    but never constrains it (CP-SAT Primer, Coding Patterns).
    """
    from ortools.sat.python import cp_model

    sku = _sku_data(factory)
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix)
               for r in factory.resources}
    m = cp_model.CpModel()
    prod = {name: math.ceil(q / sku[name.split("#")[0]][0] - 1e-9)
            for name, q in chunks}
    state = {name: sku[name.split("#")[0]][2] for name, q in chunks}
    qty_of = dict(chunks)
    blacklist = line_blacklist or frozenset()
    x = {}
    for name, _ in chunks:
        for l in sku[name.split("#")[0]][1]:
            if l not in blacklist:
                x[(name, l)] = m.new_bool_var(f"x_{name}_{l}")
    for name, _ in chunks:
        eligible = [x[(name, l)] for l in sku[name.split("#")[0]][1]
                    if (name, l) in x]
        if not eligible:
            return [], [f"day {day}: {name} has no eligible line"]
        m.add_exactly_one(eligible)
    if hint is None:
        # Automatic greedy warm start (CP-SAT Primer, Coding Patterns):
        # biggest chunks first onto the least-loaded eligible line. A
        # hint seeds the search but never constrains it. Measured need:
        # dense days (130+ chunks) with a single CP-SAT worker and no
        # incumbent seed can burn the whole budget without finding ANY
        # feasible point (plant 43 day 5: UNKNOWN after 100 s); the
        # greedy hint makes the same model decide (fabric signature
        # 3b7e07ee1b2f).
        # capacity-aware, in minutes: production + a conservative
        # changeover charge (cheapest incoming arc per extra state
        # group), preferring lines that stay under 90% of the day
        # capacity. Measured: quantity-only seeds overload lines on
        # dense days and give CP-SAT nothing repairable (plant 155
        # day 4, 138 chunks, UNKNOWN at 110 s).
        min_in_h = _min_incoming_changeover(factory)
        load: dict[str, float] = {}  # line -> minutes used
        tail_h: dict[str, str] = {}
        hint = {}
        for name, q in sorted(chunks, key=lambda cq: -cq[1]):
            elig = [l for l in sku[name.split("#")[0]][1]
                    if (name, l) in x]
            if not elig:
                continue
            st = state[name]
            def _hcost(l, name=name, st=st):
                chg = 0.0
                prev = tail_h.get(l)
                if prev is not None and prev != st:
                    chg = min_in_h.get(st, 0.0)
                e = prod[name] + chg
                over = max(0.0, load.get(l, 0.0) + e - 0.9 * cap_min)
                return (over, load.get(l, 0.0))
            line = min(elig, key=_hcost)
            chg = 0.0
            prev = tail_h.get(line)
            if prev is not None and prev != st:
                chg = min_in_h.get(st, 0.0)
            hint[name] = line
            load[line] = load.get(line, 0.0) + prod[name] + chg
            tail_h[line] = st
    if hint:
        for (name, l), var in x.items():
            m.add_hint(var, 1 if hint.get(name) == l else 0)
    if fixed:
        for name, l in fixed.items():
            if (name, l) in x:
                m.add(x[(name, l)] == 1)
            else:
                return [], [f"day {day}: fixed chunk {name} cannot "
                            f"run on {l}"]
    lines = sorted({l for name, _ in chunks
                    for l in sku[name.split("#")[0]][1]})
    # Symmetry breaking (Williams ch.6; patterns.symmetry_break_order):
    # lines that are interchangeable FOR THIS DAY (same eligible SKU
    # set, same setup matrix; efficiency is a bucket-level concept,
    # rates are SKU-level here) produce permuted duplicate optima, so
    # order their production loads. Sound: any solution has a line-
    # permuted twin with non-increasing loads and identical cost.
    # Lines pinned by `fixed` are excluded - a pinned chunk ties a
    # chunk to a NAMED line, so no permutation of it is valid.
    pinned = set(fixed.values()) if fixed else set()
    for group in _identical_line_groups(lines, chunks, sku, res_mtx):
        free = [l for l in group if l not in pinned]
        for l1, l2 in zip(free, free[1:]):
            load1 = sum(prod[c] * x[(c, l1)] for c, _ in chunks
                        if (c, l1) in x)
            load2 = sum(prod[c] * x[(c, l2)] for c, _ in chunks
                        if (c, l2) in x)
            m.add(load1 >= load2)
    state_chunks: dict[tuple[str, str], list[str]] = {}
    for l in lines:
        for name, _ in chunks:
            if (name, l) in x:
                state_chunks.setdefault((l, state[name]), []).append(name)
    line_data: dict[str, tuple] = {}
    total_cost_terms: list[tuple] = []
    for l in lines:
        mtx = res_mtx.get(l)
        if mtx is None:
            return [], [f"{l}: no setup matrix"]
        states = sorted(s for (ll, s) in state_chunks if ll == l)
        if not states:
            continue
        p_st = {s: m.new_bool_var(f"p_{l}_{s}") for s in states}
        for s in states:
            members = state_chunks[(l, s)]
            for name in members:
                m.add(x[(name, l)] <= p_st[s])
            m.add(sum(x[(name, l)] for name in members) >= p_st[s])
        n = len(states)
        D = n
        arcs, arc_costs = [], []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                d = mtx.duration_between(states[i], states[j])
                if d is None:
                    return [], [f"{l} day {day}: no changeover rule "
                                f"{states[i]} -> {states[j]}"]
                lit = m.new_bool_var(f"t_{l}_{i}_{j}")
                arcs.append((i, j, lit))
                arc_costs.append((lit, int(d.total_seconds() // 60)))
                m.add(lit <= p_st[states[i]])
                m.add(lit <= p_st[states[j]])
            st = m.new_bool_var(f"st_{l}_{i}")
            arcs.append((D, i, st)); arc_costs.append((st, 0))
            m.add(st <= p_st[states[i]])
            en = m.new_bool_var(f"en_{l}_{i}")
            arcs.append((i, D, en)); arc_costs.append((en, 0))
            m.add(en <= p_st[states[i]])
        for i in range(n):
            sl = m.new_bool_var(f"sl_{l}_{i}")
            arcs.append((i, i, sl)); arc_costs.append((sl, 0))
            m.add(sl == 1 - p_st[states[i]])
        dsl = m.new_bool_var(f"dsl_{l}")
        arcs.append((D, D, dsl)); arc_costs.append((dsl, 0))
        for i in range(n):
            m.add(dsl <= 1 - p_st[states[i]])
        m.add_circuit(arcs)
        members_all = [name for s in states for name in state_chunks[(l, s)]]
        load = (sum(prod[c] * x[(c, l)] for c in members_all)
                + sum(lit * cst for lit, cst in arc_costs))
        m.add(load <= int(cap_min))
        line_data[l] = (states, D, arcs)
        total_cost_terms.extend(arc_costs)
    if weights is not None and weights.energy:
        # energy slider: per-chunk-line production cost, x1000 for int
        eff = {r.name: r.efficiency for r in factory.resources}
        for (name, l), var in x.items():
            per_min = weights.energy * (2.0 - eff.get(l, 1.0))
            total_cost_terms.append(
                (var, int(round(per_min * prod[name] * 1000))))
    m.minimize(sum(lit * cst for lit, cst in total_cost_terms))
    solver = cp_model.CpSolver()
    if num_workers is not None:
        solver.parameters.num_workers = num_workers
    # UNKNOWN means "undecided within the limit", not "unrealizable":
    # escalate the limit (x4 per attempt, capped) before reporting.
    # INFEASIBLE is a proof and is never retried.
    limit = time_limit_s
    status = None
    for attempt in range(max(1, unknown_attempts)):
        solver.parameters.max_time_in_seconds = limit
        status = solver.solve(m)
        if status != cp_model.UNKNOWN or attempt == max(1, unknown_attempts) - 1:
            break
        limit = min(limit * 4.0, max_limit_s)
    if status == cp_model.UNKNOWN and fixed is None and hint:
        # Fix-and-optimize fallback (measured need: plant 155 day 4,
        # 138 chunks, single worker, still UNKNOWN at 110 s even with a
        # greedy seed - fabric signature 3b7e07ee1b2f; seeding quality
        # saturates at ~133 chunks). Pin the largest half of the chunks
        # to lines chosen by a CAPACITY-AWARE greedy (production minutes
        # + changeover estimate <= cap_min per line) and re-solve the
        # rest exactly. Two honesty guards, both measured: capacity-
        # blind pins can overload a line (first version proved
        # INFEASIBLE-under-pins), and an INFEASIBLE proof under pins
        # says NOTHING about the day itself - so a failed fallback
        # falls through to the original undecided report, never to an
        # INFEASIBLE claim. A successful fallback is not silent: the
        # restriction is reported through `notes`.
        load: dict[str, float] = {}
        tail_st: dict[str, str] = {}
        min_in = _min_incoming_changeover(factory)
        pinned = {}
        for name, q in sorted(chunks, key=lambda cq: -cq[1]):
            if len(pinned) >= max(1, len(chunks) // 4):
                break
            st = state[name]
            best = None
            best_chg = 0.0
            for l in sku[name.split("#")[0]][1]:
                if (name, l) not in x:
                    continue
                chg = 0.0
                prev = tail_st.get(l)
                if prev is not None and prev != st:
                    # conservative: cheapest incoming arc to this state,
                    # not the optimistic tail->state entry (the exact
                    # tour pays at least this per extra state group)
                    chg = min_in.get(st, 0.0)
                if load.get(l, 0.0) + prod[name] + chg <= 0.9 * cap_min:
                    if best is None or load.get(l, 0.0) < load.get(best, 0.0):
                        best, best_chg = l, chg
            if best is None:
                break  # first chunk that fits nowhere: stop pinning
            pinned[name] = best
            load[best] = load.get(best, 0.0) + prod[name] + best_chg
            tail_st[best] = st
        if pinned:
            asg, probs = solve_day_exact(
                factory, chunks, day, cap_min, window_start_day,
                min(max(60.0, time_limit_s), max_limit_s), hint=hint,
                fixed=pinned,
                line_blacklist=line_blacklist, weights=weights,
                num_workers=num_workers, unknown_attempts=1,
                notes=notes)
            if asg:
                if notes is not None:
                    notes.append(
                        f"day {day}: decided with fixed-prefix "
                        f"restriction (largest {len(pinned)} of "
                        f"{len(chunks)} chunks pinned to capacity-aware "
                        "greedy lines)")
                return asg, probs
            # fallback failed: pins were our choice, so the day stays
            # undecided - fall through to the honest UNKNOWN report
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        name = solver.status_name(status)
        if name == "INFEASIBLE":
            return [], [f"day {day}: exact assignment+sequencing "
                        "INFEASIBLE; the bucket level's day mix cannot "
                        "be realized with true changeovers"]
        return [], [f"day {day}: exact assignment+sequencing {name} "
                    f"after {limit:.0f}s; undecided, not disproven - "
                    "retry with a larger sequencing time limit"]
    assignments: list[LotAssignment] = []
    for l, (states, D, arcs) in line_data.items():
        present = [i for i in range(len(states))
                   if solver.value(next(lit for (a, b, lit) in arcs
                                        if a == i and b == i)) == 0]
        if not present:
            continue
        succ = {i: j for (i, j, lit) in arcs
                if i != j and solver.value(lit)}
        order, node = [], D
        while True:
            node = succ.get(node, D)
            if node == D:
                break
            order.append(node)
        pos = 0
        prev = None
        for i in order:
            s_i = states[i]
            members = sorted(c for c in state_chunks[(l, s_i)]
                             if solver.value(x[(c, l)]))
            for k, name in enumerate(members):
                if prev is None or k > 0:
                    chg = 0.0  # line start, or same state as previous lot
                else:
                    chg = matrices_duration(res_mtx[l], prev, s_i)
                assignments.append(LotAssignment(l, window_start_day + day,
                                                 name.split("#")[0],
                                                 qty_of[name], pos, chg))
                pos += 1
                prev = s_i
    return assignments, []


def solve_window(factory: Factory, horizon_start: datetime, days: int,
                 cap_min: float, chg_allowance: float = DEFAULT_CHG_ALLOWANCE,
                 bucket_time_s: float = 60.0, seq_time_s: float = 10.0,
                 inv0: dict | None = None,
                 extra_due_day0: dict | None = None,
                 window_start_day: int = 0,
                 cap_override: dict | None = None,
                 weights: ObjectiveWeights = DEFAULT_WEIGHTS,
                 seq_num_workers: int | None = None
                 ) -> WindowPlan:
    """One window: buckets -> sequencing -> independent validation."""
    bucket = solve_buckets(factory, horizon_start, days, cap_min,
                           chg_allowance, bucket_time_s, inv0,
                           extra_due_day0, cap_override, weights)
    if bucket.objective is None:
        return WindowPlan(horizon_start, days, [], bucket,
                          f"bucket-level failed: {bucket.status}",
                          problems=[f"bucket level: {bucket.status}"])
    # collapse line-split quantities to (sku, day), chunk, solve each
    # day exactly (assignment + sequencing in one model)
    qty: dict[tuple[str, int], float] = {}
    for (s, t, l), q in bucket.qty.items():
        qty[(s, t)] = qty.get((s, t), 0.0) + q
    sku = _sku_data(factory)
    day_lots = chunk_lots(sku, qty, cap_min)
    # bucket line split as per-chunk hints: chunk -> its SKU's largest
    # bucket line that day
    day_hint: dict[int, dict[str, str]] = {}
    for (s, t, l), q in bucket.qty.items():
        cur = day_hint.setdefault(t, {}).get(f"{s}")
        best_line, best_q = None, -1.0
        for (s2, t2, l2), q2 in bucket.qty.items():
            if s2 == s and t2 == t and q2 > best_q:
                best_line, best_q = l2, q2
        day_lot_names = [n for n, _ in day_lots.get(t, [])
                         if n.split("#")[0] == s]
        for n in day_lot_names:
            day_hint[t][n] = best_line
    assignments: list[LotAssignment] = []
    problems: list[str] = []
    repair_moves: list[str] = []
    min_in = _min_incoming_changeover(factory)
    due_by_sku: dict[str, int] = {}
    for d in factory.demands:
        dd = due_day(d.due, horizon_start)
        if d.item in sku:
            due_by_sku[d.item] = max(due_by_sku.get(d.item, -1), dd)
    pending: dict[int, list[tuple[str, float]]] = {t: list(lots)
                                                   for t, lots in
                                                   day_lots.items()}
    day_notes: list[str] = []
    for t in range(days):
        lots = pending.pop(t, [])
        if not lots:
            continue
        day_asg: list[LotAssignment] = []
        day_problems: list[str] = []
        for attempt in range(MAX_DAY_REPAIRS + 1):
            # Dense-day budget (measured: registry fc9f56ec5ce7 -
            # days above the ~130-chunk hint-saturation point can
            # stay UNKNOWN at the 120 s cap even with the full
            # 3b7e07ee1b2f heal chain; 2 of 249,179 assignments at
            # 53M vars). Dense days start at a bigger budget and a
            # higher escalation cap; normal days are untouched.
            dense = len(lots) > DENSE_DAY_CHUNKS
            day_asg, day_problems = solve_day_exact(
                factory, lots, t, cap_min, window_start_day,
                max(seq_time_s, DENSE_DAY_BUDGET_S) if dense
                else seq_time_s,
                hint=day_hint.get(t), weights=weights,
                num_workers=seq_num_workers, notes=day_notes,
                max_limit_s=DENSE_DAY_MAX_S if dense else 120.0)
            if not day_problems:
                break
            if not any("INFEASIBLE" in p for p in day_problems):
                break  # UNKNOWN/error: not repairable by eviction
            if attempt == MAX_DAY_REPAIRS:
                break
            # evict the highest-pressure chunk among those that still
            # have due-date slack (moving them is free); only when none
            # can move without lateness, evict the highest-pressure
            # chunk outright. Pressure = unavoidable incoming changeover
            # of its state, then its production minutes.
            def _pressure(i):
                name, q = lots[i]
                s = name.split("#")[0]
                slack = due_by_sku.get(s, t) > t
                return (slack, min_in.get(sku[s][2], 0.0),
                        q / sku[s][0])
            evict_i = max(range(len(lots)), key=_pressure)
            name, q = lots.pop(evict_i)
            repair_moves.append(
                f"day {t}: {name} ({q:.0f} units) moved to day {t + 1} "
                "after infeasible day mix")
            if t + 1 < days:
                pending.setdefault(t + 1, []).append((name, q))
            else:
                problems.append(
                    f"day {t}: {name} ({q:.0f} units) could not be "
                    "produced inside the horizon (repair moved it past "
                    "the last day)")
        assignments.extend(day_asg)
        problems.extend(day_problems)
    plan = WindowPlan(horizon_start, days, assignments, bucket,
                      "ok" if not problems else "sequencing problems",
                      problems=list(problems))
    v_problems, kpis = validate_window_plan(factory, plan, cap_min,
                                            inv0=inv0,
                                            day0=window_start_day)
    plan.problems.extend(v_problems)
    kpis["repair_moves"] = repair_moves
    if day_notes:
        # restricted days are valid assignments, not problems; they
        # belong in the measured record, not the verdict
        kpis["restricted_days"] = list(day_notes)
    plan.kpis = kpis
    bound = bucket.objective
    if bound and bound > 0 and kpis.get("proxy_cost") is not None:
        # labeled: bucket objective is a RELAXATION bound (capacity
        # allowance + setup-count proxy), not the true problem's bound
        plan.kpis["gap_vs_bucket_relaxation"] = \
            (kpis["proxy_cost"] - bound) / bound
    return plan


def _daily_walk(factory: Factory, horizon_start: datetime, days: int,
                assignments: list[LotAssignment], inv0: dict | None = None,
                day0: int = 0) -> dict:
    """Per-SKU day-by-day stock/backlog from returned assignments."""
    inv0 = inv0 or {}
    dem: dict[str, list[float]] = {}
    for d in factory.demands:
        day = due_day(d.due, horizon_start)
        if 0 <= day < days:
            dem.setdefault(d.item, [0.0] * days)[day] += d.quantity
    prod: dict[str, list[float]] = {}
    for a in assignments:
        day = a.day - day0
        if 0 <= day < days:
            prod.setdefault(a.sku, [0.0] * days)[day] += a.qty
    backlog_days = 0.0
    early_days = 0.0
    end_backlog = 0.0
    for s in sorted(set(dem) | set(prod)):
        stock = inv0.get(s, 0.0)
        for t in range(days):
            stock += prod.get(s, [0.0] * days)[t]
            stock -= dem.get(s, [0.0] * days)[t]
            if stock < 0:
                backlog_days += -stock
            else:
                early_days += stock
        end_backlog += max(0.0, -stock)
    return {"backlog_unit_days": backlog_days, "early_unit_days": early_days,
            "backlog_units_end": end_backlog}


def validate_window_plan(factory: Factory, plan: WindowPlan,
                         cap_min: float, inv0: dict | None = None,
                         day0: int = 0) -> tuple[list[str], dict]:
    """Independent check from records + returned assignments only.

    Capacity per line-day with exact matrix changeovers in the returned
    sequence order; per-SKU daily stock walk for lateness/earliness;
    KPIs recomputed, never read from solver output.
    """
    from ..guards.invariants import assignment_findings, enforce
    sku = _sku_data(factory)
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix) for r in factory.resources}
    # runtime invariants on every returned lot (value + placement):
    # record mode lands them in problems, strict mode pauses the run
    problems: list[str] = enforce(
        assignment_findings(plan.assignments, plan.days, day0),
        "validate_window_plan")
    by_ld: dict[tuple[str, int], list[LotAssignment]] = {}
    for a in plan.assignments:
        by_ld.setdefault((a.line, a.day - day0), []).append(a)
    chg_total = 0.0
    for (l, t), lots in sorted(by_ld.items()):
        lots.sort(key=lambda a: a.seq_pos)
        mtx = res_mtx.get(l)
        total = 0.0
        prev = None
        seen_pos: set[int] = set()
        for a in lots:
            if a.seq_pos in seen_pos:
                problems.append(f"{l} day {t}: duplicate seq_pos {a.seq_pos}")
            seen_pos.add(a.seq_pos)
            if a.sku not in sku:
                problems.append(f"{l} day {t}: unknown sku {a.sku}")
                continue
            rate, lines, state = sku[a.sku]
            if l not in lines:
                problems.append(f"{l} day {t}: {a.sku} not eligible on {l}")
            total += a.qty / rate
            if prev is not None:
                if mtx is None:
                    problems.append(f"{l}: no setup matrix")
                else:
                    d = mtx.duration_between(prev, state)
                    if d is None:
                        problems.append(f"{l} day {t}: no rule "
                                        f"{prev} -> {state}")
                    else:
                        chg = d.total_seconds() / 60.0
                        total += chg
                        chg_total += chg
                        if abs(chg - a.chg_from_prev_min) > 0.5:
                            problems.append(
                                f"{l} day {t} pos {a.seq_pos}: recorded "
                                f"changeover {a.chg_from_prev_min} != {chg}")
            prev = state
        if not (total <= cap_min + 0.05):   # NaN-safe: NaN fails too
            problems.append(f"{l} day {t}: {total:.1f} min > {cap_min}")
    walk = _daily_walk(factory, plan.horizon_start, plan.days,
                       plan.assignments, inv0, day0)
    setups = len({(a.sku, a.day) for a in plan.assignments})
    proxy_cost = (SETUP_W * setups + LATE_W * walk["backlog_unit_days"]
                  + EARLY_W * walk["early_unit_days"])
    eff = {r.name: r.efficiency for r in factory.resources}
    prod_min = 0.0
    energy_proxy = 0.0
    for a in plan.assignments:
        if a.sku in sku:
            minutes = a.qty / sku[a.sku][0]
            prod_min += minutes
            energy_proxy += minutes * (2.0 - eff.get(a.line, 1.0))
    kpis = {"changeover_minutes": chg_total,
            "setups": setups,
            "assignments": len(plan.assignments),
            "proxy_cost": proxy_cost,
            "production_minutes": prod_min,
            "energy_proxy": energy_proxy,
            **walk}
    return problems, kpis


@dataclass
class RollingResult:
    horizon_start: datetime
    days: int                    # total simulated days
    assignments: list[LotAssignment]   # frozen only, absolute days
    windows: list[WindowPlan]
    problems: list[str]
    kpis: dict


def solve_rolling(factory: Factory, horizon_start: datetime,
                  window_days: int, freeze_days: int, n_windows: int,
                  cap_min: float,
                  chg_allowance: float = DEFAULT_CHG_ALLOWANCE,
                  bucket_time_s: float = 60.0,
                  seq_time_s: float = 10.0,
                  window_solver=None,
                  seq_num_workers: int | None = None) -> RollingResult:
    """Rolling-horizon driver: solve, freeze freeze_days, roll, repeat.

    Inventory/backlog netting per SKU over the frozen days carries the
    state forward; overproduction rides as inv0, shortfalls as
    backordered demand due on day 0 of the next window.

    window_solver defaults to solve_window; a decomposed solver (Stage
    4) with the same call contract slots in without changing the
    freeze/netting logic.
    """
    if not (1 <= freeze_days <= window_days):
        raise ValueError("freeze_days must be in [1, window_days]")
    inv: dict[str, float] = {}
    back: dict[str, float] = {}
    frozen: list[LotAssignment] = []
    windows: list[WindowPlan] = []
    problems: list[str] = []
    for w in range(n_windows):
        start_day = w * freeze_days
        ws = horizon_start + timedelta(days=start_day)
        solve = window_solver or solve_window
        plan = solve(factory, ws, window_days, cap_min,
                     chg_allowance, bucket_time_s, seq_time_s,
                     inv0=inv, extra_due_day0=back,
                     window_start_day=start_day,
                     seq_num_workers=seq_num_workers)
        windows.append(plan)
        problems.extend(f"window {w}: {p}" for p in plan.problems)
        if plan.bucket is None or plan.bucket.objective is None:
            problems.append(f"window {w}: bucket level failed "
                            f"({plan.bucket.status if plan.bucket else '?'})")
            break
        keep = [a for a in plan.assignments if
                start_day <= a.day < start_day + freeze_days]
        frozen.extend(keep)
        prod_f: dict[str, float] = defaultdict(float)
        for a in keep:
            prod_f[a.sku] += a.qty
        dem_f: dict[str, float] = defaultdict(float)
        for d in factory.demands:
            dd = due_day(d.due, horizon_start)
            if start_day <= dd < start_day + freeze_days:
                dem_f[d.item] += d.quantity
        for s in set(inv) | set(back) | set(prod_f) | set(dem_f):
            net = inv.get(s, 0.0) + prod_f.get(s, 0.0) \
                - dem_f.get(s, 0.0) - back.get(s, 0.0)
            inv[s] = max(0.0, net)
            back[s] = max(0.0, -net)
    total_days = n_windows * freeze_days
    full = WindowPlan(horizon_start, total_days, frozen, None, "frozen")
    v_problems, kpis = validate_window_plan(factory, full, cap_min)
    problems.extend(v_problems)
    kpis["backlog_units_end"] = sum(back.values())
    return RollingResult(horizon_start, total_days, frozen, windows,
                         problems, kpis)
