"""Cross-validation: Li's linear-ordering formulation vs interval solver vs
exhaustive baseline.

Three independent routes to the optimum - two different CP-SAT formulations
and full enumeration - must agree on every example and every exhaustive
golden scenario. A disagreement means at least one formulation is wrong;
this is the mechanized form of Williams ch.6 validation.
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
from brain_core.solvers.ordering_solver import solve_ordering  # noqa: E402
from brain_core.solvers.result import SolveStatus  # noqa: E402
from brain_core.validation.validator import validate_plan  # noqa: E402

EXAMPLES = sorted(p for p in (ROOT / "data" / "examples").glob("*.json"))
GOLDENS = json.loads((ROOT / "data" / "scenarios" / "goldens.json").read_text())
SMALL_SCENARIOS = [ROOT / "data" / "scenarios" / f"{name}.json"
                   for name, lock in GOLDENS.items() if lock["proof"] == "exhaustive"]


def load(path):
    data = json.loads(path.read_text())
    return from_factory_input(FactoryInput(machine=data["machine"], orders=data["orders"]))


@pytest.mark.parametrize("path", EXAMPLES + SMALL_SCENARIOS,
                         ids=[p.stem for p in EXAMPLES + SMALL_SCENARIOS])
def test_three_routes_agree(path):
    problem = load(path)
    interval = solve_cpsat(problem, time_limit_s=30.0)
    ordering = solve_ordering(problem, time_limit_s=30.0)
    best_obj, _ = enumerate_best(problem)

    assert interval.status == ordering.status, (
        f"{path.stem}: interval {interval.status.value} vs ordering {ordering.status.value}"
    )
    if best_obj is None:
        assert interval.status == SolveStatus.INFEASIBLE
        return

    assert interval.status == SolveStatus.OPTIMAL
    assert ordering.objective == pytest.approx(interval.objective, abs=1e-6)
    assert ordering.objective == pytest.approx(best_obj, abs=1e-6)

    report = validate_plan(problem, ordering.assignments, ordering.objective)
    assert report.ok, f"{path.stem}: validator rejected ordering-solver plan: {report.errors}"


def test_ordering_solver_honest_infeasible():
    problem = load(ROOT / "data" / "examples" / "tiny_c_infeasible.json")
    result = solve_ordering(problem, time_limit_s=5.0)
    assert result.status == SolveStatus.INFEASIBLE
    assert result.assignments == []
    assert result.objective is None
