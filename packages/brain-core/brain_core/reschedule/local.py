"""Event-triggered local re-solve (Stage 3, slice 1).

A plan in production meets an event - a line goes down, a rush order
lands. Re-solving the whole window overnight is not an answer at
10 AM. The local mechanic:

1. FREEZE everything outside the event's scope.
2. RE-SOLVE the event days with the downed line removed (healthy-line
   lots fixed to their lines; displaced lots free).
3. Overflow moves to ABSORBER days before the event (build-ahead,
   lots unfixed there) when the event is known early enough, then
   rolls FORWARD day by day (each receiving day is re-solved with its
   lots fixed plus the overflow free). Anything left over is reported
   unproduced - the validator counts it late; nothing vanishes.
4. MEASURE honestly: stability (units unchanged in line and day),
   wall time, and the same independent validator as every plan.

Scope deliberately narrow (the roadmap's riskiest claim, proven
first): single-line machine-down over a day range, and a rush order
added to the book.
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


class _DayResolver:
    """Solves individual days with repair eviction into a pool."""

    def __init__(self, factory: Factory, base: WindowPlan,
                 cap_min: float, seq_time_s: float):
        self.factory = factory
        self.base = base
        self.cap_min = cap_min
        self.seq_time_s = seq_time_s
        self.sku = _sku_data(factory)
        self.min_in = _min_incoming_changeover(factory)
        self.due_by_sku: dict[str, int] = {}
        for d in factory.demands:
            dd = due_day(d.due, base.horizon_start)
            if d.item in self.sku:
                self.due_by_sku[d.item] = max(
                    self.due_by_sku.get(d.item, -1), dd)
        self.grouped = _group_base(base)
        self.problems: list[str] = []
        self.repair_moves: list[str] = []

    def frozen_chunks(self, t: int,
                      down_lines: frozenset[str]) -> tuple[list, dict]:
        """The day's base lots as fixed chunks (healthy lines only)."""
        chunks, fixed = [], {}
        for (day, line, s), q in sorted(self.grouped.items()):
            if day != t or line in down_lines:
                continue
            name = f"{s}#F@{line}"   # one frozen lot per (sku, line)
            chunks.append((name, q))
            fixed[name] = line
        return chunks, fixed

    def free_chunks(self, t: int,
                    down_lines: frozenset[str]) -> list[tuple[str, float]]:
        """The day's base lots on the given lines, re-chunked, free."""
        displaced: dict[str, float] = {}
        for (day, line, s), q in sorted(self.grouped.items()):
            if day == t and line in down_lines:
                displaced[s] = displaced.get(s, 0.0) + q
        if not displaced:
            return []
        qty = {(s, t): q for s, q in displaced.items()}
        return chunk_lots(self.sku, qty, self.cap_min).get(t, [])

    def all_free_chunks(self, t: int) -> list[tuple[str, float]]:
        """Every base lot of the day, re-chunked, unfixed (absorbers)."""
        by_sku: dict[str, float] = {}
        for (day, _, s), q in self.grouped.items():
            if day == t:
                by_sku[s] = by_sku.get(s, 0.0) + q
        if not by_sku:
            return []
        qty = {(s, t): q for s, q in by_sku.items()}
        return chunk_lots(self.sku, qty, self.cap_min).get(t, [])

    def solve(self, t: int, chunks: list[tuple[str, float]],
              fixed: dict, blacklist: frozenset[str],
              pool: list[tuple[str, float]]) -> list[LotAssignment]:
        """Solve one day; overflow evicted into `pool` (slack-aware)."""
        lots = list(chunks)
        # drop chunks with no surviving eligible line (and not fixed)
        solvable = []
        for n, q in lots:
            s = n.split("#")[0]
            if n in fixed or [l for l in self.sku[s][1]
                              if l not in blacklist]:
                solvable.append((n, q))
            else:
                self.problems.append(
                    f"day {t}: {n} has no eligible line after the "
                    "event; left unproduced")
        lots = solvable
        for attempt in range(MAX_DAY_REPAIRS + 1):
            asg, probs = solve_day_exact(
                self.factory, lots, t, self.cap_min,
                time_limit_s=self.seq_time_s, fixed=fixed,
                line_blacklist=blacklist)
            if not probs:
                return asg
            if not any("INFEASIBLE" in p for p in probs):
                self.problems.extend(probs)
                return asg
            if attempt == MAX_DAY_REPAIRS:
                self.problems.extend(probs)
                return asg
            movable = [i for i, (n, _) in enumerate(lots)
                       if n not in fixed]
            if not movable:
                self.problems.extend(probs)
                return asg

            def _pressure(i):
                name, q = lots[i]
                s = name.split("#")[0]
                slack = self.due_by_sku.get(s, t) > t
                return (slack, self.min_in.get(self.sku[s][2], 0.0),
                        q / self.sku[s][0])
            evict_i = max(movable, key=_pressure)
            name, q = lots.pop(evict_i)
            pool.append((name, q))
            self.repair_moves.append(
                f"day {t}: {name} ({q:.0f} units) overflowed to the "
                "reassignment pool")
        return asg  # unreachable; keeps the type honest


def _resolve_days(factory: Factory, base: WindowPlan,
                  event_days: range, down_lines: frozenset[str],
                  extra_chunks: dict[int, list[tuple[str, float]]],
                  cap_min: float, seq_time_s: float,
                  absorber_days: tuple[int, ...] = ()) -> tuple[
                      list[LotAssignment], list[str], list[str]]:
    """Event days -> absorbers -> forward activation; pool never lost."""
    r = _DayResolver(factory, base, cap_min, seq_time_s)
    new_by_day: dict[int, list[LotAssignment]] = {}
    pool: list[tuple[str, float]] = []

    # 1) event days: healthy lots fixed, down-line lots free
    for t in event_days:
        chunks, fixed = r.frozen_chunks(t, down_lines)
        chunks = chunks + r.free_chunks(t, down_lines) + \
            list(extra_chunks.get(t, []))
        new_by_day[t] = r.solve(t, chunks, fixed, down_lines, pool)

    # 2) absorber days (build-ahead): their lots stay fixed to their
    #    lines; the pool arrives free (minimal movement, max room)
    for t in sorted(absorber_days):
        chunks, fixed = r.frozen_chunks(t, frozenset())
        take, pool = pool, []
        new_by_day[t] = r.solve(t, chunks + take, fixed, frozenset(),
                                pool)

    # 3) forward activation: each day the pool rolls into is re-solved
    #    with its base lots fixed plus the pool free
    t = max(event_days.stop - 1, max(absorber_days, default=-1)) + 1
    while pool and t < base.days:
        chunks, fixed = r.frozen_chunks(t, frozenset())
        take, pool = pool, []
        new_by_day[t] = r.solve(t, chunks + take, fixed, frozenset(),
                                pool)
        t += 1
    for name, q in pool:
        r.problems.append(
            f"{name} ({q:.0f} units) could not be produced inside the "
            "horizon after the event")

    # 4) untouched days pass through unchanged
    assignments: list[LotAssignment] = []
    for a in base.assignments:
        if a.day not in new_by_day:
            assignments.append(a)
    for day_asg in new_by_day.values():
        assignments.extend(day_asg)
    return assignments, r.problems, r.repair_moves


def machine_down(factory: Factory, base: WindowPlan, line: str,
                 from_day: int, to_day: int, cap_min: float,
                 seq_time_s: float = 10.0,
                 absorb_back: int = 0) -> LocalResolveResult:
    """Line `line` is down for days [from_day, to_day).

    absorb_back: also re-solve that many days BEFORE from_day with
    their lots unfixed - they can build ahead of the outage. Use it
    when the event is known before those days run; days already
    produced must stay frozen (absorb_back=0).
    """
    t0 = time.time()
    absorbers = tuple(range(max(0, from_day - absorb_back), from_day))
    displaced_units = sum(a.qty for a in base.assignments
                          if a.line == line
                          and from_day <= a.day < to_day)
    assignments, problems, moves = _resolve_days(
        factory, base, range(from_day, to_day), frozenset({line}), {},
        cap_min, seq_time_s, absorber_days=absorbers)
    plan = WindowPlan(base.horizon_start, base.days, assignments,
                      base.bucket,
                      "ok" if not problems else "local re-solve problems",
                      problems=list(problems))
    v_problems, kpis = validate_window_plan(factory, plan, cap_min)
    plan.problems.extend(v_problems)
    kpis["repair_moves"] = moves
    plan.kpis = kpis
    moved, total, frac = stability(base, plan)
    return LocalResolveResult(plan, f"machine-down {line} days "
                              f"[{from_day},{to_day})",
                              time.time() - t0, moved, total, frac,
                              displaced_units, moves,
                              list(plan.problems))


def rush_order(factory: Factory, base: WindowPlan, order: Demand,
               cap_min: float, seq_time_s: float = 10.0) -> LocalResolveResult:
    """A rush order lands; produce it on its due day, re-solving only
    the days it touches (overflow rolls forward with activation)."""
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
    assignments, problems, moves = _resolve_days(
        factory, base, range(day, day + 1), frozenset(), {day: chunks},
        cap_min, seq_time_s)
    plan = WindowPlan(base.horizon_start, base.days, assignments,
                      base.bucket,
                      "ok" if not problems else "local re-solve problems",
                      problems=list(problems))
    # the rush order is demand too: validate against the enlarged book
    factory_plus = factory.model_copy()
    factory_plus.demands = list(factory.demands) + [order]
    v_problems, kpis = validate_window_plan(factory_plus, plan, cap_min)
    plan.problems.extend(v_problems)
    kpis["repair_moves"] = moves
    plan.kpis = kpis
    moved, total, frac = stability(base, plan)
    return LocalResolveResult(plan, f"rush-order {order.name} "
                              f"({order.item} x{order.quantity:.0f}, "
                              f"due day {day})",
                              time.time() - t0, moved, total, frac,
                              order.quantity, moves,
                              list(plan.problems))
