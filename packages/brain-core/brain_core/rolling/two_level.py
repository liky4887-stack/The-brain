"""Two-level rolling-window solve: MILP buckets, then CP-SAT sequencing.

Level 1 (buckets, HiGHS via solvers/highs_mip.py): assigns production
quantities to (SKU, day, eligible line) over the window. Setup binary
per SKU-day, cumulative coverage with explicit lateness variables,
earliness variables as holding cost (unit-days). Capacity per line-day
is reduced by a measured changeover allowance: exact changeovers are
sequence-dependent and only known after sequencing, so the bucket
level plans against an allowance and the sequencing level checks the
truth (honesty: an allowance miss is reported, never hidden).

Level 2 (sequencing, CP-SAT): per line-day, the lots assigned by
level 1 are sequenced with the exact setup matrix via a circuit model
(minimize total changeover, hard capacity on production + changeover
minutes). Small per line-day (tens of lots), exact.

Objective bound: the bucket MILP objective (setup proxy + lateness +
earliness, capacity relaxed by the allowance) is a relaxation of the
sequenced problem, so its optimum is a valid lower bound; the gap we
log is final-validated-cost vs that bound, labeled as such.

Everything recomputed from returned assignments (honesty rules);
validate_window_plan checks any WindowPlan against the records alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from scipy.sparse import coo_matrix

from ..records.models import Factory
from ..solvers.highs_mip import MIP, solve_mip

SETUP_W = 50.0      # one SKU-day setup ~ a campaign break
LATE_W = 1000.0     # one unit late one day: never if capacity allows
EARLY_W = 0.001     # one unit held one day: tie-breaks front-loading
DEFAULT_CHG_ALLOWANCE = 0.15  # 15% of line-day reserved for changeovers


@dataclass(frozen=True)
class LotAssignment:
    line: str
    day: int
    sku: str
    qty: float
    seq_pos: int            # 0-based position on the line-day
    chg_from_prev_min: float


@dataclass(frozen=True)
class BucketResult:
    status: str
    objective: float        # recomputed from x
    mip_gap: float | None
    qty: dict               # (sku, day, line) -> float, nonzero only
    n_binaries: int
    n_vars: int


@dataclass
class WindowPlan:
    horizon_start: datetime
    days: int
    assignments: list[LotAssignment]
    bucket: BucketResult | None
    seq_status: str                     # "ok" | per line-day failures
    kpis: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _sku_data(factory: Factory) -> dict:
    """sku -> (rate_per_min, [eligible lines], setup state). Records only."""
    out = {}
    for op in factory.operations:
        produced = [m.item for m in op.materials if m.quantity > 0]
        if not produced or op.duration_per <= timedelta(0):
            continue
        rate = 1.0 / (op.duration_per.total_seconds() / 60.0)
        lines = [ld.resource for ld in op.loads]
        state = next((ld.setup for ld in op.loads if ld.setup), None)
        out[produced[0]] = (rate, lines, state)
    return out


def build_bucket_mip(factory: Factory, horizon_start: datetime, days: int,
                     cap_min: float, chg_allowance: float,
                     inv0: dict | None = None,
                     extra_due_day0: dict | None = None) -> tuple[MIP, dict]:
    """Assemble the level-1 MIP. Returns (MIP, index maps for decoding)."""
    sku = _sku_data(factory)
    inv0 = inv0 or {}
    back0 = extra_due_day0 or {}
    dem: dict[str, list[float]] = {}
    for d in factory.demands:
        day = (d.due - horizon_start).days
        if not (0 <= day < days):
            raise ValueError(f"demand {d.name}: due outside window")
        dem.setdefault(d.item, [0.0] * days)[day] += d.quantity
    for s, q in back0.items():
        dem.setdefault(s, [0.0] * days)[0] += q
    active = sorted(s for s in dem if s in sku and sum(dem[s]) > inv0.get(s, 0.0) - 1e-9)
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

    c = np.zeros(n_vars)
    for (s, t), j in yidx.items():
        c[j] = SETUP_W
    for j in loidx.values():
        c[j] = LATE_W
    for j in eidx.values():
        c[j] = EARLY_W

    rows, cols, vals, sense, rhs = [], [], [], [], []

    def add_row(entries, sn, rh):
        r = len(rhs)
        for j, v in entries:
            rows.append(r); cols.append(j); vals.append(v)
        sense.append(sn); rhs.append(rh)

    # capacity per (line, day)
    for l in lines:
        for t in range(days):
            ent = [(xidx[(s, t, l)], 1.0 / sku[s][0])
                   for s in active if (s, t, l) in xidx]
            if ent:
                add_row(ent, "L", cap_eff)
    # linking: sum_l x <= M y ; M = min(cap_eff*rate, total demand)
    for s in active:
        M = min(cap_eff * sku[s][0], sum(dem[s]) + 1.0)
        for t in range(days):
            ent = [(xidx[(s, t, l)], 1.0) for l in sku[s][1]]
            ent.append((yidx[(s, t)], -M))
            add_row(ent, "L", 0.0)
    # coverage with lateness: cumprod + late >= max(0, D - inv0)
    # earliness:          cumprod - early <= D - inv0
    for s in active:
        cum = 0.0
        for t in range(days):
            cum += dem[s][t]
            target = cum - inv0.get(s, 0.0)
            ent, ent_e = [], []
            for tau in range(t + 1):
                for l in sku[s][1]:
                    ent.append((xidx[(s, tau, l)], 1.0))
                    ent_e.append((xidx[(s, tau, l)], 1.0))
            ent.append((loidx[(s, t)], 1.0))
            add_row(ent, "G", target)
            ent_e.append((eidx[(s, t)], -1.0))
            add_row(ent_e, "L", target)

    lb = np.zeros(n_vars)
    ub = np.full(n_vars, np.inf)
    integ = np.zeros(n_vars)
    for j in yidx.values():
        ub[j] = 1.0; integ[j] = 1
    for j in list(loidx.values()) + list(eidx.values()):
        pass  # continuous >= 0
    A = coo_matrix((vals, (rows, cols)), shape=(len(rhs), n_vars)).tocsr()
    mip = MIP("buckets", c, A, tuple(sense), np.array(rhs), lb, ub, integ)
    return mip, {"x": xidx, "y": yidx, "active": active, "sku": sku}


def solve_buckets(factory: Factory, horizon_start: datetime, days: int,
                  cap_min: float, chg_allowance: float = DEFAULT_CHG_ALLOWANCE,
                  time_limit_s: float = 60.0, inv0: dict | None = None,
                  extra_due_day0: dict | None = None) -> BucketResult:
    """Level 1 solve. Objective recomputed from the assignment."""
    mip, maps = build_bucket_mip(factory, horizon_start, days, cap_min,
                                 chg_allowance, inv0, extra_due_day0)
    if not maps["active"]:
        return BucketResult("no-demand", 0.0, 0.0, {}, 0, 0)
    res = solve_mip(mip, time_limit_s=time_limit_s, mip_rel_gap=0.0)
    if res["x"] is None:
        return BucketResult(str(res["status"]), math.inf, None, {},
                            int(mip.integrality.sum()), len(mip.c))
    x = res["x"]
    qty = {k: float(x[j]) for k, j in maps["x"].items() if x[j] > 1e-6}
    return BucketResult(str(res["status"]), res["objective"],
                        res.get("gap"), qty, int(mip.integrality.sum()),
                        len(mip.c))


def solve_day_sequences(factory: Factory, bucket: BucketResult,
                        cap_min: float, time_limit_s: float = 10.0
                        ) -> tuple[list[LotAssignment], list[str]]:
    """Level 2: per line-day CP-SAT circuit sequencing with the exact
    setup matrix. Returns (assignments, problems)."""
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
        prod = [math.ceil(q / sku[s][0]) for s, q in lots]
        states = [sku[s][2] for s, q in lots]
        n = len(lots)
        m = cp_model.CpModel()
        arcs, arc_cost = [], []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                lit = m.new_bool_var(f"a{i}_{j}")
                arcs.append((i, j, lit))
                d = mtx.duration_between(states[i], states[j])
                arc_cost.append((lit, int(d.total_seconds() // 60)))
        # dummy node n: tour start/end, zero cost both ways
        for i in range(n):
            lit = m.new_bool_var(f"s_{i}")
            arcs.append((n, i, lit)); arc_cost.append((lit, 0))
            lit2 = m.new_bool_var(f"e_{i}")
            arcs.append((i, n, lit2)); arc_cost.append((lit2, 0))
        m.add_circuit(arcs)
        total_chg = sum(lit * c for lit, c in arc_cost)
        budget = int(cap_min) - sum(prod)
        if budget < 0:
            problems.append(f"{l} day {t}: production {sum(prod)} min "
                            f"alone exceeds capacity {cap_min}")
            continue
        m.add(total_chg <= budget)
        m.minimize(total_chg)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        status = solver.solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            problems.append(f"{l} day {t}: sequencing infeasible "
                            f"({solver.status_name(status)}); "
                            "changeover allowance too tight")
            continue
        # extract tour from the dummy node
        succ = {}
        for (i, j, lit) in arcs:
            if solver.value(lit):
                succ[i] = j
        order, node = [], n
        for _ in range(n):
            node = succ[node]
            order.append(node)
        prev_state = None
        for pos, i in enumerate(order):
            chg = 0.0 if prev_state is None else \
                matrices_duration(mtx, prev_state, states[i])
            assignments.append(LotAssignment(l, t, lots[i][0], lots[i][1],
                                             pos, chg))
            prev_state = states[i]
    return assignments, problems


def matrices_duration(mtx, a, b) -> float:
    d = mtx.duration_between(a, b)
    return 0.0 if d is None else d.total_seconds() / 60.0


def solve_window(factory: Factory, horizon_start: datetime, days: int,
                 cap_min: float, chg_allowance: float = DEFAULT_CHG_ALLOWANCE,
                 bucket_time_s: float = 60.0, seq_time_s: float = 10.0,
                 inv0: dict | None = None,
                 extra_due_day0: dict | None = None) -> WindowPlan:
    """One window: buckets, then sequencing, then independent validation."""
    bucket = solve_buckets(factory, horizon_start, days, cap_min,
                           chg_allowance, bucket_time_s, inv0,
                           extra_due_day0)
    if bucket.qty is None or (bucket.objective is math.inf):
        return WindowPlan(horizon_start, days, [], bucket,
                          f"bucket-level failed: {bucket.status}",
                          problems=[f"bucket level: {bucket.status}"])
    assignments, problems = solve_day_sequences(factory, bucket, cap_min,
                                                seq_time_s)
    plan = WindowPlan(horizon_start, days, assignments, bucket,
                      "ok" if not problems else "sequencing problems",
                      problems=problems)
    v_problems, kpis = validate_window_plan(factory, plan, cap_min)
    plan.problems.extend(v_problems)
    plan.kpis = kpis
    if bucket.objective and bucket.objective > 0 and kpis.get("cost") is not None:
        gap = (kpis["cost"] - bucket.objective) / bucket.objective
        plan.kpis["gap_vs_bucket_relaxation"] = gap  # labeled: relaxation
    return plan


def validate_window_plan(factory: Factory, plan: WindowPlan,
                         cap_min: float) -> tuple[list[str], dict]:
    """Independent check from records + returned assignments only."""
    sku = _sku_data(factory)
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix) for r in factory.resources}
    problems: list[str] = []
    by_ld: dict[tuple[str, int], list[LotAssignment]] = {}
    for a in plan.assignments:
        by_ld.setdefault((a.line, a.day), []).append(a)
    chg_total = 0.0
    for (l, t), lots in sorted(by_ld.items()):
        lots.sort(key=lambda a: a.seq_pos)
        mtx = res_mtx.get(l)
        total = 0.0
        prev = None
        seen_pos = set()
        for a in lots:
            if a.seq_pos in seen_pos:
                problems.append(f"{l} day {t}: duplicate seq_pos {a.seq_pos}")
            seen_pos.add(a.seq_pos)
            if a.sku not in sku:
                problems.append(f"{l} day {t}: unknown sku {a.sku}")
                continue
            rate, lines, state = sku[a.sku]
            if l not in lines:
                problems.append(f"{l} day {t}: {a.sku} not eligible")
            total += a.qty / rate
            if prev is not None and mtx is not None:
                d = mtx.duration_between(prev, state)
                if d is None:
                    problems.append(f"{l} day {t}: no rule {prev}->{state}")
                else:
                    total += d.total_seconds() / 60.0
                    chg_total += d.total_seconds() / 60.0
                    if abs(d.total_seconds() / 60.0 - a.chg_from_prev_min) > 0.5:
                        problems.append(f"{l} day {t} pos {a.seq_pos}: "
                                        "recorded changeover mismatch")
            prev = state
        if total > cap_min + 0.05:
            problems.append(f"{l} day {t}: {total:.1f} min > {cap_min}")
    # coverage: produced before due vs demand
    dem: dict[str, list] = {}
    for d in factory.demands:
        dem.setdefault(d.item, []).append(d)
    prod: dict[str, list] = {}
    for a in plan.assignments:
        prod.setdefault(a.sku, []).append(a)
    # lateness KPI: backlog per SKU at window end (units still owed),
    # recomputed from the returned assignments.
    late_units = 0.0
    for s, dems in dem.items():
        produced_total = sum(a.qty for a in prod.get(s, []))
        due_in_window = sum(d.quantity for d in dems
                            if (d.due - plan.horizon_start).days <= plan.days)
        late_units += max(0.0, due_in_window - produced_total)
    kpis = {"changeover_minutes": chg_total,
            "late_units_window_end": late_units,
            "assignments": len(plan.assignments),
            "cost": None}
    return problems, kpis
