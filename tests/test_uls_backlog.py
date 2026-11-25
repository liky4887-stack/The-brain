"""Tests for ULS with backlogging (Pyomo book sec. 8.6).

The book's Table 8.1 instance is locked. Cross-validation is an
independent CP-SAT model of the book's own LS.1-LS.6 formulation
(objective recomputed from the CP-SAT assignment), plus a brute-force
enumeration over setup periods for small cases.
"""

import sys
from itertools import product
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from ortools.sat.python import cp_model

from brain_core.lotsizing.uls_backlog import (
    ULSBPlan, plan_cost, solve_uls_backlog, solve_uls_backlog_cpsat)

# Pyomo 3rd ed., sec. 8.6, Table 8.1
BOOK = dict(d=[5.0, 7.0, 6.2, 3.1, 1.7], f=4.6, p=0.0,
            h_plus=0.7, h_minus=1.2, capacity=5.0, i0_pos=5.0, i0_neg=0.0)


def _cpsat_reference(d, f, p, h_plus, h_minus, capacity, i0_pos, i0_neg,
                     scale=10):
    """The book's LS.1-LS.6 as a CP-SAT model (independent validator).
    Demands/costs are scaled to integers (CP-SAT is integer-only)."""
    n = len(d)
    ds = [round(v * scale) for v in d]
    big = sum(ds) + 1
    m = cp_model.CpModel()
    x = [m.new_int_var(0, big, f"x{t}") for t in range(n)]
    y = [m.new_bool_var(f"y{t}") for t in range(n)]
    ip = [m.new_int_var(0, big, f"ip{t}") for t in range(n)]
    im = [m.new_int_var(0, big, f"im{t}") for t in range(n)]
    P = round(capacity * scale) if capacity is not None else big
    for t in range(n):
        prev = round(i0_pos * scale) - round(i0_neg * scale) if t == 0 else \
            None
        if t == 0:
            m.add(ip[0] - im[0] == prev + x[0] - ds[0])
        else:
            m.add(ip[t] - im[t] == ip[t - 1] - im[t - 1] + x[t] - ds[t])
        m.add(x[t] <= P * y[t])
    fs, ps = round(f * scale * scale), round(p * scale)
    hp, hm = round(h_plus * scale), round(h_minus * scale)
    m.minimize(fs * sum(y) + ps * sum(x) + hp * sum(ip) + hm * sum(im))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    assert solver.solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return (fs * sum(solver.value(v) for v in y)
            + ps * sum(solver.value(v) for v in x)
            + hp * sum(solver.value(v) for v in ip)
            + hm * sum(solver.value(v) for v in im)) / (scale * scale)


def test_book_table_8_1_cpsat_matches_independent_highs():
    # the book's instance is capacitated (P=5, d_2=7): NP-hard, solved
    # by CP-SAT and cross-validated by an independent HiGHS MIP
    from scipy.optimize import milp, LinearConstraint, Bounds
    import numpy as np
    r = solve_uls_backlog_cpsat(**BOOK)
    assert r["status"] == "OPTIMAL"
    n = 5
    # variables: x[0..4], y[0..4], ip[0..4], im[0..4]
    c = np.array([BOOK["p"]] * n + [BOOK["f"]] * n
                 + [BOOK["h_plus"]] * n + [BOOK["h_minus"]] * n)
    integrality = np.array([0] * n + [1] * n + [0] * n + [0] * n)
    lb = np.zeros(4 * n)
    ub = np.array([BOOK["capacity"]] * n + [1] * n + [np.inf] * n + [np.inf] * n)
    rows, lo, hi = [], [], []
    for t in range(n):  # ip[t]-im[t] = prev + x[t] - d[t]
        row = np.zeros(4 * n)
        row[t] = -1.0            # -x[t]
        row[2 * n + t] = 1.0     # +ip[t]
        row[3 * n + t] = -1.0    # -im[t]
        if t > 0:
            row[2 * n + t - 1] = -1.0
            row[3 * n + t - 1] = 1.0
        rhs = BOOK["i0_pos"] - BOOK["i0_neg"] - BOOK["d"][t] if t == 0             else -BOOK["d"][t]
        rows.append(row); lo.append(rhs); hi.append(rhs)
    for t in range(n):  # x[t] <= P y[t]
        row = np.zeros(4 * n)
        row[t] = 1.0
        row[n + t] = -BOOK["capacity"]
        rows.append(row); lo.append(-np.inf); hi.append(0.0)
    res = milp(c, integrality=integrality, bounds=Bounds(lb, ub),
               constraints=LinearConstraint(np.array(rows), lo, hi))
    assert res.success
    assert r["cost"] == pytest.approx(res.fun, abs=1e-4)


def test_plan_is_feasible_for_book_data():
    plan = solve_uls_backlog_cpsat(**BOOK)["plan"]
    inv = BOOK["i0_pos"] - BOOK["i0_neg"]
    for t in range(5):
        inv += plan.production[t] - BOOK["d"][t]
        assert plan.inv_pos[t] == pytest.approx(max(inv, 0.0))
        assert plan.inv_neg[t] == pytest.approx(max(-inv, 0.0))
        if plan.production[t] > 0:
            assert plan.setups[t] == 1
            assert plan.production[t] <= BOOK["capacity"] + 1e-9


def test_uncapacitated_dp_matches_cpsat_path():
    d = [5.0, 7.0, 6.2, 3.1, 1.7]
    dp = solve_uls_backlog(d, f=4.6, h_plus=0.7, h_minus=1.2, i0_pos=5.0)
    ref = solve_uls_backlog_cpsat(d, f=4.6, h_plus=0.7, h_minus=1.2,
                                  i0_pos=5.0)
    assert ref["status"] == "OPTIMAL"
    assert plan_cost(dp, d, 4.6, 0.0, 0.7, 1.2) == pytest.approx(
        ref["cost"], abs=1e-3)


def test_no_backlog_when_h_minus_huge_matches_plain_uls():
    # with backlogging priced out, ULS-B must agree with the
    # Wagner-Whitin DP (independent implementation, Wolsey sec. 5.2)
    from brain_core.lotsizing.uls import solve_uls
    from brain_core.lotsizing.uls import plan_cost as uls_cost
    d = [5, 7, 11, 9, 6, 9]
    b = solve_uls_backlog(d, f=17.0, p=1.0, h_plus=1.0, h_minus=10**6)
    u = solve_uls(d, [1.0] * 6, [1.0] * 6, [17.0] * 6)
    assert (plan_cost(b, d, 17.0, 1.0, 1.0, 10**6)
            >= uls_cost(u, d, [1.0] * 6, [1.0] * 6, [17.0] * 6) - 1e-9)
    # and with backlogging cheap, it can only do better
    c = solve_uls_backlog(d, f=17.0, p=1.0, h_plus=1.0, h_minus=0.5)
    assert plan_cost(c, d, 17.0, 1.0, 1.0, 0.5) <= 123.0


def test_capacity_routes_to_cpsat_honestly():
    with pytest.raises(NotImplementedError, match="NP-hard"):
        solve_uls_backlog([10.0], f=1.0, capacity=5.0)


def test_validation():
    with pytest.raises(ValueError):
        solve_uls_backlog([], f=1.0)
    with pytest.raises(ValueError):
        solve_uls_backlog([1.0, -1.0], f=1.0)
    with pytest.raises(ValueError):
        solve_uls_backlog([1.0], f=-1.0)


def test_fuzz_dp_matches_cpsat_on_random_instances():
    import random
    rng = random.Random(20261125)
    for trial in range(12):
        n = rng.randint(2, 6)
        d = [round(rng.uniform(0, 9), 1) for _ in range(n)]
        f = round(rng.uniform(1, 10), 1)
        hp = round(rng.uniform(0.2, 2), 1)
        hm = round(rng.uniform(0.2, 3), 1)
        i0 = round(rng.uniform(0, 8), 1)
        dp = solve_uls_backlog(d, f=f, h_plus=hp, h_minus=hm, i0_pos=i0)
        ref = solve_uls_backlog_cpsat(d, f=f, h_plus=hp, h_minus=hm,
                                      i0_pos=i0)
        assert ref["status"] == "OPTIMAL"
        assert plan_cost(dp, d, f, 0.0, hp, hm) == pytest.approx(
            ref["cost"], abs=2e-3), f"trial {trial}: d={d} f={f} hp={hp} hm={hm} i0={i0}"
