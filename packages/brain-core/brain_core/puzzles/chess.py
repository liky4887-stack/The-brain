"""Chessboard placement puzzles as CP-SAT models.

Source: Hürlimann, Puzzles and Games: A Mathematical Modeling Approach
(6th ed. 2025), ch.3: chess1 Knight Domination (sec 3.1), chess4 Queen
Placement I (sec 3.4), chess5 Queen Placement II (sec 3.5). The book's
models are boolean formulas linearized as sum >= 1 (domination) or
implications x -> nor(...) (independence); CP-SAT takes both directly.

Locked book answers (8x8): 14 knights dominate, 5 queens dominate,
8 queens maximum non-attacking (92 distinct solutions).
"""

from __future__ import annotations

from ortools.sat.python import cp_model

KNIGHT_MOVES = [(-2, -1), (-1, -2), (1, -2), (2, -1), (2, 1), (1, 2), (-1, 2), (-2, 1)]


def _solve(model: cp_model.CpModel, time_limit_s: float):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return name, None
    return name, solver


def knight_domination(n: int = 8, time_limit_s: float = 30.0) -> dict:
    """Fewest knights so every square of the n x n board is attacked
    by at least one knight (chess1). The book's constraint ORs only
    the up-to-8 attacking positions, never x[i,j] itself: a knight
    does not cover its own square, so occupied squares must also be
    attacked (total domination). Book answer for n=8: 14."""
    model = cp_model.CpModel()
    x = {(i, j): model.new_bool_var(f"x_{i}_{j}") for i in range(n) for j in range(n)}
    for i in range(n):
        for j in range(n):
            attackers = [
                x[(i + di, j + dj)]
                for di, dj in KNIGHT_MOVES
                if 0 <= i + di < n and 0 <= j + dj < n
            ]
            model.add(sum(attackers) >= 1)
    model.minimize(sum(x.values()))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "knights": None, "board": None}
    board = sorted((i, j) for (i, j) in x if solver.value(x[(i, j)]))
    return {"status": status, "knights": len(board), "board": board}


def queen_domination(n: int = 8, time_limit_s: float = 30.0) -> dict:
    """Fewest queens so every square of the n x n board is attacked
    or occupied (chess4). Book answer for n=8: 5."""
    model = cp_model.CpModel()
    x = {(i, j): model.new_bool_var(f"x_{i}_{j}") for i in range(n) for j in range(n)}
    for i in range(n):
        for j in range(n):
            cover = [x[(i, j)]]
            for h in range(n):
                if h != i:
                    cover.append(x[(h, j)])
                if h != j:
                    cover.append(x[(i, h)])
                jj = j - i + h  # diagonal h - i = jj - j
                if h != i and 0 <= jj < n:
                    cover.append(x[(h, jj)])
                jj2 = i + j - h  # anti-diagonal h + jj2 = i + j
                if h != i and 0 <= jj2 < n:
                    cover.append(x[(h, jj2)])
            model.add(sum(set(cover)) >= 1)
    model.minimize(sum(x.values()))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "queens": None, "board": None}
    board = sorted((i, j) for (i, j) in x if solver.value(x[(i, j)]))
    return {"status": status, "queens": len(board), "board": board}


def max_queens(n: int = 8, count: bool = False, time_limit_s: float = 30.0) -> dict:
    """Most non-attacking queens on the n x n board (chess5).

    Book answer for n=8: 8 queens. With count=True also enumerates all
    solutions (92 for n=8).
    """
    model = cp_model.CpModel()
    x = {(i, j): model.new_bool_var(f"x_{i}_{j}") for i in range(n) for j in range(n)}
    for i in range(n):
        model.add(sum(x[(i, j)] for j in range(n)) <= 1)
        model.add(sum(x[(j, i)] for j in range(n)) <= 1)
    for d in range(-(n - 1), n):  # main diagonals i - j = d
        model.add(sum(x[(i, i - d)] for i in range(n) if 0 <= i - d < n) <= 1)
    for s in range(2 * n - 1):  # anti-diagonals i + j = s
        model.add(sum(x[(i, s - i)] for i in range(n) if 0 <= s - i < n) <= 1)
    placement = list(x.values())
    model.maximize(sum(placement))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "queens": None, "board": None, "solutions": None}
    board = sorted((i, j) for (i, j) in x if solver.value(x[(i, j)]))
    result = {"status": status, "queens": len(board), "board": board, "solutions": None}
    if count and status == "OPTIMAL":
        # enumerate all optimal placements: fix the objective at optimum
        model.add(sum(placement) == len(board))
        model.clear_objective()
        counter = cp_model.CpSolver()
        counter.parameters.max_time_in_seconds = time_limit_s
        counter.parameters.enumerate_all_solutions = True
        cb = _CountingCallback()
        counter.solve(model, cb)
        result["solutions"] = cb.count
    return result


class _CountingCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        super().__init__()
        self.count = 0

    def on_solution_callback(self):
        self.count += 1
