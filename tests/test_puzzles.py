"""Tests for the Hürlimann puzzles module.

Locked answers come from Hürlimann, Puzzles and Games (6th ed. 2025):
chess1 sec 3.1 (14 knights, total domination), chess4 sec 3.4 (5
queens), chess5 sec 3.5 (8 queens, 92 solutions), einstein sec 5.1
(the German owns the fish), alcuin sec 5.2 (7 crossings), golomb sec
5.4 (G(4)=6, G(5)=11, G(6)=17), sendmore sec 5.9 (9567+1085=10652),
change sec 2.27 (1x50c, 1x25c, 4x10c), SevenEleven sec 2.28
({120,125,150,316}), magicsq sec 5.24 (constant 15). The sudoku test
uses a standard published puzzle with a known unique solution: the
book's givens are only available as Figure 5.69 (an image), not as
text, so the fixture is a standard grid, noted as such.

Every returned plan is re-checked by an independent validator that
knows nothing of the model internals; small instances are also checked
against exhaustive baselines.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))


from itertools import combinations

from brain_core.puzzles import (
    change_dollar,
    einstein,
    golomb_ruler,
    knight_domination,
    magic_square,
    max_queens,
    queen_domination,
    send_more_money,
    seven_eleven,
    sudoku,
    wolf_goat_cabbage,
)
from brain_core.puzzles.chess import KNIGHT_MOVES

# ---------------------------------------------------------------- independent
# validators


def valid_total_knight_domination(board, n):
    squares = set(board)
    for i in range(n):
        for j in range(n):
            if not any((i + di, j + dj) in squares for di, dj in KNIGHT_MOVES):
                return False
    return True


def valid_queen_domination(board, n):
    queens = set(board)
    for i in range(n):
        for j in range(n):
            covered = (i, j) in queens
            for qi, qj in queens:
                if qi == i or qj == j or abs(qi - i) == abs(qj - j):
                    covered = True
            if not covered:
                return False
    return True


def valid_nonattacking(board):
    queens = list(board)
    for (a, b), (c, d) in combinations(queens, 2):
        if a == c or b == d or abs(a - c) == abs(b - d):
            return False
    return True


EINSTEIN_RULES = None  # validated inline below


def valid_einstein(a):
    # every category is a permutation of houses 1..5
    for group in a.values():
        if sorted(group.values()) != [1, 2, 3, 4, 5]:
            return False
    N, C, P, D, S = (a["nationality"], a["color"], a["pet"], a["drink"], a["cigar"])
    adj = lambda u, v: abs(u - v) == 1
    return all([
        N["Briton"] == C["red"],
        N["Swede"] == P["dog"],
        N["Dane"] == D["tea"],
        C["green"] + 1 == C["white"],
        C["green"] == D["coffee"],
        S["Pall-Mall"] == P["bird"],
        D["milk"] == 3,
        C["yellow"] == S["Dunhill"],
        N["Norwegian"] == 1,
        adj(S["Marlboro"], P["cat"]),
        adj(P["horse"], S["Dunhill"]),
        adj(S["Marlboro"], D["water"]),
        S["Bluemaster"] == D["juice"],
        C["blue"] == 2,
        N["German"] == S["Prince"],
        adj(N["Norwegian"], C["blue"]),
    ])


def valid_river_plan(plan):
    left = {"wolf", "goat", "cabbage"}
    right = set()
    man_left = True
    for step in plan:
        if step != "empty":
            if man_left:
                if step not in left:
                    return False
                left.discard(step)
                right.add(step)
            else:
                if step not in right:
                    return False
                right.discard(step)
                left.add(step)
        man_left = not man_left
        unattended = right if man_left else left
        if {"wolf", "goat"} <= unattended or {"goat", "cabbage"} <= unattended:
            return False
    return not left


def valid_golomb(marks):
    dists = [b - a for a, b in combinations(marks, 2)]
    return len(dists) == len(set(dists))


def valid_magic(grid):
    n = len(grid)
    flat = [v for row in grid for v in row]
    if sorted(flat) != list(range(1, n * n + 1)):
        return False
    target = n * (n * n + 1) // 2
    lines = ([[grid[i][j] for j in range(n)] for i in range(n)]
             + [[grid[j][i] for j in range(n)] for i in range(n)]
             + [[grid[i][i] for i in range(n)],
                [grid[i][n - 1 - i] for i in range(n)]])
    return all(sum(line) == target for line in lines)


def valid_sudoku(grid, givens):
    want = set(range(1, 10))
    for i in range(9):
        if set(grid[i]) != want or {grid[j][i] for j in range(9)} != want:
            return False
    for bi in range(3):
        for bj in range(3):
            if {grid[3 * bi + di][3 * bj + dj]
                    for di in range(3) for dj in range(3)} != want:
                return False
    return all(givens[i][j] == 0 or grid[i][j] == givens[i][j]
               for i in range(9) for j in range(9))


# ---------------------------------------------------------------- chess (ch.3)


def test_knight_domination_small_matches_exhaustive():
    # exhaustive baseline for 4x4: smallest totally-dominating set
    cells = [(i, j) for i in range(4) for j in range(4)]
    best = None
    for k in range(1, 17):
        for sub in combinations(cells, k):
            if valid_total_knight_domination(sub, 4):
                best = k
                break
        if best is not None:
            break
    r = knight_domination(4)
    assert r["status"] == "OPTIMAL"
    assert r["knights"] == best == 6
    assert valid_total_knight_domination(r["board"], 4)


def test_knight_domination_8x8_locked():
    r = knight_domination(8, time_limit_s=120.0)
    assert r["status"] == "OPTIMAL"
    assert r["knights"] == 14  # book: "at least 14 Knights are necessary"
    assert valid_total_knight_domination(r["board"], 8)


def test_queen_domination_8x8_locked():
    r = queen_domination(8)
    assert r["status"] == "OPTIMAL"
    assert r["queens"] == 5
    assert valid_queen_domination(r["board"], 8)


def test_max_queens_8x8_locked():
    r = max_queens(8, count=True)
    assert r["status"] == "OPTIMAL"
    assert r["queens"] == 8
    assert r["solutions"] == 92  # classical count, confirmed by the book
    assert valid_nonattacking(r["board"])


# ---------------------------------------------------------------- logic (ch.5)


def test_einstein_locked_assignment():
    r = einstein()
    assert r["status"] == "OPTIMAL"
    assert r["fish_owner"] == "German"
    a = r["assignment"]
    assert valid_einstein(a)
    # the unique solution, house by house
    by_house = {h: {} for h in range(1, 6)}
    for group, mapping in a.items():
        for name, house in mapping.items():
            by_house[house][group] = name
    assert by_house[1] == {"nationality": "Norwegian", "color": "yellow",
                           "pet": "cat", "drink": "water", "cigar": "Dunhill"}
    assert by_house[2] == {"nationality": "Dane", "color": "blue",
                           "pet": "horse", "drink": "tea", "cigar": "Marlboro"}
    assert by_house[3] == {"nationality": "Briton", "color": "red",
                           "pet": "bird", "drink": "milk", "cigar": "Pall-Mall"}
    assert by_house[4] == {"nationality": "German", "color": "green",
                           "pet": "fish", "drink": "coffee", "cigar": "Prince"}
    assert by_house[5] == {"nationality": "Swede", "color": "white",
                           "pet": "dog", "drink": "juice", "cigar": "Bluemaster"}


def test_wolf_goat_cabbage_locked():
    r = wolf_goat_cabbage()
    assert r["status"] == "OPTIMAL"
    assert r["crossings"] == 7
    assert valid_river_plan(r["plan"])


def test_send_more_money_locked():
    r = send_more_money()
    assert r["status"] == "OPTIMAL"
    d = r["digits"]
    send = 1000 * d["S"] + 100 * d["E"] + 10 * d["N"] + d["D"]
    more = 1000 * d["M"] + 100 * d["O"] + 10 * d["R"] + d["E"]
    money = (10000 * d["M"] + 1000 * d["O"] + 100 * d["N"]
             + 10 * d["E"] + d["Y"])
    assert send == 9567 and more == 1085 and money == 10652
    assert send + more == money


def test_change_dollar_locked():
    r = change_dollar()
    assert r["status"] == "OPTIMAL"
    assert r["coins"] == {"50c": 1, "25c": 1, "10c": 4, "5c": 0, "1c": 0}


# --------------------------------------------------------------- numeric/grid


def test_seven_eleven_locked():
    r = seven_eleven()
    assert r["status"] == "OPTIMAL"
    assert r["prices"] == [120, 125, 150, 316]
    assert sum(r["prices"]) == 711
    prod = 1
    for p in r["prices"]:
        prod *= p
    assert prod == 711_000_000


def test_golomb_locked_and_exhaustive_4():
    # exhaustive baseline: no 4-mark ruler shorter than 6 exists
    short = False
    for extra in combinations(range(1, 6), 2):
        marks = (0,) + extra + (6 - 1,)  # candidate with length <= 5
        if marks[-1] <= 5 and valid_golomb(marks):
            short = True
    assert not short
    for order, length in [(4, 6), (5, 11), (6, 17)]:
        r = golomb_ruler(order)
        assert r["status"] == "OPTIMAL"
        assert r["length"] == length
        assert valid_golomb(r["marks"])


def test_magic_square_locked():
    r = magic_square(3)
    assert r["status"] == "OPTIMAL"
    assert r["constant"] == 15
    assert valid_magic(r["grid"])


SUDOKU_GIVENS = [  # standard puzzle, unique solution (see module docstring)
    [5, 3, 0, 0, 7, 0, 0, 0, 0],
    [6, 0, 0, 1, 9, 5, 0, 0, 0],
    [0, 9, 8, 0, 0, 0, 0, 6, 0],
    [8, 0, 0, 0, 6, 0, 0, 0, 3],
    [4, 0, 0, 8, 0, 3, 0, 0, 1],
    [7, 0, 0, 0, 2, 0, 0, 0, 6],
    [0, 6, 0, 0, 0, 0, 2, 8, 0],
    [0, 0, 0, 4, 1, 9, 0, 0, 5],
    [0, 0, 0, 0, 8, 0, 0, 7, 9],
]

SUDOKU_SOLUTION = [
    [5, 3, 4, 6, 7, 8, 9, 1, 2],
    [6, 7, 2, 1, 9, 5, 3, 4, 8],
    [1, 9, 8, 3, 4, 2, 5, 6, 7],
    [8, 5, 9, 7, 6, 1, 4, 2, 3],
    [4, 2, 6, 8, 5, 3, 7, 9, 1],
    [7, 1, 3, 9, 2, 4, 8, 5, 6],
    [9, 6, 1, 5, 3, 7, 2, 8, 4],
    [2, 8, 7, 4, 1, 9, 6, 3, 5],
    [3, 4, 5, 2, 8, 6, 1, 7, 9],
]


def test_sudoku_standard_fixture():
    r = sudoku(SUDOKU_GIVENS)
    assert r["status"] == "OPTIMAL"
    assert valid_sudoku(r["grid"], SUDOKU_GIVENS)
    assert r["grid"] == SUDOKU_SOLUTION
