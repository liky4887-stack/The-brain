"""Golden scenarios: realistic instances with locked expected outcomes.

Two lock strengths, kept honest in data/scenarios/goldens.json:
- proof "exhaustive": the test enumerates every sequence and confirms the
  locked objective is the true optimum; the solver must match it.
- proof "solver": the locked value is the solver's own proven-optimal result
  (exhaustive impractical at that size); the lock guards against regressions
  but is not an independent optimality proof.

Every returned plan is checked by the independent validator.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))

from brain_core.domain import FactoryInput  # noqa: E402
from brain_core.exhaustive import enumerate_best  # noqa: E402
from brain_core.problem import from_factory_input  # noqa: E402
from brain_core.solvers.cpsat_solver import solve_cpsat  # noqa: E402
from brain_core.solvers.result import SolveStatus  # noqa: E402
from brain_core.validation.validator import validate_plan  # noqa: E402

SCENARIOS = ROOT / "data" / "scenarios"
GOLDENS = json.loads((SCENARIOS / "goldens.json").read_text())


def load(name):
    data = json.loads((SCENARIOS / f"{name}.json").read_text())
    return from_factory_input(FactoryInput(machine=data["machine"], orders=data["orders"]))


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_golden_scenario(name):
    lock = GOLDENS[name]
    problem = load(name)
    result = solve_cpsat(problem, time_limit_s=60.0)

    assert result.status == SolveStatus(lock["status"]), (
        f"{name}: expected {lock['status']}, got {result.status.value}"
    )
    assert result.objective == pytest.approx(lock["objective"], abs=1e-6), (
        f"{name}: expected locked objective {lock['objective']}, got {result.objective}"
    )

    report = validate_plan(problem, result.assignments, result.objective)
    assert report.ok, f"{name}: validator rejected golden plan: {report.errors}"

    if lock["proof"] == "exhaustive":
        best_obj, best_plan = enumerate_best(problem)
        assert best_obj is not None, f"{name}: exhaustive found no feasible plan"
        assert best_obj == pytest.approx(lock["objective"], abs=1e-6), (
            f"{name}: locked objective {lock['objective']} is not the true optimum {best_obj}"
        )
        assert result.objective == pytest.approx(best_obj, abs=1e-6)


def test_every_scenario_file_is_locked():
    files = {p.stem for p in SCENARIOS.glob("*.json")} - {"goldens"}
    assert files == set(GOLDENS), (
        f"scenario files without a golden lock or vice versa: {files ^ set(GOLDENS)}"
    )


def test_dominant_weight_behavior():
    """The 100-weight order must never be late when avoiding it costs the rest 51."""
    problem = load("dominant_weight")
    result = solve_cpsat(problem, time_limit_s=60.0)
    d1 = next(a for a in result.assignments if a.order_id == "D1")
    due = next(o for o in problem.orders if o.id == "D1").due_date
    assert d1.end <= due, "dominant order finished late despite available objective-51 plan"
