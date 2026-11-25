"""Phase D coupled-cluster dual: the Lagrangian bound must be valid
(<= the coupled optimum) whenever computable, and exact at u = 0 when
the linking constraints are non-binding."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "packages" / "brain-core"))


def test_dual_bound_valid_and_tight_when_nonbinding():
    from brain_core.rolling.coupled import coupled_dual
    from brain_core.rolling.two_level import solve_buckets
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    ps = [generate_fnb_factory(FnbParams(seed=s, n_lines=3, n_skus=8,
                                         days=2, active_fraction=0.9,
                                         utilization=0.5,
                                         n_raw_materials=4,
                                         families=("DAIRY", "BAKERY")))
          for s in (11, 22)]
    hs = ps[0].params.horizon_start
    cap = ps[0].day_capacity_minutes
    days = 7
    # uncoupled optima (each plant alone)
    solo = [solve_buckets(p.factory, hs, days, cap, time_limit_s=30.0)
            for p in ps]
    solo_sum = sum(b.objective for b in solo)
    # measure uncoupled usage of every raw material per day
    from brain_core.rolling.coupled import _plant_usage
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    # NON-BINDING caps: 2x uncoupled usage -> coupled optimum == solo_sum
    caps = {k: 2.0 * v for k, v in mat_tot.items()}
    res = coupled_dual([p.factory for p in ps], hs, days, cap,
                       supplier_cap=caps, rounds=10, time_limit_s=30.0)
    assert res.lower_bound is not None
    # validity: LB must never exceed the true coupled optimum
    # (== solo_sum here) beyond solver tolerance
    assert res.lower_bound <= solo_sum * (1 + 1e-6) + 1e-6
    # and at u=0 the dual equals the uncoupled optimum exactly
    assert abs(res.lb_series[0] - solo_sum) <= 1e-4 * abs(solo_sum) + 1e-6
    assert res.rounds_run > 0


def test_dual_bound_holds_when_binding():
    from brain_core.rolling.coupled import coupled_dual, _plant_usage
    from brain_core.rolling.two_level import solve_buckets
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    ps = [generate_fnb_factory(FnbParams(seed=s, n_lines=3, n_skus=8,
                                         days=2, active_fraction=0.9,
                                         utilization=0.5,
                                         n_raw_materials=4,
                                         families=("DAIRY", "BAKERY")))
          for s in (11, 22)]
    hs = ps[0].params.horizon_start
    cap = ps[0].day_capacity_minutes
    days = 7
    solo = [solve_buckets(p.factory, hs, days, cap, time_limit_s=30.0)
            for p in ps]
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    # BINDING caps: half the uncoupled usage -> the uncoupled plans are
    # infeasible for the coupled problem; the dual must still return a
    # finite, positive, recorded bound walk (validity vs the unknown
    # coupled optimum cannot be asserted without solving it; what must
    # hold is that some multiplier pushes usage down)
    caps = {k: 0.5 * v for k, v in mat_tot.items()}
    res = coupled_dual([p.factory for p in ps], hs, days, cap,
                       supplier_cap=caps, rounds=10, time_limit_s=30.0)
    assert res.lower_bound is not None and res.lower_bound > 0
    assert any(v > 0 for v in res.multipliers["supplier"].values())
