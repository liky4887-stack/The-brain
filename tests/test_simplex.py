"""Two-phase simplex (Hillier & Lieberman ch.4) vs brute-force vertices.

Every random LP is also solved by enumerating all basic solutions of the
augmented equality system (all m-subsets of columns): the smallest
feasible basic objective is the brute-force optimum. Exact rational
arithmetic on both sides. Unboundedness and infeasibility get dedicated
constructed tests.
"""

import itertools
import random
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lp import LPStatus, solve_lp


def gauss_solve(M, rhs):
    """Exact solve of a square system; None if singular."""
    n = len(M)
    A = [row[:] + [rhs[i]] for i, row in enumerate(M)]
    for col in range(n):
        piv = None
        for r in range(col, n):
            if A[r][col] != 0:
                piv = r
                break
        if piv is None:
            return None
        A[col], A[piv] = A[piv], A[col]
        pv = A[col][col]
        A[col] = [v / pv for v in A[col]]
        for r in range(n):
            if r != col and A[r][col] != 0:
                f = A[r][col]
                A[r] = [a - f * b for a, b in zip(A[r], A[col])]
    return [A[i][n] for i in range(n)]


def brute_force_min(c, A, b, senses):
    """Enumerate all basic feasible solutions of the standard form."""
    m, n = len(A), len(c)
    # augment exactly as the solver does: +1 slack for <=, -1 for >=,
    # and for == no extra column (brute force uses equalities directly).
    cols = []
    for i in range(m):
        row = [Fraction(v) for v in A[i]]
        row += [Fraction(1) if (senses[i] == "<=" and k == i)
                else Fraction(-1) if (senses[i] == ">=" and k == i)
                else Fraction(0) for k in range(m)]
        cols.append(row)
    total = n + m
    bb = [Fraction(v) for v in b]
    best = None
    for basis in itertools.combinations(range(total), m):
        M = [[cols[i][j] for j in basis] for i in range(m)]
        sol = gauss_solve(M, bb)
        if sol is None or any(v < 0 for v in sol):
            continue
        x = [Fraction(0)] * total
        for j, v in zip(basis, sol):
            x[j] = v
        obj = sum(Fraction(c[j]) * x[j] for j in range(n))
        if best is None or obj < best:
            best = obj
    return best


def test_wyndor_glass_locked():
    # The book's running example (ch.3/4): max Z = 3x1 + 5x2,
    # x1 <= 4, 2x2 <= 12, 3x1 + 2x2 <= 18. Optimum Z = 36 at (2, 6).
    r = solve_lp([-3, -5], [[1, 0], [0, 2], [3, 2]], [4, 12, 18],
                 ["<=", "<=", "<="])
    assert r.status == LPStatus.OPTIMAL
    assert r.objective == Fraction(-36)
    assert r.x == [Fraction(2), Fraction(6)]


def test_random_lps_match_vertex_enumeration():
    rng = random.Random(4)
    for trial in range(120):
        m = rng.randint(1, 4)
        n = rng.randint(1, 5)
        # Feasible-by-construction: all <= rows with b >= 0 (origin works)
        # plus occasionally a == row through a known point.
        A, b, senses = [], [], []
        x0 = [Fraction(rng.randint(0, 4)) for _ in range(n)]
        for i in range(m):
            row = [rng.randint(-3, 5) for _ in range(n)]
            kind = rng.choice(["<=", "<=", "=="])
            if kind == "<=":
                rhs = sum(max(0, row[j]) * int(x0[j]) for j in range(n)) + rng.randint(0, 5)
            else:
                rhs = sum(row[j] * int(x0[j]) for j in range(n))
            A.append(row)
            b.append(rhs)
            senses.append(kind)
        c = [rng.randint(-4, 6) for _ in range(n)]
        r = solve_lp(c, A, b, senses)
        brute = brute_force_min(c, A, b, senses)
        if brute is None:
            # No basic feasible solution; the instance may still be
            # feasible (no vertex) - skip rather than over-claim.
            continue
        if r.status == LPStatus.UNBOUNDED:
            continue  # brute force cannot certify unboundedness here
        assert r.status == LPStatus.OPTIMAL, (trial, A, b, senses, c, r)
        assert r.objective == brute, (trial, A, b, senses, c, r.objective, brute)


def test_infeasible_detected():
    r = solve_lp([1], [[1], [1]], [1, 3], ["<=", ">="])
    assert r.status == LPStatus.INFEASIBLE


def test_unbounded_detected():
    # min -x1 with x1 - x2 <= 1: x1 -> infinity.
    r = solve_lp([-1, 0], [[1, -1]], [1], ["<="])
    assert r.status == LPStatus.UNBOUNDED


def test_degenerate_lp_terminates():
    # Degenerate: three planes through one vertex; Bland's rule must not
    # cycle (the reason it was chosen, per sec. 4.5).
    r = solve_lp([1, 1, 1],
                 [[1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]],
                 [2, 2, 2, 2],
                 ["<=", "<=", "<=", "<="])
    assert r.status == LPStatus.OPTIMAL
    assert r.objective == Fraction(0)


def test_equality_only_system():
    # min x + y s.t. x + y == 5, x - y == 1 -> x=3, y=2, obj 5.
    r = solve_lp([1, 1], [[1, 1], [1, -1]], [5, 1], ["==", "=="])
    assert r.status == LPStatus.OPTIMAL
    assert r.objective == Fraction(5)
    assert r.x == [Fraction(3), Fraction(2)]
