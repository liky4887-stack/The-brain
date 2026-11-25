"""Ahuja-Magnanti-Orlin network flows, validated independently.

Max flow: the returned value must equal the brute-force minimum cut
(Theorem 6.3), the flow must be feasible (capacity + mass balance), and
integer capacities must give integer flows (Theorem 6.5).

Min cost flow: cross-validated against the repo's exact-rational simplex
solver on the LP formulation of the same random instances - two
independent implementations must agree on the optimal cost. Returned
flows are checked for feasibility.
"""

import itertools
import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lp import LPStatus, solve_lp
from brain_core.network import FlowError, max_flow, min_cost_flow


def brute_min_cut(n, arcs, s, t):
    cap = [[0] * n for _ in range(n)]
    for (u, v, c) in arcs:
        cap[u][v] += c
    best = None
    for mask in range(1 << n):
        if not (mask >> s) & 1 or (mask >> t) & 1:
            continue
        cut = sum(cap[u][v] for u in range(n) for v in range(n)
                  if (mask >> u) & 1 and not (mask >> v) & 1)
        if best is None or cut < best:
            best = cut
    return best


def check_flow_feasible(n, arcs, flows, s, t, value):
    cap = {}
    for (u, v, c) in arcs:
        cap[(u, v)] = cap.get((u, v), 0) + c
    for (u, v), f in flows.items():
        assert 0 < f <= cap.get((u, v), 0), (u, v, f)
    for i in range(n):
        net = (sum(f for (u, v), f in flows.items() if v == i)
               - sum(f for (u, v), f in flows.items() if u == i))
        if i == s:
            assert net == -value
        elif i == t:
            assert net == value
        else:
            assert net == 0


def test_max_flow_equals_min_cut_random():
    rng = random.Random(6)
    for trial in range(100):
        n = rng.randint(2, 8)
        arcs = []
        for u in range(n):
            for v in range(n):
                if u != v and rng.random() < 0.35:
                    arcs.append((u, v, rng.randint(0, 9)))
        s, t = 0, n - 1
        value, flows = max_flow(n, arcs, s, t)
        assert value == brute_min_cut(n, arcs, s, t), (trial, arcs, value)
        assert all(isinstance(f, int) for f in flows.values())
        check_flow_feasible(n, arcs, flows, s, t, value)


def test_max_flow_book_style_example():
    # s=0 -> 1,2; 1->2,3(t); 2->3(t). Bottleneck cut value 3+2 = 5...:
    arcs = [(0, 1, 3), (0, 2, 2), (1, 2, 1), (1, 3, 4), (2, 3, 2)]
    value, flows = max_flow(4, arcs, 0, 3)
    assert value == 5
    assert value == brute_min_cut(4, arcs, 0, 3)


def mcf_as_lp(n, arcs, balance):
    """Min cost flow as an LP for the simplex solver; variable per arc."""
    m = len(arcs)
    c = [w for (_, _, _, w) in arcs]
    A, b, senses = [], [], []
    for i in range(n):
        row = [0] * m
        for k, (u, v, _, _) in enumerate(arcs):
            if u == i:
                row[k] = -1
            elif v == i:
                row[k] = 1
        A.append(row)
        b.append(-balance[i])  # inflow - outflow = -b(i)
        senses.append("==")
    for k, (u, v, cap, _) in enumerate(arcs):
        row = [0] * m
        row[k] = 1
        A.append(row)
        b.append(cap)
        senses.append("<=")
    return c, A, b, senses


def test_min_cost_flow_matches_simplex_lp():
    rng = random.Random(9)
    n_lp_optimal = 0
    for trial in range(80):
        n = rng.randint(2, 6)
        arcs = []
        for u in range(n):
            for v in range(n):
                if u != v and rng.random() < 0.4:
                    arcs.append((u, v, rng.randint(1, 9), rng.randint(0, 9)))  # SSP scope: nonnegative costs
        if not arcs:
            continue
        # random balances summing to zero
        balance = [0] * n
        for i in range(n // 2):
            balance[i] = rng.randint(0, 6)
        total = sum(balance)
        for i in range(n // 2, n - 1):
            take = rng.randint(0, total)
            balance[i] = -take
            total -= take
        balance[n - 1] = -total
        c, A, b, senses = mcf_as_lp(n, arcs, balance)
        lp = solve_lp(c, A, b, senses)
        try:
            cost, flows = min_cost_flow(n, arcs, balance)
        except FlowError:
            assert lp.status == LPStatus.INFEASIBLE, (trial, arcs, balance)
            continue
        # flow feasibility: capacity and balance
        capd = {}
        for (u, v, capk, _) in arcs:
            capd[(u, v)] = capd.get((u, v), 0) + capk
        for (u, v), f in flows.items():
            assert 0 < f <= capd[(u, v)]
        for i in range(n):
            net = (sum(f for (u, v), f in flows.items() if v == i)
                   - sum(f for (u, v), f in flows.items() if u == i))
            assert net == -balance[i], (trial, i, net, balance[i])
        if lp.status != LPStatus.OPTIMAL:
            # LP infeasible while SSP found a flow should never happen;
            # LP unbounded cannot happen (capacities bounded).
            raise AssertionError((trial, lp.status, arcs, balance))
        n_lp_optimal += 1
        assert Fraction(cost) == lp.objective, (trial, arcs, balance, cost, lp.objective)
    assert n_lp_optimal > 20  # many random instances are infeasible; the check is that a solid mass matched


def test_min_cost_flow_rejects_negative_costs():
    # Outside SSP scope (ch.9 nonnegativity assumption); rejected loudly.
    with pytest.raises(ValueError):
        min_cost_flow(2, [(0, 1, 5, -1)], [1, -1])


def test_min_cost_flow_unreachable_demand():
    # Node 2 demands 5 but has no incoming arcs at all.
    arcs = [(0, 1, 5, 1)]
    with pytest.raises(FlowError):
        min_cost_flow(3, arcs, [5, 0, -5])


def test_min_cost_flow_known_answer():
    # One supply, one demand, two routes: direct cost 9 cap 3, indirect
    # cost 2 cap 2. Demand 3 -> 2 indirect + 1 direct, cost 13.
    arcs = [(0, 1, 3, 9), (0, 2, 2, 1), (2, 1, 2, 1)]
    cost, flows = min_cost_flow(3, arcs, [3, -3, 0])
    assert cost == 13
    assert flows[(0, 1)] == 1 and flows[(0, 2)] == 2 and flows[(2, 1)] == 2
