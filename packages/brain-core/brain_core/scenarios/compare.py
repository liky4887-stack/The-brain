"""Objective weight sliders and side-by-side scenarios (Stage 3).

A planner asks "what if I care more about changeovers than about
front-loading?" A scenario is a named ObjectiveWeights; solving the
same book under several weight sets and laying the validated KPIs
side by side is the answer.

Honesty rules honored:
- Every scenario plan goes through the same independent validator.
- Comparison KPIs are computed at the DEFAULT proxy weights
  (validate_window_plan's proxy_cost), not at each scenario's own
  slider settings: scenarios are comparable only on a common scale.
- The energy slider is a documented proxy (see ObjectiveWeights):
  records carry line efficiency, not power draw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..records.models import Factory
from ..rolling.two_level import (ObjectiveWeights, WindowPlan,
                                 solve_window, validate_window_plan)


@dataclass(frozen=True)
class Scenario:
    name: str
    weights: ObjectiveWeights
    note: str = ""


@dataclass
class ScenarioResult:
    scenario: Scenario
    plan: WindowPlan
    kpis: dict
    problems: list[str] = field(default_factory=list)


def solve_scenarios(factory: Factory, horizon_start: datetime,
                    days: int, cap_min: float,
                    scenarios: list[Scenario],
                    bucket_time_s: float = 60.0,
                    seq_time_s: float = 10.0) -> list[ScenarioResult]:
    """Solve each scenario; return results in the order given."""
    out = []
    for sc in scenarios:
        plan = solve_window(factory, horizon_start, days, cap_min,
                            bucket_time_s=bucket_time_s,
                            seq_time_s=seq_time_s, weights=sc.weights)
        v_problems, kpis = validate_window_plan(factory, plan, cap_min)
        plan.problems.extend(v_problems)
        out.append(ScenarioResult(sc, plan, kpis,
                                  list(plan.problems)))
    return out


def compare(results: list[ScenarioResult]) -> dict:
    """Side-by-side KPI table: scenario name -> validated KPIs.

    Deltas are against the first scenario (the base case by
    convention).
    """
    if not results:
        return {"scenarios": {}, "deltas_vs_first": {}}
    table = {}
    for r in results:
        table[r.scenario.name] = {
            "changeover_minutes": r.kpis["changeover_minutes"],
            "setups": r.kpis["setups"],
            "late_units_end": r.kpis["backlog_units_end"],
            "backlog_unit_days": r.kpis["backlog_unit_days"],
            "early_unit_days": r.kpis["early_unit_days"],
            "production_minutes": r.kpis["production_minutes"],
            "energy_proxy": r.kpis["energy_proxy"],
            "proxy_cost": r.kpis["proxy_cost"],
            "problems": len(r.problems),
        }
    base = table[results[0].scenario.name]
    deltas = {}
    for name, kpis in table.items():
        if name == results[0].scenario.name:
            continue
        deltas[name] = {
            k: kpis[k] - base[k] for k in
            ("changeover_minutes", "late_units_end", "energy_proxy",
             "proxy_cost")}
    return {"scenarios": table, "deltas_vs_first": deltas}
