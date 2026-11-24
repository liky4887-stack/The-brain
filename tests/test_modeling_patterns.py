"""Brute-force verification of the Williams modeling patterns.

Every pattern is checked by enumerating small variable domains and confirming
the generated constraints accept exactly the intended value combinations -
the same standard the engine core is held to (no claim without a test).
"""

import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))

from brain_core.modeling import (  # noqa: E402
    at_least_k, at_most_k, disaggregate, disjunction, fixed_charge,
    indicator_link, minimax, soft_constraint, symmetry_break_order,
)

BINARY = [0.0, 1.0]


def enum(domains):
    names = list(domains)
    for combo in itertools.product(*(domains[n] for n in names)):
        yield dict(zip(names, combo))


class TestIndicatorLink:
    def test_semantics(self):
        c = indicator_link("x", "d", upper_x=5.0)
        for v in enum({"x": [0.0, 1.0, 3.0, 5.0], "d": BINARY}):
            implication_holds = v["x"] == 0.0 or v["d"] == 1.0
            assert c.holds(v) == implication_holds, v

    def test_requires_realistic_m(self):
        with pytest.raises(ValueError):
            indicator_link("x", "d", upper_x=0.0)

    def test_too_small_m_rejects_valid_states(self):
        # an M below a reachable x wrongly forbids x itself: why M must be real
        c = indicator_link("x", "d", upper_x=2.0)
        assert not c.holds({"x": 3.0, "d": 1.0})


class TestFixedCharge:
    def test_zero_output_carries_no_setup(self):
        cons, obj = fixed_charge("x", "d", 10.0, unit_cost=2.0, setup_cost=7.0)
        # minimizing: x=0,d=0 feasible and cheaper than x=0,d=1
        assert all(c.holds({"x": 0.0, "d": 0.0}) for c in cons)
        cost_idle = obj.coeffs["x"] * 0 + obj.coeffs["d"] * 0
        cost_slack = obj.coeffs["d"] * 1
        assert cost_idle < cost_slack
        # producing requires d=1 and charges both terms
        assert all(c.holds({"x": 4.0, "d": 1.0}) for c in cons)
        assert not all(c.holds({"x": 4.0, "d": 0.0}) for c in cons)


class TestSoftConstraint:
    def test_le_violation_priced_not_forbidden(self):
        cons, obj, dev = soft_constraint({"x": 1.0}, "<=", 5.0, penalty_over=100.0)
        assert cons[0].holds({"x": 5.0, dev[0]: 0.0})
        assert cons[0].holds({"x": 8.0, dev[0]: 3.0})
        assert not cons[0].holds({"x": 8.0, dev[0]: 2.0})
        assert obj.coeffs[dev[0]] == 100.0

    def test_eq_both_directions(self):
        cons, obj, dev = soft_constraint({"x": 1.0}, "==", 5.0,
                                         penalty_over=10.0, penalty_under=20.0)
        u, v = dev  # under, over (Williams 3.11: a.x + u - v = b)
        assert cons[0].holds({"x": 7.0, u: 0.0, v: 2.0})
        assert cons[0].holds({"x": 3.0, u: 2.0, v: 0.0})
        assert not cons[0].holds({"x": 7.0, u: 0.0, v: 0.0})
        assert obj.coeffs[v] == 10.0 and obj.coeffs[u] == 20.0


class TestCardinality:
    def test_at_least_k(self):
        c = at_least_k(["a", "b", "c"], 2)
        for v in enum({"a": BINARY, "b": BINARY, "c": BINARY}):
            assert c.holds(v) == (v["a"] + v["b"] + v["c"] >= 2)

    def test_at_most_k(self):
        c = at_most_k(["a", "b", "c"], 1)
        for v in enum({"a": BINARY, "b": BINARY, "c": BINARY}):
            assert c.holds(v) == (v["a"] + v["b"] + v["c"] <= 1)

    def test_bad_k_rejected(self):
        with pytest.raises(ValueError):
            at_least_k(["a"], 2)
        with pytest.raises(ValueError):
            at_most_k(["a"], 1)


class TestDisjunction:
    def test_exactly_the_union_is_feasible(self):
        # (x <= 2) OR (x >= 4), x in 0..5
        cons = disjunction(
            [({"x": 1.0}, "<=", 2.0, 5.0), ({"x": 1.0}, ">=", 4.0, 5.0)],
            ["d1", "d2"])
        # for each x, SOME delta setting works iff x is in the union
        for x in range(6):
            feasible = any(
                all(c.holds({"x": float(x), "d1": d1, "d2": d2}) for c in cons)
                for d1, d2 in itertools.product(BINARY, repeat=2))
            assert feasible == (x <= 2 or x >= 4), x

    def test_single_alternative_rejected(self):
        with pytest.raises(ValueError):
            disjunction([({"x": 1.0}, "<=", 2.0, 5.0)], ["d1"])


class TestMinimax:
    def test_z_bounds_every_expression(self):
        cons = minimax([{"x": 1.0}, {"y": 2.0}], z="z")
        for v in enum({"x": [0.0, 1.0, 2.0], "y": [0.0, 1.0], "z": [0.0, 1.0, 2.0, 3.0]}):
            ok = all(c.holds(v) for c in cons)
            assert ok == (v["z"] >= max(v["x"], 2 * v["y"])), v


class TestDisaggregate:
    def test_same_integer_feasible_set(self):
        tight = disaggregate(["a", "b", "c"], "d")
        for v in enum({"a": BINARY, "b": BINARY, "c": BINARY, "d": BINARY}):
            n = v["a"] + v["b"] + v["c"]
            aggregated_ok = n - 3 * v["d"] <= 0
            tight_ok = all(c.holds(v) for c in tight)
            assert tight_ok == aggregated_ok, v

    def test_strictly_tighter_relaxation(self):
        # fractional point allowed by the aggregate form, killed by disaggregation
        v = {"a": 1.0, "b": 0.5, "c": 0.5, "d": 0.7}
        assert v["a"] + v["b"] + v["c"] - 3 * v["d"] <= 0
        assert not all(c.holds(v) for c in disaggregate(["a", "b", "c"], "d"))


class TestSymmetryBreak:
    def test_ordering_chain(self):
        cons = symmetry_break_order(["v1", "v2", "v3"])
        assert all(c.holds({"v1": 3.0, "v2": 2.0, "v3": 2.0}) for c in cons)
        assert not all(c.holds({"v1": 1.0, "v2": 2.0, "v3": 0.0}) for c in cons)

    def test_kills_symmetric_duplicates(self):
        # assignments of 2 identical machines to loads 1 and 2: 4 symmetric
        # assignments collapse to the 3 ordered ones
        cons = symmetry_break_order(["m1", "m2"])
        survivors = [v for v in enum({"m1": [1.0, 2.0], "m2": [1.0, 2.0]})
                     if all(c.holds(v) for c in cons)]
        assert len(survivors) == 3
