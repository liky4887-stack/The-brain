"""Stage 4 test suite: correctness proven against the exhaustive baseline.

Blueprint test list (docs/notes-03, Stage 4):
- feasible and infeasible instances
- ties (multiple optimal schedules - different sequence, same objective, NOT a failure)
- missing or inconsistent input data (rejected before solving)
- time limits and non-optimal statuses (honest statuses, never fake plans)
- zero and extreme processing times, boundary calendars
- each constraint individually, via deliberately corrupted plans the
  independent validator must reject
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))

from brain_core.domain import FactoryInput
from brain_core.exhaustive import enumerate_best
from brain_core.problem import from_factory_input
from brain_core.solvers.cpsat_solver import solve_cpsat
from brain_core.solvers.result import Assignment, SolveStatus
from brain_core.validation.validator import validate_plan

EXAMPLES = ROOT / "data" / "examples"


def load(name):
    raw = json.loads((EXAMPLES / name).read_text())
    factory = FactoryInput(machine=raw["machine"], orders=raw["orders"])
    return from_factory_input(factory), raw["expected"]


def solve_and_validate(problem, **kwargs):
    result = solve_cpsat(problem, **kwargs)
    if result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        report = validate_plan(problem, result.assignments, result.objective)
        assert report.ok, f"validator rejected a solver plan: {report.errors}"
    return result


# ---------- Hand-computed instances (docs/specs/stage0-tiny-problem.md) ----------

def test_instance_a_strict_optimum():
    problem, expected = load("tiny_a_strict.json")
    result = solve_and_validate(problem)
    assert result.status == SolveStatus.OPTIMAL
    assert result.objective == expected["objective"]
    seq = [a.order_id for a in result.assignments]
    assert seq == ["O2", "O1"]


def test_instance_b_tie_same_objective_either_sequence():
    problem, expected = load("tiny_b_tie.json")
    result = solve_and_validate(problem)
    assert result.status == SolveStatus.OPTIMAL
    assert result.objective == expected["objective"]
    # Either sequence is acceptable; feasibility + objective, not identity.
    assert sorted(a.order_id for a in result.assignments) == ["O1", "O2"]


def test_instance_c_infeasible_is_honest():
    problem, _ = load("tiny_c_infeasible.json")
    result = solve_cpsat(problem)
    assert result.status == SolveStatus.INFEASIBLE
    assert result.objective is None
    assert result.assignments == []


# ---------- Exhaustive baseline: the optimality proof ----------

def test_solver_matches_exhaustive_on_all_examples():
    for name, n_max in [("tiny_a_strict.json", 2), ("tiny_b_tie.json", 2), ("six_orders.json", 6)]:
        problem, _ = load(name)
        assert len(problem.orders) <= n_max
        best_obj, best_plan = enumerate_best(problem)
        result = solve_and_validate(problem)
        assert result.status == SolveStatus.OPTIMAL, f"{name}: {result.status}"
        assert result.objective == pytest.approx(best_obj, abs=1e-6), (
            f"{name}: solver {result.objective} != exhaustive {best_obj}"
        )
        # The exhaustive best plan also passes the independent validator.
        assert validate_plan(problem, best_plan, best_obj).ok


def test_exhaustive_confirms_infeasible_c():
    problem, _ = load("tiny_c_infeasible.json")
    best_obj, best_plan = enumerate_best(problem)
    assert best_obj is None and best_plan == []


# ---------- Input validation: bad data never reaches a solver ----------

def test_duplicate_order_ids_rejected():
    with pytest.raises(Exception, match="duplicate order id"):
        FactoryInput(machine={"id": "M1"}, orders=[
            {"id": "O1", "processing_time": 1, "due_date": 1, "weight": 1},
            {"id": "O1", "processing_time": 2, "due_date": 2, "weight": 1},
        ])


def test_negative_processing_time_rejected():
    with pytest.raises(Exception):
        FactoryInput(machine={"id": "M1"}, orders=[
            {"id": "O1", "processing_time": -1, "due_date": 1, "weight": 1},
        ])


def test_zero_weight_rejected():
    with pytest.raises(Exception):
        FactoryInput(machine={"id": "M1"}, orders=[
            {"id": "O1", "processing_time": 1, "due_date": 1, "weight": 0},
        ])


def test_empty_orders_rejected():
    with pytest.raises(Exception):
        FactoryInput(machine={"id": "M1"}, orders=[])


# ---------- Boundary calendars / extreme times ----------

def test_zero_processing_time_order():
    factory = FactoryInput(machine={"id": "M1"}, orders=[
        {"id": "Z", "processing_time": 0, "due_date": 0, "weight": 1},
        {"id": "R", "processing_time": 4, "due_date": 10, "weight": 2},
    ])
    result = solve_and_validate(from_factory_input(factory))
    assert result.status == SolveStatus.OPTIMAL
    assert result.objective == 0.0


def test_large_processing_times():
    factory = FactoryInput(machine={"id": "M1"}, orders=[
        {"id": "BIG", "processing_time": 1_000_000, "due_date": 500_000, "weight": 1},
        {"id": "SMALL", "processing_time": 1, "due_date": 1, "weight": 3},
    ])
    result = solve_and_validate(from_factory_input(factory))
    assert result.status == SolveStatus.OPTIMAL
    best_obj, _ = enumerate_best(from_factory_input(factory))
    assert result.objective == pytest.approx(best_obj, abs=1e-6)


# ---------- Time-limit honesty ----------

def test_time_limit_status_is_honest():
    # A zero-ish time limit on a nontrivial instance must return an honest
    # status - OPTIMAL/FEASIBLE with a valid plan, or TIME_LIMIT - never a
    # plan that fails validation.
    problem, _ = load("six_orders.json")
    result = solve_cpsat(problem, time_limit_s=0.0001)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE, SolveStatus.TIME_LIMIT)
    if result.status == SolveStatus.FEASIBLE:
        assert "unproven" in " ".join(result.warnings)
    if result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        assert validate_plan(problem, result.assignments, result.objective).ok


# ---------- Validator rejects corrupted plans, per constraint ----------

def corrupted_problem():
    factory = FactoryInput(machine={"id": "M1"}, orders=[
        {"id": "O1", "processing_time": 3, "due_date": 4, "weight": 2, "deadline": 10},
        {"id": "O2", "processing_time": 2, "due_date": 3, "weight": 1},
    ])
    return from_factory_input(factory)


def test_validator_rejects_overlap():
    p = corrupted_problem()
    plan = [Assignment("O1", 0, 3), Assignment("O2", 2, 4)]
    report = validate_plan(p, plan)
    assert not report.ok and any("overlap" in e for e in report.errors)


def test_validator_rejects_wrong_duration():
    p = corrupted_problem()
    plan = [Assignment("O1", 0, 2), Assignment("O2", 3, 5)]  # O1 cut short
    report = validate_plan(p, plan)
    assert not report.ok and any("end" in e for e in report.errors)


def test_validator_rejects_negative_start():
    p = corrupted_problem()
    plan = [Assignment("O1", -1, 2), Assignment("O2", 2, 4)]
    report = validate_plan(p, plan)
    assert not report.ok and any("negative start" in e for e in report.errors)


def test_validator_rejects_deadline_breach():
    p = corrupted_problem()
    plan = [Assignment("O2", 0, 2), Assignment("O1", 8, 11)]  # O1 past deadline 10
    report = validate_plan(p, plan)
    assert not report.ok and any("deadline" in e for e in report.errors)


def test_validator_rejects_missing_order():
    p = corrupted_problem()
    report = validate_plan(p, [Assignment("O1", 0, 3)])
    assert not report.ok and any("missing" in e for e in report.errors)


def test_validator_rejects_unknown_order():
    p = corrupted_problem()
    plan = [Assignment("O1", 0, 3), Assignment("O2", 3, 5), Assignment("GHOST", 5, 6)]
    report = validate_plan(p, plan)
    assert not report.ok and any("unknown" in e for e in report.errors)


def test_validator_rejects_objective_mismatch():
    p = corrupted_problem()
    plan = [Assignment("O1", 0, 3), Assignment("O2", 3, 5)]
    # True objective: O1 end 3 <= due 4 -> 0; O2 end 5, tardy 2 x w1 -> 2.
    report = validate_plan(p, plan, reported_objective=99.0)
    assert not report.ok and any("objective" in e for e in report.errors)
    report_ok = validate_plan(p, plan, reported_objective=2.0)
    assert report_ok.ok
