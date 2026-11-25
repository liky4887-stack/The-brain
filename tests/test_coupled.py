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


def test_coupled_mip_primal_bound_sandwiches_dual():
    """The coupled cluster is ONE MIP: its incumbent is a feasible UB,
    the Lagrangian dual a proven LB, and LB <= UB must hold with both
    computed independently. With non-binding caps the coupled optimum
    equals the sum of the uncoupled optima."""
    from brain_core.rolling.coupled import (coupled_dual,
                                            solve_coupled_cluster,
                                            _plant_usage)
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
    solo_sum = sum(b.objective for b in solo)
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    caps = {k: 2.0 * v for k, v in mat_tot.items()}
    primal = solve_coupled_cluster([p.factory for p in ps], hs, days,
                                   cap, supplier_cap=caps,
                                   time_limit_s=60.0)
    assert primal["objective"] is not None
    # non-binding caps: coupled optimum == sum of uncoupled optima
    assert abs(primal["objective"] - solo_sum) <= \
        1e-4 * abs(solo_sum) + 1e-6
    dual = coupled_dual([p.factory for p in ps], hs, days, cap,
                        supplier_cap=caps, rounds=5, time_limit_s=30.0)
    # the sandwich: proven LB <= incumbent UB
    assert dual.lower_bound <= primal["objective"] + 1e-6


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


def test_repair_unchanged_when_nonbinding():
    """With caps at 2x uncoupled usage the uncoupled plans already fit:
    repair must cut nothing and recompute exactly the uncoupled
    objective under the base weights."""
    from brain_core.rolling.coupled import primal_repair, _plant_usage
    from brain_core.rolling.two_level import solve_buckets
    ps, hs, cap, days = _two_plants()
    solo = [solve_buckets(p.factory, hs, days, cap, time_limit_s=30.0)
            for p in ps]
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    caps = {k: 2.0 * v for k, v in mat_tot.items()}
    rep = primal_repair([p.factory for p in ps], hs, days, cap,
                        supplier_cap=caps,
                        qtys=[b.qty for b in solo])
    assert rep["problems"] == []
    assert rep["cuts"] == 0
    solo_sum = sum(b.objective for b in solo)
    assert abs(rep["objective"] - solo_sum) <= \
        1e-4 * abs(solo_sum) + 1e-6


def test_repair_feasible_when_binding():
    """With caps at half the uncoupled usage the uncoupled plans
    violate the pools; repair must return a plan that fits every cap,
    with a finite objective (a valid UB)."""
    from brain_core.rolling.coupled import primal_repair, _plant_usage
    from brain_core.rolling.two_level import solve_buckets
    ps, hs, cap, days = _two_plants()
    solo = [solve_buckets(p.factory, hs, days, cap, time_limit_s=30.0)
            for p in ps]
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    caps = {k: 0.5 * v for k, v in mat_tot.items()}
    rep = primal_repair([p.factory for p in ps], hs, days, cap,
                        supplier_cap=caps,
                        qtys=[b.qty for b in solo])
    assert rep["problems"] == []
    assert rep["objective"] is not None
    for k, v in rep["usage"]["supplier"].items():
        assert v <= caps[k] + 1e-6
    # a cut plan covers less demand -> pays lateness: UB >= solo_sum
    solo_sum = sum(b.objective for b in solo)
    assert rep["objective"] >= solo_sum - 1e-6


def test_dual_with_repair_gives_proven_gap():
    """Dual + repair sandwich on a binding instance: LB <= UB with
    both computed independently, and proven_gap is recorded."""
    from brain_core.rolling.coupled import coupled_dual, _plant_usage
    from brain_core.rolling.two_level import solve_buckets
    ps, hs, cap, days = _two_plants()
    solo = [solve_buckets(p.factory, hs, days, cap, time_limit_s=30.0)
            for p in ps]
    mat_tot = {}
    for p, b in zip(ps, solo):
        m_p, _ = _plant_usage(p.factory, b.qty)
        for k, v in m_p.items():
            mat_tot[k] = mat_tot.get(k, 0.0) + v
    caps = {k: 0.75 * v for k, v in mat_tot.items()}
    res = coupled_dual([p.factory for p in ps], hs, days, cap,
                       supplier_cap=caps, rounds=8, time_limit_s=30.0,
                       repair_every=2)
    assert res.lower_bound is not None
    assert res.upper_bound is not None
    assert res.lower_bound <= res.upper_bound + 1e-6
    assert res.proven_gap is not None and res.proven_gap >= -1e-9
