"""Independent coupled-plan validator: accepts a true feasible plan,
rejects broken ones (outside-review item 3)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))

from brain_core.synthetic import FnbParams, generate_fnb_factory
from brain_core.rolling.coupled import (build_coupled_mip,
                                        validate_coupled_plan)
from brain_core.solvers.highs_mip import solve_mip


def _tiny_cluster():
    ps = [generate_fnb_factory(FnbParams(seed=101 * (i + 1), n_lines=3,
                                         n_skus=10, days=4,
                                         active_fraction=0.9,
                                         utilization=0.5,
                                         n_raw_materials=4,
                                         families=("DAIRY", "BAKERY")))
          for i in range(2)]
    return ps, ps[0].params.horizon_start, ps[0].day_capacity_minutes


def _solve_tiny(supplier_cap, labor_cap):
    ps, hs, cap = _tiny_cluster()
    factories = [p.factory for p in ps]
    mip, meta = build_coupled_mip(factories, hs, 4, cap,
                                  supplier_cap, labor_cap)
    res = solve_mip(mip, time_limit_s=30.0, mip_rel_gap=0.0)
    assert res["x"] is not None
    qtys = []
    for mp, off in zip(meta["maps"], meta["offsets"]):
        qtys.append({k: float(res["x"][off + j])
                     for k, j in mp["x"].items() if res["x"][off + j] > 1e-6})
    return factories, qtys, hs, cap


def test_validates_a_true_feasible_plan():
    factories, qtys, hs, cap = _solve_tiny({}, {})
    problems, kpis = validate_coupled_plan(factories, qtys, hs, 4, cap)
    assert problems == [], problems[:5]


def test_rejects_capacity_violation():
    factories, qtys, hs, cap = _solve_tiny({}, {})
    (s, t, l), q = next(iter(qtys[0].items()))
    qtys[0][(s, t, l)] = q * 50  # blow the line-day capacity
    problems, _ = validate_coupled_plan(factories, qtys, hs, 4, cap)
    assert any("min > cap" in p for p in problems)


def test_rejects_shared_pool_violation():
    factories, qtys, hs, cap = _solve_tiny({}, {})
    from brain_core.rolling.coupled import _plant_usage
    mat, _ = _plant_usage(factories[0], qtys[0])
    assert mat, "expected material usage in the tiny plan"
    (r, t), use = next(iter(mat.items()))
    problems, _ = validate_coupled_plan(
        factories, qtys, hs, 4, cap, supplier_cap={(r, t): use / 2})
    assert any("supplier pool" in p for p in problems)


def test_rejects_labor_pool_violation():
    factories, qtys, hs, cap = _solve_tiny({}, {})
    problems, _ = validate_coupled_plan(
        factories, qtys, hs, 4, cap, labor_cap={0: 1.0})
    assert any("labor pool day 0" in p for p in problems)
