"""Traveling Salesman Problem: DFJ model with lazy subtour elimination.

Source: Fischetti, Introduction to Mathematical Optimization (5th ed.
2019), sec. 8.2 model (8.2a)-(8.2e): minimize circuit cost with one
arc entering and one leaving every vertex, plus the connectivity
("reachability from 1") family (8.2d). The book solves it by
branch-and-cut, separating (8.2d) over the fractional relaxation; we
use the same constraint-generation loop over INTEGER solutions (the
assignment relaxation solved to integrality by CP-SAT): any subtour in
an integer solution yields a violated set S directly, so separation
is exact and cheap. Each added constraint is one of the book's
(8.2d), written for the subtour's vertex set.
"""

from __future__ import annotations

from typing import Sequence

from ortools.sat.python import cp_model


def solve_tsp(cost: Sequence[Sequence[int]], time_limit_s: float = 30.0,
              max_rounds: int = 100) -> dict:
    """Min-cost Hamiltonian circuit on the complete digraph with cost
    matrix cost[i][j] (i != j). Returns status, objective, tour
    (0-based vertex order starting at 0), and rounds of constraint
    generation."""
    n = len(cost)
    if n < 3:
        raise ValueError("need at least 3 cities")
    model = cp_model.CpModel()
    x = {(i, j): model.new_bool_var(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    for j in range(n):  # (8.2b) one arc entering j
        model.add(sum(x[(i, j)] for i in range(n) if i != j) == 1)
    for i in range(n):  # (8.2c) one arc leaving i
        model.add(sum(x[(i, j)] for j in range(n) if j != i) == 1)
    model.minimize(sum(cost[i][j] * x[(i, j)]
                       for i in range(n) for j in range(n) if i != j))
    rounds = 0
    for _ in range(max_rounds):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        status = solver.solve(model)
        name = solver.status_name(status)
        if name not in ("OPTIMAL", "FEASIBLE"):
            return {"status": name, "objective": None, "tour": None,
                    "rounds": rounds}
        rounds += 1
        # find subtours in the current (integer) solution
        nxt = {i: next(j for j in range(n) if j != i
                       and solver.value(x[(i, j)])) for i in range(n)}
        seen = [False] * n
        subtours = []
        for start in range(n):
            if seen[start]:
                continue
            tour = [start]
            seen[start] = True
            while nxt[tour[-1]] != start:
                tour.append(nxt[tour[-1]])
                seen[tour[-1]] = True
            subtours.append(tour)
        if len(subtours) == 1:
            tour = subtours[0]
            obj = sum(cost[tour[k]][tour[(k + 1) % n]] for k in range(n))
            return {"status": name, "objective": obj, "tour": tour,
                    "rounds": rounds}
        for S in subtours:  # (8.2d) for the violated set S
            model.add(sum(x[(i, j)] for i in S for j in range(n)
                          if j not in S) >= 1)
    return {"status": "round_limit", "objective": None, "tour": None,
            "rounds": rounds}
