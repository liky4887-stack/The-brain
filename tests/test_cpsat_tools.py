"""Tests for the CP-SAT Primer tooling (Krupke, CC-BY 4.0).

Locked: the primer's own unsat-core example (x+y<=4, x+z<=2, z>=4 is
infeasible and the core names the last two constraints). Hints are
checked both ways: a feasible hint verifies, an infeasible one does
not, and a wrong hint never changes the optimum (hints seed the
search, they do not constrain it).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from ortools.sat.python import cp_model

from brain_core.solvers.cpsat_tools import (
    assert_hint_feasible,
    explain_infeasibility,
    solve_with_hint,
)


def _knapsack():
    model = cp_model.CpModel()
    x = [model.new_int_var(0, 1, f"x{i}") for i in range(4)]
    model.add(2 * x[0] + 3 * x[1] + 4 * x[2] + 5 * x[3] <= 7)
    model.maximize(3 * x[0] + 4 * x[1] + 5 * x[2] + 6 * x[3])
    return model, x


def test_explain_infeasibility_primer_example_locked():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 100, "x")
    y = model.new_int_var(0, 100, "y")
    z = model.new_int_var(0, 100, "z")
    r = explain_infeasibility(model, [
        ("c1: x+y<=4", x + y <= 4),
        ("c2: x+z<=2", x + z <= 2),
        ("c3: z>=4", z >= 4),
    ])
    assert r["status"] == "INFEASIBLE"
    assert set(r["core"]) == {"c2: x+z<=2", "c3: z>=4"}


def test_explain_feasible_model_has_no_core():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 100, "x")
    y = model.new_int_var(0, 100, "y")
    r = explain_infeasibility(model, [("c1", x + y <= 4), ("c2", x >= 1)])
    assert r["status"] == "OPTIMAL"
    assert r["core"] is None


def test_assert_hint_feasible_both_ways():
    model, x = _knapsack()
    assert assert_hint_feasible(model, [(x[0], 1), (x[3], 1)])  # weight 7, ok
    assert not assert_hint_feasible(model, [(x[2], 1), (x[3], 1)])  # weight 9
    # the caller's model is untouched: it still has no fixed values
    r = solve_with_hint(model, {})
    assert r["status"] == "OPTIMAL"


def test_wrong_hint_never_changes_the_optimum():
    model, x = _knapsack()
    # the true optimum: items 1 and 3 (weight 7, value 9); hint the
    # worst feasible item instead
    r = solve_with_hint(model, [(x[0], 1), (x[1], 0), (x[2], 0), (x[3], 0)])
    assert r["status"] == "OPTIMAL"
    assert r["objective"] == 9  # optimum despite the misleading hint


def test_warm_start_after_change_matches_cold_solve():
    # solve, tighten the capacity, re-solve with the old solution as a
    # hint (the Stage 3 local-replan pattern); results must agree with
    # a cold solve of the changed model
    model, x = _knapsack()
    r1 = solve_with_hint(model, {})
    assert r1["status"] == "OPTIMAL"
    model2 = cp_model.CpModel()
    y = [model2.new_int_var(0, 1, f"y{i}") for i in range(4)]
    model2.add(2 * y[0] + 3 * y[1] + 4 * y[2] + 5 * y[3] <= 5)
    model2.maximize(3 * y[0] + 4 * y[1] + 5 * y[2] + 6 * y[3])
    old_solution = [(y[i], r1["values"].get(x[i].name, 0)) for i in range(4)]
    warm = solve_with_hint(model2, old_solution)
    cold = solve_with_hint(model2.clone(), {})
    assert warm["status"] == "OPTIMAL" == cold["status"]
    assert warm["objective"] == cold["objective"] == 7  # items 0 and 1
