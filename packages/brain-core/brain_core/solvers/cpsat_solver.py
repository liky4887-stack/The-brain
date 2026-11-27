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
        diagnostics["conflicting_constraints"] = explain_infeasible_cpsat(problem)
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


def explain_infeasible_cpsat(problem: SchedulingProblem, time_limit_s: float = 10.0) -> list[str]:
    """Name a MINIMAL set of conflicting rules for an infeasible problem.

    Method (CP-SAT assumptions): each rule is guarded by a literal (the hard deadline of each order). The model
    is solved under the literals of the rules still active; on INFEASIBLE
    the solver returns a sufficient set of assumptions, then a deletion
    filter drops each rule in turn and keeps the drop only when the rest
    stays INFEASIBLE. The result is irreducible: removing any one named
    rule makes the remaining rules feasible. The machine's no-overlap and
    the processing times are the structure itself and are never blamed.
    If a re-solve is undecided within the limit the list carries an
    explicit "unminimized" entry (never silent). Returns [] when the
    problem is infeasible without any named rule.
    """
    horizon = max(problem.horizon, 1)
    d_names = {o.id: f"deadline of order {o.id} (end <= {o.deadline})"
               for o in problem.orders if o.deadline is not None}
    all_rules = list(d_names.values())

    def run(active):
        m = cp_model.CpModel()
        lit = {}
        ivs, ends = [], {}
        for o in problem.orders:
            st = m.new_int_var(0, horizon, f"s_{o.id}")
            en = m.new_int_var(0, horizon, f"e_{o.id}")
            ivs.append(m.new_interval_var(st, o.processing_time, en, f"i_{o.id}"))
            if o.id in d_names:
                lit[d_names[o.id]] = m.new_bool_var(f"deadline_{o.id}")
                m.add(en <= o.deadline).only_enforce_if(lit[d_names[o.id]])
        m.add_no_overlap(ivs)
        m.add_assumptions([lit[n] for n in all_rules if n in active])
        sv = cp_model.CpSolver()
        sv.parameters.max_time_in_seconds = time_limit_s
        code = sv.solve(m)
        core = set()
        if code == cp_model.INFEASIBLE:
            idx = set(sv.sufficient_assumptions_for_infeasibility())
            core = {n for n in active if lit[n].index in idx}
        return code, core

    code, core = run(set(all_rules))
    if code != cp_model.INFEASIBLE:
        return []
    unminimized = False
    for n in sorted(core):
        c2, core2 = run(core - {n})
        if c2 == cp_model.INFEASIBLE:
            core = core2 if core2 else core - {n}
        elif c2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            unminimized = True
    out = sorted(core)
    if unminimized:
        out.append("(unminimized: a re-solve was undecided within the limit)")
    return out
