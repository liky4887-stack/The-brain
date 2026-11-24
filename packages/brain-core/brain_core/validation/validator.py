"""Independent plan validator (blueprint Stage 3, step 5; DECISIONS.md #5).

Shares no code with the solver adapter. Given a problem and a plan, it
re-checks every rule from docs/specs/stage0-tiny-problem.md and recomputes
the objective from scratch. It deliberately says NOTHING about optimality -
optimality is proven only by the exhaustive baseline in the test suite
(Stage 4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..problem import SchedulingProblem
from ..solvers.result import Assignment

OBJECTIVE_TOLERANCE = 1e-6


@dataclass
class ValidationReport:
    ok: bool
    errors: List[str] = field(default_factory=list)
    recomputed_objective: Optional[float] = None


def validate_plan(problem: SchedulingProblem, assignments: List[Assignment],
                  reported_objective: Optional[float] = None) -> ValidationReport:
    errors: List[str] = []
    orders = {o.id: o for o in problem.orders}
    seen = set()

    # Rule 1: every order assigned exactly once, no unknown orders.
    for a in assignments:
        if a.order_id not in orders:
            errors.append(f"unknown order in plan: {a.order_id!r}")
            continue
        if a.order_id in seen:
            errors.append(f"order {a.order_id!r} assigned more than once")
        seen.add(a.order_id)
    missing = set(orders) - seen
    if missing:
        errors.append(f"orders missing from plan: {sorted(missing)}")

    # Rules 2-4 per assignment.
    intervals = []
    for a in assignments:
        if a.order_id not in orders:
            continue
        o = orders[a.order_id]
        if a.start < 0:
            errors.append(f"{a.order_id}: negative start {a.start}")
        if a.end != a.start + o.processing_time:
            errors.append(f"{a.order_id}: end {a.end} != start {a.start} + p {o.processing_time}")
        if o.deadline is not None and a.end > o.deadline:
            errors.append(f"{a.order_id}: end {a.end} past deadline {o.deadline}")
        intervals.append((a.start, a.end, a.order_id))

    # Rule: no overlap on the single machine (sort and compare neighbors).
    intervals.sort()
    for (s1, e1, i1), (s2, e2, i2) in zip(intervals, intervals[1:]):
        if s2 < e1:
            errors.append(f"overlap on machine: {i1} [{s1},{e1}) vs {i2} [{s2},{e2})")

    # Objective recomputed from scratch with float weights.
    recomputed = None
    if not errors:
        recomputed = 0.0
        for a in assignments:
            o = orders[a.order_id]
            recomputed += o.weight * max(0, a.end - o.due_date)
        if reported_objective is not None and abs(recomputed - reported_objective) > OBJECTIVE_TOLERANCE:
            errors.append(
                f"reported objective {reported_objective} != recomputed {recomputed}"
            )

    return ValidationReport(ok=not errors, errors=errors, recomputed_objective=recomputed)
