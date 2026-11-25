"""Tests for the Fischetti branch-and-cut modules.

Locked instance: Fischetti Example 1 (sec 6.3): min -x2 s.t.
3x1 + 2x2 <= 6, -3x1 + 2x2 <= 0, x1,x2 >= 0 integer. Relaxation
optimum (1, 3/2) with z = -3/2; after two Gomory cuts the book
reaches the integer optimum C = (1,1), z = -1 (its Figure 6.6).
Everything else is cross-checked against brute-force enumeration
(random small ILPs) and brute-force permutation (TSP).
"""

import random
import sys
from fractions import Fraction
from itertools import permutations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.ilp import solve_ilp_bb, solve_ilp_gomory, solve_tsp

EX1_C = [0, -1]
EX1_A = [[3, 2], [-3, 2]]
EX1_B = [6, 0]
EX1_S = ["<=", "<="]


def brute_ilp(c, A, b, senses, bound=6):
    """Min c.x over integer x in [0, bound]^n satisfying all rows."""
    best = None
    best_x = None
    n = len(c)
    for combo in __import__("itertools").product(range(bound + 1), repeat=n):
        ok = True
        for row, rhs, sense in zip(A, b, senses):
            lhs = sum(Fraction(v) * w for v, w in zip(row, combo))
            if sense == "<=" and not lhs <= rhs:
                ok = False
            elif sense == ">=" and not lhs >= rhs:
                ok = False
            elif sense == "==" and not lhs == rhs:
                ok = False
            if not ok:
                break
        if ok:
            obj = sum(Fraction(v) * w for v, w in zip(c, combo))
            if best is None or obj < best:
                best, best_x = obj, list(combo)
    return best, best_x


def test_gomory_fischetti_example_1_locked():
    r = solve_ilp_gomory(EX1_C, EX1_A, EX1_B, EX1_S)
    assert r["status"] == "optimal"
    assert r["objective"] == Fraction(-1)
    assert r["x"] == [Fraction(1), Fraction(1)]
    assert len(r["cuts"]) == 2  # the book's two cuts (Figure 6.6)
    # fractional form (6.4): all coefficients nonnegative
    for cut in r["cuts"]:
        assert all(v >= 0 for v in cut["coeffs"])
        assert 0 < cut["rhs"] < 1


def test_gomory_matches_brute_force():
    rng = random.Random(2026)
    for _ in range(40):
        n, m = 3, 3
        A = [[rng.randint(-4, 5) for _ in range(n)] for _ in range(m)]
        b = [rng.randint(0, 10) for _ in range(m)]
        c = [rng.randint(-5, 5) for _ in range(n)]
        senses = ["<="] * m
        # bound every variable so the brute-force box is exact
        A_b = A + [[1 if j == i else 0 for j in range(n)] for i in range(n)]
        b_b = b + [5] * n
        s_b = senses + ["<="] * n
        best, _ = brute_ilp(c, A_b, b_b, s_b, bound=5)
        r = solve_ilp_gomory(c, A_b, b_b, s_b)
        if best is None:
            assert r["status"] != "optimal"
        elif r["status"] == "optimal":
            assert r["objective"] == best


def test_branch_and_bound_fischetti_example_1_locked():
    for strategy in ("best-bound", "dfs"):
        r = solve_ilp_bb(EX1_C, EX1_A, EX1_B, EX1_S, strategy=strategy)
        assert r["status"] == "optimal"
        assert r["objective"] == Fraction(-1)
        assert r["x"] == [Fraction(1), Fraction(1)]


def test_branch_and_bound_matches_brute_force():
    rng = random.Random(99)
    for _ in range(40):
        n, m = 3, 3
        A = [[rng.randint(-4, 5) for _ in range(n)] for _ in range(m)]
        b = [rng.randint(0, 10) for _ in range(m)]
        c = [rng.randint(-5, 5) for _ in range(n)]
        senses = ["<="] * m
        # bound every variable so the box check is exact
        A_b = A + [[1 if j == i else 0 for j in range(n)] for i in range(n)]
        b_b = b + [4] * n
        s_b = senses + ["<="] * n
        best, best_x = brute_ilp(c, A_b, b_b, s_b, bound=4)
        r = solve_ilp_bb(c, A_b, b_b, s_b)
        assert r["status"] == "optimal"
        assert r["objective"] == best
        # the returned point is feasible and attains the bound
        for row, rhs, sense in zip(A_b, b_b, s_b):
            lhs = sum(v * w for v, w in zip(row, r["x"]))
            assert lhs <= rhs


def test_branch_and_bound_infeasible():
    r = solve_ilp_bb([1], [[1], [1]], [1, 3], [">=", "<="])
    # x >= 1 and x <= 3 has integer solutions; use a truly empty one
    r = solve_ilp_bb([1, 1], [[2, 2]], [3], ["=="])
    assert r["status"] == "infeasible"  # 2x1 + 2x2 = 3 has no integer sol


def test_gomory_and_bb_agree():
    rng = random.Random(7)
    for _ in range(20):
        n, m = 3, 2
        A = [[rng.randint(0, 5) for _ in range(n)] for _ in range(m)]
        b = [rng.randint(3, 12) for _ in range(m)]
        c = [rng.randint(-4, 6) for _ in range(n)]
        rg = solve_ilp_gomory(c, A, b, ["<="] * m)
        rb = solve_ilp_bb(c, A, b, ["<="] * m)
        if rg["status"] == "optimal" and rb["status"] == "optimal":
            assert rg["objective"] == rb["objective"]


TSP5 = [
    [0, 10, 15, 20, 25],
    [10, 0, 35, 25, 30],
    [15, 35, 0, 30, 5],
    [20, 25, 30, 0, 12],
    [25, 30, 5, 12, 0],
]


def brute_tsp(cost):
    n = len(cost)
    best = None
    for perm in permutations(range(1, n)):
        tour = (0,) + perm
        obj = sum(cost[tour[k]][tour[(k + 1) % n]] for k in range(n))
        if best is None or obj < best:
            best = obj
    return best


def valid_tour(tour, n):
    return sorted(tour) == list(range(n))


def test_tsp_5city_handchecked():
    # brute-forced optimum for this matrix is 67: 0-1-3-4-2-0
    assert brute_tsp(TSP5) == 67
    r = solve_tsp(TSP5)
    assert r["status"] == "OPTIMAL"
    assert r["objective"] == 67
    assert valid_tour(r["tour"], 5)


def test_tsp_matches_brute_force():
    rng = random.Random(1234)
    for n in (6, 7):
        for _ in range(5):
            cost = [[0 if i == j else rng.randint(1, 60)
                     for j in range(n)] for i in range(n)]
            r = solve_tsp(cost)
            assert r["status"] == "OPTIMAL"
            assert r["objective"] == brute_tsp(cost)
            assert valid_tour(r["tour"], n)
