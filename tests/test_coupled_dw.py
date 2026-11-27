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


def test_master_pool_usage_matches_validator_on_random_plans():
    """Consistency (review 15): for random (not optimal, not even
    coverage-feasible) plans, the usage the master uses per pool
    (column mat/lab) must agree with the independent validator: a cap
    1% above the master usage is never flagged, a cap 1% below is
    always flagged, for every supplier and labor pool."""
    import random
    from brain_core.rolling.two_level import (_sku_data,
                                              DEFAULT_WEIGHTS)
    from brain_core.rolling.coupled import validate_coupled_plan
    from brain_core.rolling.coupled_dw import _column
    ps, hs, cap, days = _two_plants()
    fs = [p.factory for p in ps]
    skus = [_sku_data(f) for f in fs]
    for seed in range(6):
        rng = random.Random(seed)
        qtys = []
        for sk in skus:
            q = {}
            for s, (rate, lines, _x) in sk.items():
                if rng.random() < 0.5:
                    t = rng.randrange(days)
                    q[(s, t, rng.choice(lines))] = rng.uniform(
                        1.0, 0.2 * cap * rate)
            qtys.append(q)
        use = {}
        for f, q in zip(fs, qtys):
            c = _column(f, hs, days, q, None, DEFAULT_WEIGHTS)
            for k, v in list(c["mat"].items()) + list(c["lab"].items()):
                use[k] = use.get(k, 0.0) + v
        assert use
        big = {k: v for k, v in use.items() if v > 20.0}
        assert big

        def run(scale):
            sup = {k: scale * v for k, v in big.items()
                   if isinstance(k, tuple)}
            lab = {k: scale * v for k, v in big.items()
                   if not isinstance(k, tuple)}
            probs, _k = validate_coupled_plan(
                fs, qtys, hs, days, cap, supplier_cap=sup,
                labor_cap=lab)
            return [p for p in probs if "pool" in p]

        assert run(1.01) == [], run(1.01)
        flagged = run(0.99)
        assert len(flagged) == len(big), (len(flagged), len(big))


def test_master_lp_retries_after_numerical_failure_and_records_it(
        monkeypatch):
    """Measured on 0.9/0.9 n=2 s0: master LP status 4 (model_status
    Unknown) at CG iteration 182. The master must retry with another
    HiGHS algorithm and say so in the returned status."""
    import scipy.optimize as so
    from brain_core.rolling.coupled_dw import _solve_master
    real = so.linprog
    calls = []

    def flaky(*a, **kw):
        calls.append(kw.get("method"))
        if len(calls) == 1:
            class R:
                status = 4
                message = "numerical difficulties (mock)"
            return R()
        return real(*a, **kw)

    monkeypatch.setattr(so, "linprog", flaky)
    colsets = [[{"cost": 5.0, "mat": {("m", 0): 1.0}, "lab": {},
                 "qty": {}}]]
    obj, u, sigma, art, st, lam = _solve_master(colsets, [("m", 0)],
                                                [10.0])
    assert obj == 5.0 and art == 0.0
    assert calls[0] == "highs" and calls[1] == "highs-ipm"
    assert st.startswith("optimal after retry") and "status 4" in st


def test_master_lp_reports_failure_when_all_methods_fail(monkeypatch):
    import scipy.optimize as so
    from brain_core.rolling.coupled_dw import _solve_master

    class R:
        status = 4
        message = "mock"
    monkeypatch.setattr(so, "linprog", lambda *a, **k: R())
    obj, *_rest, st, lam = _solve_master(
        [[{"cost": 1.0, "mat": {}, "lab": {}, "qty": {}}]], [("m", 0)],
        [1.0])
    assert obj is None and "retries" in st


def test_master_lp_tolerance_keeps_master_monotone_and_converges():
    """Fail-before: with the HiGHS default 1e-7 feasibility tolerance on the
    scaled master (absolute noise ~1e-7 x largest column cost) the 0.75x
    binding-caps instance (cost ~4.5e7) did not converge in 150 iterations
    (master went UP by up to 1.25), master 44,978,347.26. With 1e-10 it
    converges in 20 iterations at 44,978,346.733, master never rises."""
    import brain_core.rolling.coupled_dw as D
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 0.75 * v for k, v in mat_tot.items()}
    fs = [p.factory for p in ps]
    assert D.MASTER_LP_TOL <= 1e-9      # the default itself is under test
    d = D.column_generation(fs, hs, days, cap, supplier_cap=caps,
                            max_iter=60, time_limit_s=30.0)
    m = d.master_series
    assert d.converged, d.status
    assert all(m[i] <= m[i - 1] + 1e-9 * abs(m[i - 1])
               for i in range(1, len(m)))
    assert abs(d.lower_bound - 44978346.733) < 0.05


def test_tol_rel_floor_is_relative_and_default_is_unchanged():
    """tol_rel raises the pricing tolerance to tol_rel x |master| (original
    cost units); default 0 keeps the absolute tol. Measured on real seed
    200006 (cost 1.5e8): absolute 1e-6 stalled at 247 it with bound = master
    to 1e-12; tol_rel 1e-10 converged in 148 it, same value to 2e-14."""
    import pytest
    from brain_core.rolling.coupled_dw import column_generation
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 0.75 * v for k, v in mat_tot.items()}
    fs = [p.factory for p in ps]
    a = column_generation(fs, hs, days, cap, supplier_cap=caps,
                          max_iter=60, time_limit_s=30.0)
    b = column_generation(fs, hs, days, cap, supplier_cap=caps,
                          max_iter=60, time_limit_s=30.0, tol_rel=1e-6)
    assert a.converged and b.converged
    assert b.iterations <= a.iterations
    assert b.lower_bound == pytest.approx(a.lower_bound, rel=1e-5)
