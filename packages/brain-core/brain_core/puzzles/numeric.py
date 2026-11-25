"""Numeric and grid puzzles as CP-SAT models.

Source: Hürlimann, Puzzles and Games (6th ed. 2025): SevenEleven (sec
2.28), golomb Golomb ruler (sec 5.4), magicsq Magic Squares (sec 5.24),
sudoku (sec 5.27, the binary xi,j,k formulation with one number per
cell/row/column/subblock).
"""

from __future__ import annotations

from typing import Optional, Sequence

from ortools.sat.python import cp_model

BIG = 711_000_000  # 7.11 * 10^8, the book's scaled product


def _solve(model: cp_model.CpModel, time_limit_s: float):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return name, None
    return name, solver


def seven_eleven(time_limit_s: float = 60.0) -> dict:
    """Four prices in cents with sum 711 and product 711000000
    (SevenEleven). Locked unique answer: {120, 125, 150, 316}.

    The product is modeled with chained multiplication equalities;
    symmetry is broken by ordering the prices.
    """
    model = cp_model.CpModel()
    x = [model.new_int_var(1, 711, f"x{i}") for i in range(4)]
    model.add(sum(x) == 711)
    for i in range(3):  # symmetry breaking
        model.add(x[i] <= x[i + 1])
    p1 = model.new_int_var(1, 711 * 711, "p1")
    model.add_multiplication_equality(p1, [x[0], x[1]])
    p2 = model.new_int_var(1, BIG, "p2")
    model.add_multiplication_equality(p2, [p1, x[2]])
    p3 = model.new_int_var(BIG, BIG, "p3")
    model.add_multiplication_equality(p3, [p2, x[3]])
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "prices": None}
    prices = sorted(solver.value(v) for v in x)
    return {"status": status, "prices": prices}


def golomb_ruler(order: int, time_limit_s: float = 60.0) -> dict:
    """Optimal Golomb ruler of the given order (golomb): integer marks
    with all pairwise distances distinct, minimizing the length.
    Locked answers: order 4 -> 6, order 5 -> 11, order 6 -> 17."""
    n = order
    upper = n * n  # safe length bound
    model = cp_model.CpModel()
    mark = [model.new_int_var(0, upper, f"m{i}") for i in range(n)]
    model.add(mark[0] == 0)
    for i in range(n - 1):  # ordering breaks translation/reflection symmetry
        model.add(mark[i] < mark[i + 1])
    dists = []
    for i in range(n):
        for j in range(i + 1, n):
            d = model.new_int_var(1, upper, f"d{i}_{j}")
            model.add(d == mark[j] - mark[i])
            dists.append(d)
    model.add_all_different(dists)
    model.minimize(mark[n - 1])
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "length": None, "marks": None}
    marks = [solver.value(v) for v in mark]
    return {"status": status, "length": marks[-1], "marks": marks}


def magic_square(n: int = 3, time_limit_s: float = 30.0) -> dict:
    """n x n magic square with the numbers 1..n^2 (magicsq).

    Locked answer for n=3: magic constant 15 (solution unique up to
    the 8 symmetries of the square).
    """
    model = cp_model.CpModel()
    x = {(i, j): model.new_int_var(1, n * n, f"x{i}_{j}")
         for i in range(n) for j in range(n)}
    model.add_all_different(x.values())
    target = n * (n * n + 1) // 2  # forced by the sum of 1..n^2
    for i in range(n):
        model.add(sum(x[(i, j)] for j in range(n)) == target)
        model.add(sum(x[(j, i)] for j in range(n)) == target)
    model.add(sum(x[(i, i)] for i in range(n)) == target)
    model.add(sum(x[(i, n - 1 - i)] for i in range(n)) == target)
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "constant": None, "grid": None}
    grid = [[solver.value(x[(i, j)]) for j in range(n)] for i in range(n)]
    return {"status": status, "constant": target, "grid": grid}


def sudoku(givens: Sequence[Sequence[int]], time_limit_s: float = 30.0) -> dict:
    """Sudoku by the book's binary formulation (sudoku): x[i,j,k] = 1
    iff cell (i,j) holds k; one number per cell, and each number once
    per row, column and 3x3 subblock. givens is 9x9 with 0 = blank."""
    if len(givens) != 9 or any(len(row) != 9 for row in givens):
        raise ValueError("givens must be 9x9")
    model = cp_model.CpModel()
    x = {(i, j, k): model.new_bool_var(f"x_{i}_{j}_{k}")
         for i in range(9) for j in range(9) for k in range(1, 10)}
    for i in range(9):
        for j in range(9):
            model.add(sum(x[(i, j, k)] for k in range(1, 10)) == 1)
    for k in range(1, 10):
        for i in range(9):
            model.add(sum(x[(i, j, k)] for j in range(9)) == 1)
            model.add(sum(x[(j, i, k)] for j in range(9)) == 1)
        for bh in range(3):
            for bg in range(3):
                model.add(sum(
                    x[(3 * bh + di, 3 * bg + dj, k)]
                    for di in range(3) for dj in range(3)
                ) == 1)
    for i in range(9):
        for j in range(9):
            if givens[i][j]:
                model.add(x[(i, j, givens[i][j])] == 1)
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "grid": None}
    grid = [[next(k for k in range(1, 10) if solver.value(x[(i, j, k)]))
             for j in range(9)] for i in range(9)]
    return {"status": status, "grid": grid}
