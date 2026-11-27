"""Infeasible CP-SAT problems name a minimal conflicting set of rules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))
from brain_core.problem import SchedulingProblem, ProblemOrder  # noqa: E402
from brain_core.solvers.cpsat_solver import solve_cpsat, explain_infeasible_cpsat  # noqa: E402
from brain_core.solvers.result import SolveStatus  # noqa: E402


def _prob(orders, horizon):
    kw = {"machine_id": "M1", "orders": orders}
    f = SchedulingProblem.__dataclass_fields__
    if "horizon" in f:
        kw["horizon"] = horizon
    return SchedulingProblem(**kw)


def _o(i, p, d, dl):
    return ProblemOrder(id=i, processing_time=p, due_date=d, weight=1.0, deadline=dl)


def test_two_orders_same_tight_deadline_are_named_and_minimal():
    # A and B both 5 long, both must end by 6 on one machine: conflict is A+B deadlines.
    # C has a slack deadline and must NOT be blamed.
    p = _prob([_o("A", 5, 0, 6), _o("B", 5, 0, 6), _o("C", 1, 0, 100)], 50)
    r = solve_cpsat(p)
    assert r.status == SolveStatus.INFEASIBLE
    c = r.solver_diagnostics["conflicting_constraints"]
    assert c == ["deadline of order A (end <= 6)", "deadline of order B (end <= 6)"], c


def test_minimality_dropping_any_named_rule_is_feasible():
    p = _prob([_o("A", 5, 0, 6), _o("B", 5, 0, 6), _o("C", 1, 0, 100)], 50)
    named = explain_infeasible_cpsat(p)
    for drop in named:
        keep = [o for o in p.orders
                if f"deadline of order {o.id}" not in drop]
        q = _prob(keep, 50)
        assert solve_cpsat(q).status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)


def test_feasible_problem_names_nothing():
    p = _prob([_o("A", 2, 0, 10), _o("B", 2, 0, 10)], 50)
    assert explain_infeasible_cpsat(p) == []
