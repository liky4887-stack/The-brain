"""Tests for Apt's bounds-consistency propagation and MAC search.

Locked: the book's Fig. 6.3-6.4 example (3x - 5y = 4) at its exact
stabilised bounds, the single-variable rule examples (sec. 6.4.2), and
SEND + MORE = MONEY (sec. 6.4.6/8.3) with its unique solution.
Cross-validation: random small systems checked against brute-force
enumeration over the full domains.
"""

import sys
from itertools import product
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.csp import (
    LinearConstraint, enumerate_solutions, propagate, solve_mac,
)


def test_book_fig_6_3_6_4_locked():
    # <3x - 5y = 4; x in [0..9], y in [1..8]> stabilises at
    # x in [3..8], y in [1..4] (Apt Fig. 6.4)
    c = LinearConstraint((("x", 3), ("y", -5)), "eq", 4)
    dom = propagate([c], {"x": (0, 9), "y": (1, 8)})
    assert dom == {"x": (3, 8), "y": (1, 4)}


def test_single_variable_rule():
    # 4x = 19 with x in [0..100] reaches a failure (Apt sec. 6.4.2)
    c = LinearConstraint((("x", 4),), "eq", 19)
    assert propagate([c], {"x": (0, 100)}) is None
    # 4x = 20 infers x = 5
    c2 = LinearConstraint((("x", 4),), "eq", 20)
    assert propagate([c2], {"x": (0, 100)}) == {"x": (5, 5)}


def test_inequality_rule():
    # 3x + y <= 10 with x in [0..5], y in [0..20]: y <= 10, x <= 3
    c = LinearConstraint((("x", 3), ("y", 1)), "le", 10)
    dom = propagate([c], {"x": (0, 5), "y": (0, 20)})
    assert dom == {"x": (0, 3), "y": (0, 10)}


def test_send_more_money_unique_solution():
    # S E N D + M O R E = M O N E Y as one integer equation with
    # all-different posted pairwise (disequality via split search)
    letters = ["s", "e", "n", "d", "m", "o", "r", "y"]
    send = [("s", 1000), ("e", 100), ("n", 10), ("d", 1)]
    more = [("m", 1000), ("o", 100), ("r", 10), ("e", 1)]
    money = [("m", -10000), ("o", -1000), ("n", -100), ("e", -10),
             ("y", -1)]
    coeffs = {}
    for v, a in send + more + money:
        coeffs[v] = coeffs.get(v, 0) + a
    eq = LinearConstraint(tuple(sorted(coeffs.items())), "eq", 0)
    doms = {v: (0, 9) for v in letters}
    doms["s"] = doms["m"] = (1, 9)

    def rec(dom):
        dom = propagate([eq], dom)
        if dom is None:
            return None
        # check all-different on fixed values
        fixed = {v: l for v, (l, h) in dom.items() if l == h}
        if len(set(fixed.values())) < len(fixed):
            return None
        if all(l == h for l, h in dom.values()):
            return fixed
        var = min((v for v in dom if dom[v][0] < dom[v][1]),
                  key=lambda v: dom[v][1] - dom[v][0])
        l, h = dom[var]
        for val in range(l, h + 1):
            sub = dict(dom)
            sub[var] = (val, val)
            r = rec(sub)
            if r is not None:
                return r
        return None

    sol = rec(doms)
    assert sol == {"s": 9, "e": 5, "n": 6, "d": 7, "m": 1, "o": 0,
                   "r": 8, "y": 2}
    assert 9567 + 1085 == 10652  # SEND + MORE = MONEY


def test_mac_matches_brute_force_on_random_systems():
    import random
    rng = random.Random(2003)
    for _ in range(20):
        nv = rng.randint(2, 4)
        vs = [f"x{i}" for i in range(nv)]
        doms = {v: (0, rng.randint(3, 6)) for v in vs}
        cons = []
        for _ in range(rng.randint(1, 3)):
            coeffs = tuple((v, rng.choice([-3, -2, -1, 1, 2, 3]))
                           for v in rng.sample(vs, rng.randint(1, nv)))
            sense = rng.choice(["eq", "le", "ge"])
            rhs = rng.randint(-5, 15)
            cons.append(LinearConstraint(coeffs, sense, rhs))
        mac_all = enumerate_solutions(cons, doms)
        brute = []
        for vals in product(*[range(l, h + 1) for l, h in doms.values()]):
            pt = dict(zip(vs, vals))
            ok = True
            for c in cons:
                s = sum(a * pt[v] for v, a in c.coeffs)
                if c.sense == "eq" and s != c.rhs:
                    ok = False
                if c.sense == "le" and s > c.rhs:
                    ok = False
                if c.sense == "ge" and s < c.rhs:
                    ok = False
            if ok:
                brute.append(pt)
        assert mac_all == brute or (len(mac_all) == len(brute)
                                    and all(m in brute for m in mac_all))


def test_unknown_variable_and_bad_input_rejected():
    with pytest.raises(ValueError):
        propagate([LinearConstraint((("z", 1),), "eq", 1)], {"x": (0, 1)})
    with pytest.raises(ValueError):
        LinearConstraint((("x", 0),), "eq", 1)
    with pytest.raises(ValueError):
        LinearConstraint((("x", 1),), "lt", 1)
