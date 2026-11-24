"""CP-SAT adapter: the first solver path (blueprint Stage 3, step 2).

Formulation per the OR-Tools CP-SAT scheduling documentation and the CP-SAT
Primer (Krupke, public):
- one interval variable per order, AddNoOverlap for the single machine
- tardiness linearized exactly: T_i >= end_i - due_i, T_i >= 0
- CP-SAT accepts INTEGER coefficients only, so float weights are scaled by
  WEIGHT_SCALE and rounded; the scale is recorded in diagnostics and the
  reported objective is divided back exactly.
- hard deadlines become end_i <= deadline bounds

Honesty rules:
- statuses map 1:1 from the solver; FEASIBLE (unproven) is never upgraded
  to OPTIMAL; time limits that found nothing return TIME_LIMIT, not a plan.
- the returned objective is the true weighted tardiness recomputed from the
  assignment (not the scaled internal value), so callers never see solver
  artifacts.
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from ..problem import SchedulingProblem
from .result import Assignment, SolveResult, SolveStatus

WEIGHT_SCALE = 1000  # weights rounded to 3 decimals; documented in model spec


def solve_cpsat(problem: SchedulingProblem, time_limit_s: float = 10.0) -> SolveResult:
    model = cp_model.CpModel()
    horizon = max(problem.horizon, 1)

    intervals = {}
    start_vars = {}
    tardiness_terms = []
    for order in problem.orders:
        start = model.new_int_var(0, horizon, f"start_{order.id}")
        end = model.new_int_var(0, horizon, f"end_{order.id}")
        interval = model.new_interval_var(start, order.processing_time, end, f"iv_{order.id}")
        intervals[order.id] = interval
        start_vars[order.id] = start  # keep our own var; IntervalVar accessors differ across ortools versions
        if order.deadline is not None:
            model.add(end <= order.deadline)
        tardy = model.new_int_var(0, horizon, f"tardy_{order.id}")
        model.add(tardy >= end - order.due_date)
        scaled_weight = round(order.weight * WEIGHT_SCALE)
        tardiness_terms.append(scaled_weight * tardy)

    model.add_no_overlap(intervals.values())
    model.minimize(sum(tardiness_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status_code = solver.solve(model)

    diagnostics = {
        "solver": "cp-sat",
        "weight_scale": WEIGHT_SCALE,
        "wall_time_s": round(solver.wall_time, 3),
        "branches": solver.num_branches,
        "conflicts": solver.num_conflicts,
    }
    solve_time_ms = int(round(solver.wall_time * 1000))

    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignments = []
        for order in problem.orders:
            s = solver.value(start_vars[order.id])
            assignments.append(Assignment(order_id=order.id, start=s, end=s + order.processing_time))
        assignments.sort(key=lambda a: a.start)
        # Recompute the true objective from the assignment, not the scaled
        # internal expression, so callers get exact weighted tardiness.
        objective = 0.0
        for order, a in zip(problem.orders, _by_order(problem, assignments)):
            objective += order.weight * max(0, a.end - order.due_date)
        status = SolveStatus.OPTIMAL if status_code == cp_model.OPTIMAL else SolveStatus.FEASIBLE
        warnings = [] if status == SolveStatus.OPTIMAL else ["time limit reached; optimality unproven"]
        return SolveResult(
            status=status,
            objective=objective,
            assignments=assignments,
            solve_time_ms=solve_time_ms,
            warnings=warnings,
            solver_diagnostics=diagnostics,
        )

    if status_code == cp_model.INFEASIBLE:
        return SolveResult(status=SolveStatus.INFEASIBLE, solve_time_ms=solve_time_ms,
                           solver_diagnostics=diagnostics)

    # UNKNOWN (includes time limit with no plan) and MODEL_INVALID both land
    # here; neither produces a plan.
    label = SolveStatus.TIME_LIMIT if status_code == cp_model.UNKNOWN else SolveStatus.ERROR
    return SolveResult(status=label, solve_time_ms=solve_time_ms,
                       warnings=[f"solver returned status {solver.status_name(status_code)}"],
                       solver_diagnostics=diagnostics)


def _by_order(problem: SchedulingProblem, assignments):
    """Yield assignments in problem.orders order."""
    by_id = {a.order_id: a for a in assignments}
    return [by_id[o.id] for o in problem.orders]
