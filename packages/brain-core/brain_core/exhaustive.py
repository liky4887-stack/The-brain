"""Exhaustive baseline (Stage 4): enumerate every sequence by brute force.

With a tardiness-only objective and no release dates, an optimal schedule
never idles, so enumerating permutations and starting each order as early
as possible covers every candidate plan. Feasibility (hard deadlines) is
checked per sequence; infeasible sequences are skipped.

This is the ground truth for optimality claims, used only in tests with
small N (2! = 2, 6! = 720 - trivially cheap; keep N <= 8).
"""
from __future__ import annotations

from itertools import permutations
from typing import List, Optional, Tuple

from .problem import SchedulingProblem
from .solvers.result import Assignment


def enumerate_best(problem: SchedulingProblem) -> Tuple[Optional[float], List[Assignment]]:
    """Return (best objective, one best assignment) or (None, []) if infeasible."""
    best_obj: Optional[float] = None
    best_plan: List[Assignment] = []
    ids = [o.id for o in problem.orders]
    orders = {o.id: o for o in problem.orders}

    for seq in permutations(ids):
        t = 0
        obj = 0.0
        plan: List[Assignment] = []
        feasible = True
        for oid in seq:
            o = orders[oid]
            start = t
            end = t + o.processing_time
            if o.deadline is not None and end > o.deadline:
                feasible = False
                break
            obj += o.weight * max(0, end - o.due_date)
            plan.append(Assignment(order_id=oid, start=start, end=end))
            t = end
        if feasible and (best_obj is None or obj < best_obj):
            best_obj = obj
            best_plan = plan

    return best_obj, best_plan
