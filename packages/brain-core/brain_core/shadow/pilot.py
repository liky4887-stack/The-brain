"""Four-week shadow pilot (Stage 3, slice 6).

The optimizer runs in shadow mode alongside the naive hand plan on
the same weeks. Every week, BOTH plans are scored by the same
independent validator and BOTH are written to the audit log with a
plan digest and the measured decision latency - the evidence a
planner would need to trust the switch.

Same primitives and seed stride as the back-test harness
(seeds stride by 7919; see harness.run_backtest for why).

Honesty rules honored:
- every number comes from validate_window_plan on the returned plans,
  never from solver output;
- "beats the naive plan" is the same measured EPS rule as the
  back-test: no worse on changeovers AND lateness, strictly better on
  at least one;
- the audit entries record decision_latency_s as measured wall time
  (planned runs have no external event).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..audit import AuditLog
from ..backtest.harness import naive_plan
from ..rolling.two_level import solve_window, validate_window_plan
from ..synthetic import FnbParams, generate_fnb_factory

SEED_STRIDE = 7919   # see backtest.harness.run_backtest
EPS = 1e-6


@dataclass
class ShadowWeek:
    week: int
    seed: int
    optimizer_digest: str
    naive_digest: str
    optimizer_changeover_min: float
    naive_changeover_min: float
    optimizer_late_units: float
    naive_late_units: float
    optimizer_wall_s: float
    optimizer_problems: list[str] = field(default_factory=list)
    naive_problems: list[str] = field(default_factory=list)


@dataclass
class ShadowResult:
    weeks: list[ShadowWeek]
    total_optimizer_changeover_min: float
    total_naive_changeover_min: float
    total_optimizer_late_units: float
    total_naive_late_units: float
    all_plans_valid: bool
    beats_naive: bool
    audit_entries: int


def run_shadow_pilot(weeks: int, cap_min: float,
                     params: FnbParams = FnbParams(),
                     bucket_time_s: float = 60.0,
                     seq_time_s: float = 10.0,
                     week0_seed: int = 1000,
                     audit_path: str | Path | None = None
                     ) -> ShadowResult:
    """`weeks` weekly instances; optimizer and naive scored side by
    side and both recorded in the audit log when audit_path is given.
    """
    log = AuditLog(audit_path) if audit_path else None
    results: list[ShadowWeek] = []
    for w in range(weeks):
        seed = week0_seed + w * SEED_STRIDE
        p = generate_fnb_factory(FnbParams(
            **{**params.__dict__, "seed": seed}))
        hs = p.params.horizon_start
        t0 = time.monotonic()
        opt = solve_window(p.factory, hs, p.params.days,
                           p.day_capacity_minutes,
                           bucket_time_s=bucket_time_s,
                           seq_time_s=seq_time_s)
        opt_wall = time.monotonic() - t0
        naive = naive_plan(p.factory, hs, p.params.days,
                           p.day_capacity_minutes)
        opt_probs, opt_kpis = validate_window_plan(
            p.factory, opt, p.day_capacity_minutes)
        naive_probs, naive_kpis = validate_window_plan(
            p.factory, naive, p.day_capacity_minutes)
        opt_probs = opt_probs + opt.problems
        naive_probs = naive_probs + naive.problems
        opt_d = naive_d = ""
        if log:
            e = log.record_decision(
                "shadow_week", f"week {w} optimizer plan (seed {seed})",
                opt, wall_s=opt_wall,
                kpis={k: opt_kpis[k] for k in
                      ("changeover_minutes", "backlog_units_end",
                       "proxy_cost")},
                problems=len(opt_probs), detail={"week": w,
                                                 "seed": seed,
                                                 "side": "optimizer"})
            opt_d = e["digest"]
            e = log.record_decision(
                "shadow_week", f"week {w} naive plan (seed {seed})",
                naive, wall_s=0.0,
                kpis={k: naive_kpis[k] for k in
                      ("changeover_minutes", "backlog_units_end",
                       "proxy_cost")},
                problems=len(naive_probs), detail={"week": w,
                                                   "seed": seed,
                                                   "side": "naive"})
            naive_d = e["digest"]
        results.append(ShadowWeek(
            week=w, seed=seed,
            optimizer_digest=opt_d, naive_digest=naive_d,
            optimizer_changeover_min=opt_kpis["changeover_minutes"],
            naive_changeover_min=naive_kpis["changeover_minutes"],
            optimizer_late_units=opt_kpis["backlog_units_end"],
            naive_late_units=naive_kpis["backlog_units_end"],
            optimizer_wall_s=opt_wall,
            optimizer_problems=opt_probs,
            naive_problems=naive_probs))
    oc = sum(r.optimizer_changeover_min for r in results)
    nc = sum(r.naive_changeover_min for r in results)
    ol = sum(r.optimizer_late_units for r in results)
    nl = sum(r.naive_late_units for r in results)
    beats = ((oc < nc - EPS or ol < nl - EPS)
             and oc <= nc + EPS and ol <= nl + EPS)
    return ShadowResult(
        weeks=results,
        total_optimizer_changeover_min=oc,
        total_naive_changeover_min=nc,
        total_optimizer_late_units=ol,
        total_naive_late_units=nl,
        all_plans_valid=all(not r.optimizer_problems
                            and not r.naive_problems for r in results),
        beats_naive=beats,
        audit_entries=len(log.entries()) if log else 0)
