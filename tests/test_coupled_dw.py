"""Phase D Dantzig-Wolfe: the master LP attains the convexification
bound (== Lagrangian dual bound), the integer restricted master gives
a feasible UB, and LB <= UB must hold with both computed
independently."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))


def _two_plants():
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    ps = [generate_fnb_factory(FnbParams(seed=s, n_lines=3, n_skus=8,
                                         days=2, active_fraction=0.9,
                                         utilization=0.5,
                                         n_raw_materials=4,
                                         families=("DAIRY", "BAKERY")))
          for s in (11, 22)]
    return ps, ps[0].params.horizon_start, \
        ps[0].day_capacity_minutes, 7


def _uncoupled(ps, hs, cap, days):
    from brain_core.rolling.two_level import solve_buckets
    from brain_core.rolling.coupled import _plant_usage
    solo = [solve_buckets(p.factory, hs, days, cap, time_limit_s=30.0)
            for p in ps]
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    return solo, mat_tot


def test_cg_exact_on_nonbinding_caps():
    """Caps at 2x uncoupled usage: the coupled optimum equals the sum
    of the uncoupled optima, so the CG master LP must attain it
    exactly and the integer master must match."""
    from brain_core.rolling.coupled_dw import (column_generation,
                                               integer_master)
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    solo_sum = sum(b.objective for b in solo)
    caps = {k: 2.0 * v for k, v in mat_tot.items()}
    dw = column_generation([p.factory for p in ps], hs, days, cap,
                           supplier_cap=caps, max_iter=40,
                           time_limit_s=30.0)
    assert dw.converged, dw.status
    assert dw.lower_bound is not None
    assert abs(dw.lower_bound - solo_sum) <= 1e-4 * abs(solo_sum) + 1
    dw = integer_master(dw, [p.factory for p in ps], hs, days)
    assert dw.upper_bound is not None
    assert abs(dw.upper_bound - solo_sum) <= 1e-4 * abs(solo_sum) + 1
    assert dw.proven_gap is not None and dw.proven_gap <= 1e-4 + 1e-9


def test_cg_bound_dominates_subgradient_on_binding_caps():
    """Caps at 0.75x: the CG LP bound is the exact convexification
    bound, so it must be >= the subgradient walk's best LB (which only
    approaches it from below), and the integer master UB must sit
    above it. The selected plan must respect every cap."""
    from brain_core.rolling.coupled_dw import (column_generation,
                                               integer_master)
    from brain_core.rolling.coupled import coupled_dual, _plant_usage
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 0.75 * v for k, v in mat_tot.items()}
    dw = column_generation([p.factory for p in ps], hs, days, cap,
                           supplier_cap=caps, max_iter=40,
                           time_limit_s=30.0)
    assert dw.lower_bound is not None
    sub = coupled_dual([p.factory for p in ps], hs, days, cap,
                       supplier_cap=caps, rounds=8, time_limit_s=30.0)
    assert dw.lower_bound >= sub.lower_bound - \
        1e-4 * abs(sub.lower_bound) - 1
    dw = integer_master(dw, [p.factory for p in ps], hs, days)
    assert dw.upper_bound is not None, dw.problems
    assert dw.lower_bound <= dw.upper_bound + 1e-6
    # the selected plan must respect every cap, checked from records
    mat_tot2 = {}
    for f, q in zip([p.factory for p in ps], dw.selected_qtys):
        m_p, _ = _plant_usage(f, q)
        for k, v in m_p.items():
            mat_tot2[k] = mat_tot2.get(k, 0.0) + v
    for k, v in mat_tot2.items():
        if k in caps:   # pools without a cap row are unconstrained
            assert v <= caps[k] + 1e-6


def test_cg_farley_bounds_are_valid_each_iteration():
    """Every recorded Farley bound must sit at or below the final
    converged bound (validity), and the series must be recorded even
    if convergence is capped."""
    from brain_core.rolling.coupled_dw import column_generation
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 0.75 * v for k, v in mat_tot.items()}
    dw = column_generation([p.factory for p in ps], hs, days, cap,
                           supplier_cap=caps, max_iter=40,
                           time_limit_s=30.0)
    assert len(dw.lb_series) == dw.iterations
    assert len(dw.master_series) == dw.iterations
    for lb in dw.lb_series:
        assert lb <= dw.lower_bound + 1e-6


def test_diving_returns_feasible_selection_with_valid_ub():
    """Diving fixes columns until one per plant; when the final master
    needs no artificial columns the selection is a feasible coupled
    plan: cost >= certified LB (valid UB) and pool usage within caps.
    """
    from brain_core.rolling.coupled_dw import (column_generation,
                                               diving_select,
                                               _solve_master)
    from brain_core.rolling.coupled import _plant_usage
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    sup = {k: 0.75 * v for k, v in mat_tot.items()}
    lab = {}
    dw = column_generation([p.factory for p in ps], hs, days, cap,
                           supplier_cap=sup, labor_cap=lab,
                           max_iter=8, time_limit_s=10.0)
    pools, caps = dw._pools, dw._caps
    cost, qtys = diving_select(dw._colsets, pools, caps)
    if cost is None:
        return   # no artificial-free dive on this pool: nothing claimed
    assert dw.lower_bound is None or cost >= dw.lower_bound - 1e-6
    mat_tot, lab_tot = {}, {}
    for p, q in zip(ps, qtys):
        m_p, l_p = _plant_usage(p.factory, q)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
        for k, v in l_p.items():
            lab_tot[k] = lab_tot.get(k, 0.0) + v
    for (m, t), c in sup.items():
        assert mat_tot.get((m, t), 0.0) <= c + 1e-6
    for t, c in lab.items():
        assert lab_tot.get(t, 0.0) <= c + 1e-6


def test_allocate_solve_zero_share_is_a_hard_zero():
    """Regression (known failure f7ca2901b4bd): a pool that a plant's
    columns never use has share 0, NOT unlimited. Omitting the key let
    the union exceed the shared cap in every crossover replica."""
    from brain_core.rolling.coupled import _plant_usage
    from brain_core.rolling.coupled_dw import (_column, allocate_solve,
                                               _ub_plan_valid, DWResult)
    from brain_core.rolling.two_level import DEFAULT_WEIGHTS
    ps, hs, cap, days = _two_plants()
    solo, _ = _uncoupled(ps, hs, cap, days)
    m0, _l = _plant_usage(ps[0].factory, solo[0].qty)
    key = sorted(m0, key=repr)[0]
    empty = _column(ps[0].factory, hs, days, {}, None, DEFAULT_WEIGHTS)
    full1 = _column(ps[1].factory, hs, days, solo[1].qty, None, DEFAULT_WEIGHTS)
    # plant 0's only column uses nothing: its share of `key` is 0
    cost, qtys, probs = allocate_solve(
        [[empty], [full1]], [1.0, 1.0], [p.factory for p in ps], hs,
        days, cap, pools=[key])
    assert cost is not None, probs
    use0, _ = _plant_usage(ps[0].factory, qtys[0])
    assert use0.get(key, 0.0) <= 1e-6, use0.get(key)


def test_ub_gate_rejects_pool_violating_plan():
    from brain_core.rolling.coupled import _plant_usage
    from brain_core.rolling.coupled_dw import _ub_plan_valid, DWResult
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    key = sorted(mat_tot, key=repr)[0]
    res = DWResult(None)
    ok = _ub_plan_valid(res, [b.qty for b in solo],
                        [p.factory for p in ps], hs, days, cap,
                        [key], [mat_tot[key] * 0.5], "test")
    assert ok is False
    assert any("REJECTED" in p for p in res.problems)
    ok2 = _ub_plan_valid(DWResult(None), [b.qty for b in solo],
                         [p.factory for p in ps], hs, days, cap,
                         [key], [mat_tot[key] * 2.0], "test")
    assert ok2 is True
