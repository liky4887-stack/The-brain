"""Back-test harness (Stage 2, slice 5).

Compares the optimizer against a documented naive-planner baseline on
a series of synthetic weekly instances: changeover minutes and late
units, both recomputed by the SAME independent validator, so the
comparison is apples to apples.

The baseline is a heuristic, not a claim about any real plant's
behavior: earliest-due-date first, whole-lot on the first eligible
line that fits (production + the true matrix changeover against the
line-day's current last state), no changeover-aware reordering. That
is the honest reading of "how a planner sequences by hand": due date
drives everything, changeovers are accepted as they come.

Honesty rules honored:
- Both plans go through validate_window_plan; numbers are recomputed
  from records + returned assignments, never from solver output.
- The baseline is documented in code and in docs; "beats" is decided
  on validated metrics only (gate: fewer changeover minutes or fewer
  late units, and worse on neither).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..records.models import Factory
from ..rolling.two_level import (LotAssignment, WindowPlan, due_day,
                                 solve_window, validate_window_plan)
from ..synthetic import FnbParams, generate_fnb_factory


def _sku_data(factory: Factory) -> dict:
    """sku -> (rate_per_min, eligible lines, setup state, onhand)."""
    out = {}
    for o in factory.operations:
        if o.item and o.loads:
            per = o.duration_per.total_seconds()
            if per > 0:
                out[o.item] = (60.0 / per,
                               [l.resource for l in o.loads],
                               o.loads[0].setup)
    onhand: dict[str, float] = {}
    for b in factory.buffers:
        onhand[b.item] = onhand.get(b.item, 0.0) + b.onhand
    return out, onhand


def naive_plan(factory: Factory, horizon_start: datetime, days: int,
               cap_min: float) -> WindowPlan:
    """The documented hand-planning baseline (see module docstring)."""
    sku, onhand = _sku_data(factory)
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix) for r in factory.resources}
    need: dict[str, float] = {}
    edd: dict[str, int] = {}
    for d in factory.demands:
        day = due_day(d.due, horizon_start)
        if 0 <= day < days and d.item in sku:
            need[d.item] = need.get(d.item, 0.0) + d.quantity
            edd[d.item] = min(edd.get(d.item, days - 1), day)
    for s in list(need):
        need[s] = max(0.0, need[s] - onhand.get(s, 0.0))
        if need[s] <= 0:
            del need[s]
            del edd[s]
    # line-day state: remaining minutes, last setup state, next seq pos
    rem = {(l, t): cap_min for t in range(days)
           for l in {r.name for r in factory.resources}}
    last_state: dict[tuple[str, int], str | None] = {}
    pos: dict[tuple[str, int], int] = {}
    assignments: list[LotAssignment] = []

    def chg(line, day, state):
        prev = last_state.get((line, day))
        if prev is None:
            return 0.0
        mtx = res_mtx.get(line)
        d = mtx.duration_between(prev, state) if mtx else None
        return d.total_seconds() / 60.0 if d else 0.0

    def place(s: str, qty: float, t: int, line: str) -> None:
        rate, _, state = sku[s]
        c = chg(line, t, state)
        pmin = qty / rate
        key = (line, t)
        assignments.append(LotAssignment(line, t, s, qty,
                                         pos.get(key, 0), c))
        pos[key] = pos.get(key, 0) + 1
        rem[key] -= pmin + c
        last_state[key] = state

    def fits(s: str, qty: float, t: int, line: str) -> bool:
        rate, _, state = sku[s]
        return qty / rate + chg(line, t, state) <= rem[(line, t)] + 1e-9

    for s in sorted(need, key=lambda s: (edd[s], s)):
        rate, lines, _ = sku[s]
        qty = need[s]
        # 1) whole lot on its due day, first eligible line that fits
        placed = False
        for line in lines:
            if fits(s, qty, edd[s], line):
                place(s, qty, edd[s], line)
                placed = True
                break
        if placed:
            continue
        # 2) walk backward from the day before due (build ahead)
        for t in range(edd[s] - 1, -1, -1):
            done = False
            for line in lines:
                if fits(s, qty, t, line):
                    place(s, qty, t, line)
                    done = True
                    break
            if done:
                placed = True
                break
        if placed:
            continue
        # 3) split: fill the due day, spill the rest forward (late)
        left = qty
        for t in range(edd[s], days):
            if left <= 1e-9:
                break
            for line in lines:
                rate, _, state = sku[s]
                room = rem[(line, t)] - chg(line, t, state)
                take = min(left, max(0.0, room * rate))
                if take > 1e-9:
                    place(s, take, t, line)
                    left -= take
        # whatever remains unplaced is simply not produced: the
        # validator's stock walk counts it as late, honestly.

    plan = WindowPlan(horizon_start, days, assignments, None,
                      "naive-edd-first-fit")
    return plan


@dataclass
class WeekResult:
    week: int
    seed: int
    optimizer_changeover_min: float
    naive_changeover_min: float
    optimizer_late_units: float
    naive_late_units: float
    optimizer_problems: list[str] = field(default_factory=list)
    naive_problems: list[str] = field(default_factory=list)


@dataclass
class BacktestResult:
    weeks: list[WeekResult]
    total_optimizer_changeover_min: float
    total_naive_changeover_min: float
    total_optimizer_late_units: float
    total_naive_late_units: float
    beats_baseline: bool
    all_optimizer_plans_valid: bool


def run_backtest(weeks: int, cap_min: float,
                 params: FnbParams = FnbParams(),
                 bucket_time_s: float = 60.0,
                 seq_time_s: float = 10.0,
                 week0_seed: int = 1000) -> BacktestResult:
    """`weeks` independent weekly instances, optimizer vs naive.

    Each week is a fresh plant (its own seed): the back-test asks "on
    a typical week, does the optimizer beat the hand plan", not a
    rolling simulation (solve_rolling already covers that).

    Seeds stride by 7919: the generator retries failed campaign
    constructions on seed+attempt, so consecutive seeds can collapse
    onto the same surviving plant (observed: seeds 1005-1007 produced
    one identical instance). A prime stride larger than the retry
    budget (20) keeps the 12 instances distinct.
    """
    results: list[WeekResult] = []
    for w in range(weeks):
        seed = week0_seed + w * 7919
        p = generate_fnb_factory(FnbParams(
            **{**params.__dict__, "seed": seed}))
        hs = p.params.horizon_start
        opt = solve_window(p.factory, hs, p.params.days,
                           p.day_capacity_minutes,
                           bucket_time_s=bucket_time_s,
                           seq_time_s=seq_time_s)
        naive = naive_plan(p.factory, hs, p.params.days,
                           p.day_capacity_minutes)
        opt_probs, opt_kpis = validate_window_plan(
            p.factory, opt, p.day_capacity_minutes)
        naive_probs, naive_kpis = validate_window_plan(
            p.factory, naive, p.day_capacity_minutes)
        results.append(WeekResult(
            week=w, seed=seed,
            optimizer_changeover_min=opt_kpis["changeover_minutes"],
            naive_changeover_min=naive_kpis["changeover_minutes"],
            optimizer_late_units=opt_kpis["backlog_units_end"],
            naive_late_units=naive_kpis["backlog_units_end"],
            optimizer_problems=opt_probs + opt.problems,
            naive_problems=naive_probs + naive.problems))
    # MILP quantities are floats; dust below 1e-6 units is zero.
    EPS = 1e-6
    oc = sum(r.optimizer_changeover_min for r in results)
    nc = sum(r.naive_changeover_min for r in results)
    ol = sum(r.optimizer_late_units for r in results)
    nl = sum(r.naive_late_units for r in results)
    beats = ((oc < nc - EPS or ol < nl - EPS)
             and oc <= nc + EPS and ol <= nl + EPS)
    return BacktestResult(
        weeks=results,
        total_optimizer_changeover_min=oc,
        total_naive_changeover_min=nc,
        total_optimizer_late_units=ol,
        total_naive_late_units=nl,
        beats_baseline=beats,
        all_optimizer_plans_valid=not any(r.optimizer_problems
                                          for r in results))
