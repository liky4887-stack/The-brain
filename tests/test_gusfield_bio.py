"""Tests for the Gusfield computational-biology ILP modules.

Locked answers come from Gusfield, ILP in Computational and Systems
Biology (BCB tutorial, 2019): the Species-Protection toy instance
(optimal 108.7K rounded up, XA=0.831, XD=0.269, XE=1; what-if max
XB = 0.00296 under cost <= 108.7; cost 111.7K under XB >= 0.1), the
5-node maximum-clique example (value 3, clique {1,3,5} 1-based), the
RNA toy S=ACUGU (2 pairs). Graph tests cross-check against brute-force
subset enumeration; idiom tests enumerate every assignment and check
the indicator logic holds universally.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))


from fractions import Fraction
from itertools import combinations

import pytest
from ortools.sat.python import cp_model

from brain_core.bio import (
    TOY_ABUNDANCE,
    TOY_COSTS,
    TOY_TARGETS,
    high_density_subgraph,
    max_clique,
    max_near_clique,
    rna_fold,
    species_protection,
)
from brain_core.ilp import (
    add_if_then,
    add_implied_satisfaction,
    add_not_equal,
    add_not_equal_indicator,
    add_only_if,
    add_or,
    add_xor,
)

# The book's 5-node graph (Figure in Part II): non-edges (1,4), (2,3),
# (2,5), (4,5) 1-based.
BOOK_EDGES = [(0, 1), (0, 2), (0, 4), (1, 3), (2, 3), (2, 4)]


def brute_max_clique(n, edges):
    E = {tuple(sorted(e)) for e in edges}
    for k in range(n, 0, -1):
        for sub in combinations(range(n), k):
            if all((a, b) in E for a, b in combinations(sub, 2)):
                return k, set(sub)
    return 0, set()


def valid_clique(clique, edges):
    E = {tuple(sorted(e)) for e in edges}
    return all(tuple(sorted(p)) in E for p in combinations(clique, 2))


def test_species_protection_exact_locked():
    r = species_protection(TOY_COSTS, TOY_ABUNDANCE, TOY_TARGETS)
    assert r["status"] == "optimal"
    # exact rational optimum; the book reports it rounded up as 108.7
    assert r["objective"] == Fraction(45072, 415)
    assert float(r["objective"]) == pytest.approx(108.6072, abs=1e-4)
    xa, xb, xc, xd, xe = r["x"]
    assert xb == 0 and xc == 0 and xe == 1
    assert float(xa) == pytest.approx(0.831, abs=1e-3)
    assert float(xd) == pytest.approx(0.269, abs=1e-3)


def test_species_what_if_variants_locked():
    # max X_B without spending more than 108.7K: book answer 0.00296
    r = species_protection(
        TOY_COSTS, TOY_ABUNDANCE, TOY_TARGETS,
        extra=[([97, 73, 22, 11, 25], "<=", Fraction(1087, 10))],
        maximize=[0, 1, 0, 0, 0])
    assert float(r["objective"]) == pytest.approx(0.00296, abs=1e-5)
    # force at least 10% of region B: book answer 111.7K
    r2 = species_protection(
        TOY_COSTS, TOY_ABUNDANCE, TOY_TARGETS,
        extra=[([0, 1, 0, 0, 0], ">=", Fraction(1, 10))])
    assert float(r2["objective"]) == pytest.approx(111.7, abs=0.05)


def test_max_clique_book_example_locked():
    r = max_clique(5, BOOK_EDGES)
    assert r["status"] == "OPTIMAL"
    assert r["size"] == 3  # book's Gurobi run: objective 3
    assert valid_clique(r["clique"], BOOK_EDGES)


def test_max_clique_matches_brute_force():
    # every graph on 6 nodes with edges chosen by a fixed pattern
    for mask in range(0, 2**15, 211):  # 155 deterministic samples
        edges = [(i, j) for i in range(6) for j in range(i + 1, 6)
                 if (mask >> (i * 6 + j)) & 1]
        r = max_clique(6, edges)
        k, _ = brute_max_clique(6, edges)
        assert r["status"] == "OPTIMAL"
        assert r["size"] == k
        assert valid_clique(r["clique"], edges)


def test_max_near_clique_book_graph():
    # hand-checked on the book's graph: no 4-set has <= 1 missing edge,
    # but {1,2,3,4} and others have exactly 2
    r1 = max_near_clique(5, BOOK_EDGES, k=1)
    assert r1["size"] == 3
    r2 = max_near_clique(5, BOOK_EDGES, k=2)
    assert r2["size"] == 4
    E = {tuple(sorted(e)) for e in BOOK_EDGES}
    missing = sum(1 for p in combinations(r2["clique"], 2)
                  if tuple(sorted(p)) not in E)
    assert missing <= 2


def test_high_density_subgraph_book_graph():
    r = high_density_subgraph(5, BOOK_EDGES, 0.8)
    assert r["status"] == "OPTIMAL"
    assert r["size"] == 3 and r["density"] == 1.0
    # at d = 0.6 the whole graph (6 edges out of 10) qualifies
    r2 = high_density_subgraph(5, BOOK_EDGES, 0.6)
    assert r2["size"] == 5


def test_rna_fold_book_toy_locked():
    r = rna_fold("ACUGU")
    assert r["status"] == "OPTIMAL"
    assert r["matched"] == 2  # e.g. (1,5) and (2,4) 1-based
    assert set(r["pairs"]) == {(0, 4), (1, 3)}


def _valid_rna_pairing(seq, pairs, min_distance=1):
    comp = {frozenset("AU"), frozenset("CG")}
    used = set()
    for i, j in pairs:
        if j - i < min_distance or frozenset((seq[i], seq[j])) not in comp:
            return False
        if i in used or j in used:
            return False
        used.add(i)
        used.add(j)
    for (i, j), (i2, j2) in combinations(pairs, 2):
        if i < i2 < j < j2 or i2 < i < j2 < j:
            return False
    return True


def test_rna_fold_against_dynamic_programming():
    # independent baseline: classic Nussinov DP recurrence
    def nussinov(s, d=1):
        n = len(s)
        comp = {frozenset("AU"), frozenset("CG")}
        dp = [[0] * n for _ in range(n)]
        for span in range(d, n):
            for i in range(n - span):
                j = i + span
                best = dp[i + 1][j] if i + 1 <= j else 0
                best = max(best, dp[i][j - 1])
                if frozenset((s[i], s[j])) in comp:
                    best = max(best, (dp[i + 1][j - 1] if i + 1 <= j - 1 else 0) + 1)
                for k in range(i + 1, j):
                    best = max(best, dp[i][k] + dp[k + 1][j])
                dp[i][j] = best
        return dp[0][n - 1]

    seqs = ["ACUGU", "GCAUGC", "ACGUGCCACGAU", "GGGAAACCC", "AUCGCGUA"]
    for s in seqs:
        r = rna_fold(s)
        assert r["status"] == "OPTIMAL"
        assert r["matched"] == nussinov(s)
        assert _valid_rna_pairing(s, r["pairs"])


def test_rna_stacking_quartets():
    # GCAUGC folds as three nested pairs with two stacked quartets
    r = rna_fold("GCAUGC", stacking=True)
    assert r["status"] == "OPTIMAL"
    assert r["matched"] == 3
    assert len(r["quartets"]) == 2
    for (i, j) in r["quartets"]:
        assert (i, j) in r["pairs"] and (i + 1, j - 1) in r["pairs"]


def test_rna_weighted_prefers_gc():
    # AU weight 2, CG weight 3 (hydrogen bonds)
    r = rna_fold("ACUGU", weighted=True)
    assert r["status"] == "OPTIMAL"
    assert set(r["pairs"]) == {(0, 4), (1, 3)}  # AU + CG = 5
    assert _valid_rna_pairing("ACUGU", r["pairs"])


def test_rna_min_distance():
    r = rna_fold("ACUGU", min_distance=3)
    assert r["matched"] == 1  # only (1,5) 1-based survives distance >= 3
    assert _valid_rna_pairing("ACUGU", r["pairs"], min_distance=3)


# ------------------------------------------------------------------- idioms


def _enumerate(model, variables):
    class CB(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.rows = []

        def on_solution_callback(self):
            self.rows.append([self.value(v) for v in variables])

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    cb = CB()
    solver.solve(model, cb)
    return cb.rows


def test_if_then_idiom_truth_table():
    model = cp_model.CpModel()
    x = [model.new_bool_var(f"x{i}") for i in range(3)]
    z = model.new_bool_var("z")
    L = 2 * x[0] + 3 * x[1] + 5 * x[2]  # range 0..10
    add_if_then(model, L, 4, z, M=10)
    for a, b, c, zv in _enumerate(model, x + [z]):
        if 2 * a + 3 * b + 5 * c >= 4:
            assert zv == 1


def test_only_if_idiom_truth_table():
    model = cp_model.CpModel()
    x = [model.new_bool_var(f"x{i}") for i in range(3)]
    z = model.new_bool_var("z")
    L = 2 * x[0] + 3 * x[1] + 5 * x[2]
    add_only_if(model, L, 4, z, s=0)
    for a, b, c, zv in _enumerate(model, x + [z]):
        if zv == 1:
            assert 2 * a + 3 * b + 5 * c >= 4


def test_iff_indicator_counts_exactly():
    # if-and-only-if: number of solutions with z=1 equals the number of
    # assignments with L >= b, over all 2^3 assignments
    model = cp_model.CpModel()
    x = [model.new_bool_var(f"x{i}") for i in range(3)]
    z = model.new_bool_var("z")
    L = 2 * x[0] + 3 * x[1] + 5 * x[2]
    add_if_then(model, L, 4, z, M=10)
    add_only_if(model, L, 4, z, s=0)
    rows = _enumerate(model, x + [z])
    assert len(rows) == 8
    for a, b, c, zv in rows:
        assert (zv == 1) == (2 * a + 3 * b + 5 * c >= 4)


def test_not_equal_idiom():
    model = cp_model.CpModel()
    u = model.new_int_var(1, 4, "u")
    v = model.new_int_var(1, 4, "v")
    add_not_equal(model, u, v, n=4)
    rows = _enumerate(model, [u, v])
    assert len(rows) == 12  # 16 minus the 4 diagonal pairs
    assert all(a != b for a, b in rows)


def test_not_equal_indicator_binary():
    model = cp_model.CpModel()
    x = model.new_bool_var("x")
    y = model.new_bool_var("y")
    z = model.new_bool_var("z")
    add_not_equal_indicator(model, x, y, z)
    for xv, yv, zv in _enumerate(model, [x, y, z]):
        assert (zv == 1) == (xv != yv)


def test_or_and_xor_idioms():
    for builder, want in [(add_or, lambda t: t >= 1),
                          (add_xor, lambda t: t == 1)]:
        model = cp_model.CpModel()
        x = [model.new_bool_var(f"x{i}") for i in range(3)]
        L1 = 2 * x[0] + x[1]          # range 0..3
        L2 = 3 * x[1] + x[2]          # range 0..4
        builder(model, [(L1, 2, 0, 3), (L2, 3, 0, 4)])
        rows = _enumerate(model, x)
        # assignments by (L1 >= 2) + (L2 >= 3) count: t=0 twice,
        # t=1 four times, t=2 twice; OR keeps t>=1, XOR keeps t==1
        assert len(rows) == (6 if builder is add_or else 4)
        for a, b, c in rows:
            t = (2 * a + b >= 2) + (3 * b + c >= 3)
            assert want(t)


def test_implied_satisfaction_idiom():
    model = cp_model.CpModel()
    x = [model.new_bool_var(f"x{i}") for i in range(3)]
    L1 = 2 * x[0] + x[1]
    L2 = 3 * x[1] + x[2]
    add_implied_satisfaction(model, L1, 2, 0, 3, L2, 2, 0, 4)
    for a, b, c in _enumerate(model, x):
        if 2 * a + b >= 2:
            assert 3 * b + c >= 2
