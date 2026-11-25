"""Linear-ordering formulation: an independent second solver (Li 11.2.3).

From Li, Optimization Modeling for Supply Chain Applications, ch.11.2.3,
generalized from total tardiness to total WEIGHTED tardiness with optional
hard deadlines:

- x_ij = 1 iff order i is processed before order j (i != j)
- x_ij + x_ji = 1 for every pair
- transitivity: x_ij + x_jk + x_ki <= 2 for every triple (O(n^3) constraints;
  practical for the instance sizes this solver is meant to cross-validate)
- completion of j is start + p_j where start = sum_i p_i * x_ij (no idle
  time; valid here because weighted tardiness with no release dates is a
  regular objective - Li 11.2.2)
- tardiness T_j >= sum_i p_i*x_ij + p_j - d_j, T_j >= 0
- hard deadline: sum_i p_i*x_ij + p_j <= deadline_j

Why this solver exists: it shares no formulation machinery with the
interval/no_overlap model (cpsat_solver.py). Two independent formulations
reaching the same optimum on every example and golden scenario is far
stronger evidence than either alone (Williams ch.6: validation as a
two-way process). Same honesty rules as the interval solver: statuses map
1:1, objective recomputed from the returned assignment.
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from ..problem import SchedulingProblem
from .cpsat_solver import WEIGHT_SCALE, _by_order
from .result import Assignment, SolveResult, SolveStatus


def solve_ordering(problem: SchedulingProblem, time_limit_s: float = 10.0) -> SolveResult:
    model = cp_model.CpModel()
    orders = problem.orders
    n = len(orders)

    before = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                before[i, j] = model.new_bool_var(f"before_{orders[i].id}_{orders[j].id}")
    for i in range(n):
        for j in range(i + 1, n):
            model.add(before[i, j] + before[j, i] == 1)
    # Transitivity, written as cycle prevention. Each unordered triple
    # {a, b, c} needs exactly two constraints, one per cycle direction;
    # iterating ordered triples would emit each form three times.
    for a in range(n):
        for b in range(a + 1, n):
            for c in range(b + 1, n):
                model.add(before[a, b] + before[b, c] + before[c, a] <= 2)
                model.add(before[a, c] + before[c, b] + before[b, a] <= 2)

    tardiness_terms = []
    for j, order in enumerate(orders):
        start_expr = sum(orders[i].processing_time * before[i, j]
                         for i in range(n) if i != j)
        completion = start_expr + order.processing_time
        if order.deadline is not None:
            model.add(completion <= order.deadline)
        tardy = model.new_int_var(0, max(problem.horizon, 1), f"tardy_{order.id}")
        model.add(tardy >= completion - order.due_date)
        tardiness_terms.append(round(order.weight * WEIGHT_SCALE) * tardy)

    model.minimize(sum(tardiness_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status_code = solver.solve(model)

    diagnostics = {
        "solver": "cp-sat-linear-ordering",
        "formulation": "li-11.2.3",
        "weight_scale": WEIGHT_SCALE,
        "wall_time_s": round(solver.wall_time, 3),
        "branches": solver.num_branches,
        "conflicts": solver.num_conflicts,
    }
    solve_time_ms = int(round(solver.wall_time * 1000))

    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # reconstruct the sequence: order by count of predecessors, then emit
        # a no-idle schedule in that order (valid for regular objectives)
        rank = {j: sum(solver.value(before[i, j]) for i in range(n) if i != j)
                for j in range(n)}
        sequence = sorted(range(n), key=lambda j: rank[j])  # fewest predecessors first
        assignments = []
        t = 0
        for j in sequence:
            o = orders[j]
            assignments.append(Assignment(order_id=o.id, start=t, end=t + o.processing_time))
            t += o.processing_time
        objective = 0.0
        for order, a in zip(problem.orders, _by_order(problem, assignments)):
            objective += order.weight * max(0, a.end - order.due_date)
        status = SolveStatus.OPTIMAL if status_code == cp_model.OPTIMAL else SolveStatus.FEASIBLE
        warnings = [] if status == SolveStatus.OPTIMAL else ["time limit reached; optimality unproven"]
        return SolveResult(status=status, objective=objective, assignments=assignments,
                           solve_time_ms=solve_time_ms, warnings=warnings,
                           solver_diagnostics=diagnostics)

    if status_code == cp_model.INFEASIBLE:
        return SolveResult(status=SolveStatus.INFEASIBLE, solve_time_ms=solve_time_ms,
                           solver_diagnostics=diagnostics)

    label = SolveStatus.TIME_LIMIT if status_code == cp_model.UNKNOWN else SolveStatus.ERROR
    return SolveResult(status=label, solve_time_ms=solve_time_ms,
                       warnings=[f"solver returned status {solver.status_name(status_code)}"],
                       solver_diagnostics=diagnostics)
