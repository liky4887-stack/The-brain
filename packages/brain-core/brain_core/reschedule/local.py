"""Event-triggered local re-solve (Stage 3, slice 1).

A plan in production meets an event - a line goes down, a rush order
lands. Re-solving the whole window overnight is not an answer at
10 AM. The local mechanic:

1. FREEZE everything outside the event's scope (untouched days, and
   untouched lines inside the affected days keep their lots, fixed to
   their line).
2. RE-SOLVE only the affected days with the day-exact model (true
   changeovers, true capacity), displaced lots free to move to any
   eligible line; forward-spill repair (slack-aware) absorbs what the
   day cannot.
3. MEASURE honestly: plan stability (share of production unchanged in
   line and day), wall time, and the same independent validator as
   every other plan - a local re-solve is never taken on faith.

Scope deliberately narrow (the roadmap's riskiest claim, proven
first): single-line machine-down over a day range, and a rush order
added to the book. Widening to multi-line events is a scope change,
not a code change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..records.models import Demand, Factory
from ..rolling.two_level import (LotAssignment, WindowPlan, chunk_lots,
                                 solve_day_exact, validate_window_plan,
                                 _min_incoming_changeover, _sku_data,
                                 due_day, MAX_DAY_REPAIRS)


@dataclass
class LocalResolveResult:
    plan: WindowPlan
    event: str
    wall_s: float
    moved_units: float          # units whose (line, day) changed vs base
    total_units: float
    moved_fraction: float       # by units; "orders moved" gate metric
    displaced_units: float      # units the event itself forced out
    repair_moves: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _group_base(plan: WindowPlan) -> dict[tuple[int, str, str], float]:
    """(day, line, sku) -> qty for the base plan's assignments."""
    out: dict[tuple[int, str, str], float] = {}
    for a in plan.assignments:
        out[(a.day, a.line, a.sku)] = out.get((a.day, a.line, a.sku),
                                              0.0) + a.qty
    return out


def stability(base: WindowPlan, new: WindowPlan) -> tuple[float, float, float]:
    """(moved_units, total_units, moved_fraction) by (line, day) match.

    A unit counts as moved when its SKU's production on its original
    (line, day) shrank - resequencing inside a line-day is not a move.
    """
    b = _group_base(base)
    n = _group_base(new)
    total = sum(b.values())
    moved = 0.0
    for key, q in b.items():
        moved += max(0.0, q - n.get(key, 0.0))
    return moved, total, (moved / total if total else 0.0)


def _resolve_days(factory: Factory, base: WindowPlan,
                  affected_days: range, down_lines: frozenset[str],
                  extra_chunks: dict[int, list[tuple[str, float]]],
                  cap_min: float, seq_time_s: float) -> tuple[
                      list[LotAssignment], list[str], list[str]]:
    """Re-solve the affected days; everything else stays as in base.

    Returns (new assignments for ALL days, problems, repair moves).
    """
    sku = _sku_data(factory)
    min_in = _min_incoming_changeover(factory)
    due_by_sku: dict[str, int] = {}
    for d in factory.demands:
        dd = due_day(d.due, base.horizon_start)
        if d.item in sku:
            due_by_sku[d.item] = max(due_by_sku.get(d.item, -1), dd)

    base_by_day: dict[int, list[LotAssignment]] = {}
    for a in base.assignments:
        base_by_day.setdefault(a.day, []).append(a)

    new_assignments: list[LotAssignment] = []
    problems: list[str] = []
    repair_moves: list[str] = []
    pending: dict[int, list[tuple[str, float]]] = {t: list(c) for t, c in
                                                   extra_chunks.items()}

    for t in sorted(base_by_day):
        if t not in affected_days:
            new_assignments.extend(base_by_day[t])
            continue
        fixed: dict[str, str] = {}
        chunks: list[tuple[str, float]] = []
        grouped = _group_base(base)
        for (day, line, s), q in sorted(grouped.items()):
            if day != t or line in down_lines:
                continue
            name = f"{s}#F@{line}"   # one frozen lot per (sku, line)
            chunks.append((name, q))
            fixed[name] = line
        displaced: dict[str, float] = {}
        for (day, line, s), q in sorted(grouped.items()):
            if day == t and line in down_lines:
                displaced[s] = displaced.get(s, 0.0) + q
        qty = {(s, t): q for s, q in displaced.items()}
        chunks.extend(chunk_lots(sku, qty, cap_min).get(t, []))
        chunks.extend(pending.pop(t, []))
        # chunks with no surviving eligible line (and not frozen) are
        # left unproduced, honestly reported
        solvable = []
        for n, q in chunks:
            s = n.split("#")[0]
            if n in fixed or [l for l in sku[s][1]
                              if l not in down_lines]:
                solvable.append((n, q))
            else:
                problems.append(
                    f"day {t}: {n} has no eligible line after the "
                    "event; left unproduced")
        chunks = solvable
        day_asg: list[LotAssignment] = []
        day_problems: list[str] = []
        lots = list(chunks)
        for attempt in range(MAX_DAY_REPAIRS + 1):
            day_asg, day_problems = solve_day_exact(
                factory, lots, t, cap_min, time_limit_s=seq_time_s,
                fixed=fixed, line_blacklist=down_lines)
            if not day_problems:
                break
            if not any("INFEASIBLE" in p for p in day_problems):
                break
            if attempt == MAX_DAY_REPAIRS:
                break
            movable = [i for i, (n, _) in enumerate(lots)
                       if n not in fixed]
            if not movable:
                break
            def _pressure(i):
                name, q = lots[i]
                s = name.split("#")[0]
                slack = due_by_sku.get(s, t) > t
                return (slack, min_in.get(sku[s][2], 0.0),
                        q / sku[s][0])
            evict_i = max(movable, key=_pressure)
            name, q = lots.pop(evict_i)
            repair_moves.append(
                f"day {t}: {name} ({q:.0f} units) moved to day {t + 1} "
                "during local re-solve")
            if t + 1 < base.days:
                pending.setdefault(t + 1, []).append((name, q))
            else:
                problems.append(
                    f"day {t}: {name} ({q:.0f} units) could not be "
                    "produced inside the horizon")
        new_assignments.extend(day_asg)
        problems.extend(day_problems)
    return new_assignments, problems, repair_moves


def machine_down(factory: Factory, base: WindowPlan, line: str,
                 from_day: int, to_day: int, cap_min: float,
                 seq_time_s: float = 10.0) -> LocalResolveResult:
    """Line `line` is down for days [from_day, to_day). Re-solve those
    days with the line removed; everything else frozen."""
    t0 = time.time()
    affected = range(from_day, to_day)
    displaced_units = sum(a.qty for a in base.assignments
                          if a.line == line and a.day in affected)
    assignments, problems, moves = _resolve_days(
        factory, base, affected, frozenset({line}), {}, cap_min,
        seq_time_s)
    plan = WindowPlan(base.horizon_start, base.days, assignments,
                      base.bucket,
                      "ok" if not problems else "local re-solve problems",
                      problems=list(problems))
    v_problems, kpis = validate_window_plan(factory, plan, cap_min)
    plan.problems.extend(v_problems)
    plan.kpis = kpis
    moved, total, frac = stability(base, plan)
    return LocalResolveResult(plan, f"machine-down {line} days "
                              f"[{from_day},{to_day})",
                              time.time() - t0, moved, total, frac,
                              displaced_units, moves,
                              list(plan.problems))


def rush_order(factory: Factory, base: WindowPlan, order: Demand,
               cap_min: float, seq_time_s: float = 10.0) -> LocalResolveResult:
    """A rush order lands; produce it on its due day (or earlier if it
    cannot fit), re-solving only the days it touches."""
    t0 = time.time()
    day = due_day(order.due, base.horizon_start)
    sku = _sku_data(factory)
    if order.item not in sku:
        raise ValueError(f"rush order item {order.item!r} has no "
                         "operation in the records")
    if not (0 <= day < base.days):
        raise ValueError(f"rush order due outside the plan horizon "
                         f"(day {day})")
    chunks = chunk_lots(sku, {(order.item, day): order.quantity},
                        cap_min).get(day, [])
    affected = range(day, day + 1)
    assignments, problems, moves = _resolve_days(
        factory, base, affected, frozenset(), {day: chunks}, cap_min,
        seq_time_s)
    plan = WindowPlan(base.horizon_start, base.days, assignments,
                      base.bucket,
                      "ok" if not problems else "local re-solve problems",
                      problems=list(problems))
    # the rush order is demand too: validate against the enlarged book
    factory_plus = factory.model_copy()
    factory_plus.demands = list(factory.demands) + [order]
    v_problems, kpis = validate_window_plan(factory_plus, plan, cap_min)
    plan.problems.extend(v_problems)
    plan.kpis = kpis
    moved, total, frac = stability(base, plan)
    return LocalResolveResult(plan, f"rush-order {order.name} "
                              f"({order.item} x{order.quantity:.0f}, "
                              f"due day {day})",
                              time.time() - t0, moved, total, frac,
                              order.quantity, moves,
                              list(plan.problems))
