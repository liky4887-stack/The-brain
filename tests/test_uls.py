"""Wolsey sec. 5.2 ULS dynamic program, validated against brute force.

Brute force enumerates all 2^n setup sets; by Proposition 5.1 an optimal
plan with a given setup set is forced (produce exactly the demand up to
the next production period), so the enumeration is exact for small n.
Example 5.1 from the book is locked with its printed answer.
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.lotsizing import plan_cost, solve_uls


def brute_force_uls(d, p, h, f):
    n = len(d)
    best = None
    for setup_set in itertools.product([0, 1], repeat=n):
        if any(d[t] > 0 for t in range(n)) and not any(setup_set):
            continue
        # Forced plan: each production period covers demand until the next.
        production = [0.0] * n
        periods = [t for t in range(n) if setup_set[t]]
        for idx, t in enumerate(periods):
            end = periods[idx + 1] if idx + 1 < len(periods) else n
            production[t] = sum(d[t:end])
        # Demand before the first production period is unsatisfiable.
        if periods and any(d[t] > 0 for t in range(periods[0])):
            continue
        stocks = [0.0] * n
        for t in range(n):
            stocks[t] = (stocks[t - 1] if t > 0 else 0.0) + production[t] - d[t]
        if any(s < -1e-9 for s in stocks):
            continue
        cost = sum(
            p[t] * production[t] + h[t] * stocks[t] + f[t] * setup_set[t]
            for t in range(n)
        )
        if best is None or cost < best:
            best = cost
    return best


def test_book_example_5_1():
    # Wolsey Example 5.1: d=(2,4,5,1), p=(3,3,3,3), h=(1,2,1,1),
    # f=(12,20,16,8) -> optimal value 69 with y=(6,0,6,0), x=(1,0,1,0).
    d = [2, 4, 5, 1]
    p = [3, 3, 3, 3]
    h = [1, 2, 1, 1]
    f = [12, 20, 16, 8]
    plan = solve_uls(d, p, h, f)
    assert plan.setups == [1, 0, 1, 0]
    assert plan.production == [6.0, 0.0, 6.0, 0.0]
    assert plan.stocks == [4.0, 0.0, 1.0, 0.0]
    assert plan_cost(plan, d, p, h, f) == 69


def test_dp_matches_brute_force_random():
    rng = random.Random(20261125)
    for trial in range(120):
        n = rng.randint(1, 8)
        d = [rng.randint(0, 9) for _ in range(n)]
        if all(v == 0 for v in d):
            d[0] = 1
        p = [rng.randint(1, 8) for _ in range(n)]
        h = [rng.randint(0, 5) for _ in range(n)]
        f = [rng.randint(0, 25) for _ in range(n)]
        plan = solve_uls(d, p, h, f)
        dp_cost = plan_cost(plan, d, p, h, f)  # also feasibility-checks
        assert dp_cost == brute_force_uls(d, p, h, f), (
            trial, d, p, h, f, plan)


def test_proposition_5_1_structure():
    # In the returned plan, production only happens with zero entering
    # stock, and produced quantities are exact demand runs.
    rng = random.Random(5)
    for _ in range(40):
        n = rng.randint(1, 8)
        d = [rng.randint(0, 9) for _ in range(n)]
        if all(v == 0 for v in d):
            d[0] = 1
        p = [rng.randint(1, 8) for _ in range(n)]
        h = [rng.randint(0, 5) for _ in range(n)]
        f = [rng.randint(0, 25) for _ in range(n)]
        plan = solve_uls(d, p, h, f)
        for t in range(n):
            entering = plan.stocks[t - 1] if t > 0 else 0.0
            assert entering * plan.production[t] == 0.0
            if plan.production[t] > 0:
                # produced amount = demand of an exact run t..t+k
                acc = 0.0
                found = False
                for k in range(t, n):
                    acc += d[k]
                    if abs(acc - plan.production[t]) < 1e-9:
                        found = True
                        break
                assert found, (t, plan.production[t], d)


def test_zero_setup_cost_produces_every_period():
    # With f = 0 and positive holding costs, producing on demand wins.
    d = [3, 1, 4, 1, 5]
    p = [1, 1, 1, 1, 1]
    h = [2, 2, 2, 2, 2]
    f = [0, 0, 0, 0, 0]
    plan = solve_uls(d, p, h, f)
    assert plan.production == [float(v) for v in d]
    assert all(s == 0.0 for s in plan.stocks)


def test_holding_cost_zero_produce_all_upfront():
    d = [2, 3, 4]
    p = [1, 1, 1]
    h = [0, 0, 0]
    f = [10, 10, 10]
    plan = solve_uls(d, p, h, f)
    assert plan.production[0] == 9.0
    assert plan.setups == [1, 0, 0]
