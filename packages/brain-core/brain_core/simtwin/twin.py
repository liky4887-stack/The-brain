"""Simulation twin + per-plan robustness score (Stage 4, slice 3).

A plan is executed as-is against sampled disruptions - line-days
down, demand jitter, line slowdowns - WITHOUT re-optimization: what
breaks if the world does not match the plan. Execution uses the same
daily stock walk as the independent validator, so "late units" in the
twin means exactly what it means in validation.

Honesty rules honored:
- every score is measured by executing the plan through the walk,
  never asserted from plan properties;
- the sampling seed and parameters are recorded with the score;
  results are reproducible, not calibrated probabilities;
- the nominal (no-disruption) execution is always included, so a plan
  that is only good on paper shows it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..records.models import Factory
from ..rolling.two_level import WindowPlan, _daily_walk


@dataclass(frozen=True)
class Disruption:
    """One scenario: line-days fully down, per-SKU demand multiplier,
    per-line rate multiplier (a slower line produces less of its
    planned quantity)."""
    down: tuple = ()                    # ((line, day), ...)
    demand_scale: tuple = ()            # ((sku, factor), ...)
    rate_scale: tuple = ()              # ((line, factor), ...)


def sample_scenarios(factory: Factory, days: int, n: int, seed: int = 0,
                     p_down_day: float = 0.02,
                     demand_jitter: float = 0.10,
                     rate_slowdown: float = 0.05
                     ) -> list[Disruption]:
    """n i.i.d. scenarios. A scenario contains the nominal plan's
    world plus independent Bernoulli line-day outages, uniform demand
    jitter in [1-j, 1+j], and an optional uniform rate slowdown
    probability per line (5% slower when it fires)."""
    rng = random.Random(seed)
    lines = [r.name for r in factory.resources]
    skus = sorted({d.item for d in factory.demands})
    out = []
    for _ in range(n):
        down = tuple(sorted(
            (l, t) for l in lines for t in range(days)
            if rng.random() < p_down_day))
        dscale = tuple((s, 1.0 + rng.uniform(-demand_jitter,
                                             demand_jitter))
                       for s in skus)
        rscale = tuple((l, 1.0 - rate_slowdown)
                       for l in lines if rng.random() < 0.3)
        out.append(Disruption(down=down, demand_scale=dscale,
                              rate_scale=rscale))
    return out


def execute(factory: Factory, plan: WindowPlan,
            disruption: Disruption, inv0: dict | None = None) -> dict:
    """Execute the plan as-is under one disruption; return the same
    metrics the validator's walk produces."""
    down = set(disruption.down)
    rate = dict(disruption.rate_scale)
    kept = []
    for a in plan.assignments:
        if (a.line, a.day) in down:
            continue                       # that production is lost
        f = rate.get(a.line, 1.0)
        if f != 1.0:
            a = type(a)(line=a.line, day=a.day, sku=a.sku,
                        qty=a.qty * f, seq_pos=a.seq_pos,
                        chg_from_prev_min=a.chg_from_prev_min)
        kept.append(a)
    dscale = dict(disruption.demand_scale)
    if dscale:
        factory = factory.model_copy(update={
            "demands": [d.model_copy(update={
                "quantity": d.quantity * dscale.get(d.item, 1.0)})
                for d in factory.demands]})
    return _daily_walk(factory, plan.horizon_start, plan.days, kept,
                       inv0)


def robustness_score(factory: Factory, plan: WindowPlan,
                     n_scenarios: int = 20, seed: int = 0,
                     inv0: dict | None = None,
                     **sampling) -> dict:
    """Measured robustness: nominal execution + sampled disruptions.

    Returns the recorded parameters, the nominal metrics, and
    mean/max/p95-ish (95th percentile by rank) of backlog_units_end
    and backlog_unit_days over the scenarios.
    """
    nominal = execute(factory, plan, Disruption(), inv0)
    scens = sample_scenarios(factory, plan.days, n_scenarios, seed,
                             **sampling)
    late = sorted(execute(factory, plan, s, inv0)["backlog_units_end"]
                  for s in scens)
    udays = sorted(execute(factory, plan, s, inv0)["backlog_unit_days"]
                   for s in scens)

    def p95(xs):
        return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else 0.0

    return {
        "n_scenarios": n_scenarios, "seed": seed,
        "sampling": {"p_down_day": sampling.get("p_down_day", 0.02),
                     "demand_jitter": sampling.get("demand_jitter", 0.10),
                     "rate_slowdown": sampling.get("rate_slowdown", 0.05)},
        "nominal": nominal,
        "late_units": {"mean": sum(late) / len(late) if late else 0.0,
                       "p95": p95(late),
                       "max": late[-1] if late else 0.0},
        "backlog_unit_days": {
            "mean": sum(udays) / len(udays) if udays else 0.0,
            "p95": p95(udays),
            "max": udays[-1] if udays else 0.0},
    }
