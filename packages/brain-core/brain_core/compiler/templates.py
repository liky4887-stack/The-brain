"""The compiler: canonical records -> solver-native problems (Stage 1).

Two templates, exactly as ROADMAP Stage 1 requires:

- compile_lotsizing: a single-item view of the factory over discrete
  periods becomes the Wagner-Whitin ULS from Wolsey (solved exactly by
  the DP in lotsizing/uls.py — no black-box solver).
- compile_jobshop: demands become jobs whose routes follow the
  in-factory BOM chain; the instance feeds the disjunctive job-shop
  core (jobshop/disjunctive.py, Pinedo ch.5.3) and CP-SAT.

Honesty rules: compilation never claims feasibility or optimality;
every number in the compiled problem traces to a record field, and the
mapping back to record names is returned so plans can be explained.
Float->int scaling happens HERE (the compiler boundary), in minutes
for durations, never inside solvers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ..jobshop.disjunctive import JobShopInstance
from ..lotsizing.uls import ULSPlan, solve_uls
from ..records.models import Factory, Operation


@dataclass(frozen=True)
class LotSizingCompilation:
    item: str
    operation: Optional[str]  # producing operation, None = purchased
    period_starts: tuple
    demands: tuple          # per-period bucketed demand (floats)
    plan: ULSPlan
    total_cost: float       # recomputed from the plan in original costs
    production_orders: tuple  # (period_start, quantity, operation_name)


def _bucket_demands(factory: Factory, item: str,
                    period_starts: list[datetime],
                    period: timedelta) -> tuple[list[float], list[str]]:
    """Sum demand quantities into periods by due date. Demands due
    outside the horizon are listed as problems, not silently dropped."""
    n = len(period_starts)
    d = [0.0] * n
    problems = []
    for dem in factory.demands:
        if dem.item != item:
            continue
        idx = int((dem.due - period_starts[0]) // period)
        if dem.due < period_starts[0] or idx >= n:
            problems.append(f"demand {dem.name}: due {dem.due} outside horizon")
            continue
        d[idx] += dem.quantity
    return d, problems


def compile_lotsizing(factory: Factory, item: str,
                      period_starts: list[datetime], period: timedelta,
                      setup_cost: float, holding_cost: float,
                      unit_cost: Optional[float] = None) -> LotSizingCompilation:
    """Single-item lot sizing over a discrete horizon (ULS template).

    unit_cost defaults to the producing operation's cost; an item with
    no in-factory producer compiles to all-zero production (purchased),
    which the DP treats as demands satisfiable only from stock — the
    caller sees that as a positive-cost-only-if-stock exists plan and
    must treat uncovered demand as a purchasing decision, honestly.
    """
    if not period_starts:
        raise ValueError("at least one period")
    if period <= timedelta(0):
        raise ValueError("period length must be > 0")
    if setup_cost < 0 or holding_cost < 0:
        raise ValueError("costs must be >= 0")
    producers = factory.producing_operations(item)
    op: Optional[Operation] = producers[0] if producers else None
    if len(producers) > 1:
        raise ValueError(
            f"item {item}: {len(producers)} producers, ULS template is single-source")
    p_unit = unit_cost if unit_cost is not None else (op.cost if op else 0.0)
    d, problems = _bucket_demands(factory, item, period_starts, period)
    if problems:
        raise ValueError("; ".join(problems))
    onhand = sum(b.onhand for b in factory.buffers
                 if b.item == item and (op is None or b.location == op.location
                                        or op.location is None))
    # first-period stock covers demand for free; model by reducing d
    if onhand > 0:
        covered = 0.0
        for t in range(len(d)):
            take = min(d[t], onhand - covered)
            d[t] -= take
            covered += take
    n = len(d)
    plan = solve_uls(d, [p_unit] * n, [holding_cost] * n, [setup_cost] * n)
    total = plan_cost(plan, d, p_unit, holding_cost, setup_cost)
    orders = tuple((period_starts[t], plan.production[t], op.name if op else "")
                   for t in range(n) if plan.production[t] > 0)
    return LotSizingCompilation(item, op.name if op else None,
                                tuple(period_starts), tuple(d), plan,
                                total, orders)


def plan_cost(plan: ULSPlan, d: list[float], p: float, h: float, f: float) -> float:
    """Cost recomputed from the returned plan (never from DP internals)."""
    n = len(d)
    stock = 0.0
    total = 0.0
    for t in range(n):
        stock += plan.production[t] - d[t]
        total += p * plan.production[t] + h * stock + f * plan.setups[t]
    return total


def _minutes(td: timedelta) -> int:
    return math.ceil(td.total_seconds() / 60)


@dataclass(frozen=True)
class JobShopCompilation:
    instance: JobShopInstance
    job_names: tuple        # job index -> demand name
    step_sources: tuple     # job index -> tuple of operation names in route


def _route_for(factory: Factory, item: str, quantity: float,
               seen: frozenset) -> list[tuple[str, int, str]]:
    """(resource, minutes, operation_name) steps, upstream first."""
    if item in seen:
        raise ValueError(f"BOM cycle at item {item}")
    producers = factory.producing_operations(item)
    if not producers:
        return []  # purchased: no in-factory work
    if len(producers) > 1:
        raise ValueError(f"item {item}: {len(producers)} producers, "
                         "job-shop template needs one")
    op = producers[0]
    steps: list[tuple[str, int, str]] = []
    for m in op.materials:
        if m.quantity < 0:
            steps.extend(_route_for(factory, m.item, -m.quantity * quantity,
                                    seen | {item}))
    if not op.loads:
        raise ValueError(f"operation {op.name}: no resource load")
    minutes = _minutes(op.duration + op.duration_per * quantity)
    if minutes <= 0:
        raise ValueError(f"operation {op.name}: zero processing time")
    steps.append((op.loads[0].resource, minutes, op.name))
    return steps


def compile_jobshop(factory: Factory) -> JobShopCompilation:
    """Demands -> jobs on machines, routes following the BOM chain."""
    routes, names, sources = [], [], []
    for dem in factory.demands:
        steps = _route_for(factory, dem.item, dem.quantity, frozenset())
        if not steps:
            continue  # fully purchased item: no job to schedule
        routes.append(tuple((res, mins) for res, mins, _ in steps))
        names.append(dem.name)
        sources.append(tuple(op for _, _, op in steps))
    if not routes:
        raise ValueError("no in-factory work to schedule")
    return JobShopCompilation(JobShopInstance(tuple(routes)),
                              tuple(names), tuple(sources))
