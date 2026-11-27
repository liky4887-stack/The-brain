"""Pool-level lower bound as an anomaly rule. Fail-before: a record that
claims less lateness than the pools allow used to pass."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from brain_core.guards.anomaly import check_record  # noqa: E402
from brain_core.guards.physical_bound import lateness_check, lateness_lower_bound  # noqa: E402
from brain_core.rolling import two_level as T  # noqa: E402
from brain_core.rolling.coupled import (build_coupled_mip,  # noqa: E402
                                        validate_coupled_plan)
from brain_core.solvers.highs_mip import solve_mip  # noqa: E402
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from coupled_comparison import qty_from_mip_x  # noqa: E402


def _case():
    p = generate_fnb_factory(FnbParams(
        seed=101, n_lines=3, n_skus=6, days=3, active_fraction=1.0,
        utilization=0.6, n_raw_materials=3, families=("DAIRY", "BAKERY")))
    f, hs, cap = p.factory, p.params.horizon_start, p.day_capacity_minutes
    lab = {t: 0.5 * cap for t in range(3)}
    mip, meta = build_coupled_mip([f], hs, 3, cap, {}, lab)
    r = solve_mip(mip, time_limit_s=30)
    q = qty_from_mip_x(r["x"], meta["maps"], meta["offsets"])
    _, k = validate_coupled_plan([f], q, hs, 3, cap, labor_cap=lab)
    cap_eff = cap * (1 - T.DEFAULT_CHG_ALLOWANCE)
    lb = lateness_lower_bound([f], hs, 3, cap_eff, labor_cap=lab, inv0s=[None])
    gen = lambda claim, tol=None: lateness_check(  # noqa: E731
        [f], hs, 3, cap_eff, {}, lab, [None], claim, tol)
    return k["backlog_unit_days"], lb, gen


def _rec(lt):
    return {"status": "optimal", "incumbent": 1.0, "nodes": 1,
            "lateness_check": lt}


def _rules(rec):
    return [x.rule for x in check_record(rec)]


def test_optimum_is_at_or_above_bound_and_passes():
    bud, lb, gen = _case()
    assert lb > 0 and bud >= lb - 1e-6 * lb
    r = _rules(_rec(gen(bud)))
    assert "below_physical_bound" not in r and "bound_not_applicable" not in r


def test_equal_within_noise_passes_and_tolerance_is_recorded():
    bud, lb, gen = _case()
    for claim in (lb, lb * (1 - 1e-8), lb * (1 - 5e-7)):
        r = _rules(_rec(gen(claim)))
        assert "below_physical_bound" not in r and \
            "bound_not_applicable" not in r, claim
    f = [x for x in check_record(_rec(gen(lb * (1 - 1e-4))))
         if x.rule == "below_physical_bound"]
    assert f and "1e-06" in f[0].detail


def test_claim_below_the_bound_is_refused():
    bud, lb, gen = _case()
    for claim in (0.0, 0.5 * lb, lb * (1 - 1e-3)):
        assert "below_physical_bound" in _rules(_rec(gen(claim))), claim


def test_runner_written_flag_or_edited_bound_is_not_judged():
    """Fail-before: a runner-written inventory_handled=True (no function
    run) was trusted. Now only a record with the function's provenance is
    judged; forged or edited records are bound_not_applicable."""
    bud, lb, gen = _case()
    forged = {"backlog_unit_days": 0.0, "lower_bound": lb,
              "inventory_handled": True}
    r = _rules(_rec(forged))
    assert "bound_not_applicable" in r and "below_physical_bound" not in r
    edited = dict(gen(bud), lower_bound=lb * 10)      # bound edited later
    assert "bound_not_applicable" in _rules(_rec(edited))
    other_inv = dict(gen(bud), inv0_digest="deadbeef")
    assert "bound_not_applicable" in _rules(_rec(other_inv))
    wrong_tol = dict(gen(bud), rel_tol=0.5)
    assert "bound_not_applicable" in _rules(_rec(wrong_tol))


def test_inventory_must_be_explicit_and_is_applied():
    """Fail-before: ignoring non-zero initial stock gives a bound ABOVE
    the true optimum (invalid; valid plans would be refused)."""
    import pytest
    from brain_core.guards.independent_data import raw_due_day, raw_sku_data
    p = generate_fnb_factory(FnbParams(
        seed=101, n_lines=3, n_skus=6, days=3, active_fraction=1.0,
        utilization=0.6, n_raw_materials=3, families=("DAIRY", "BAKERY")))
    f, hs, cap = p.factory, p.params.horizon_start, p.day_capacity_minutes
    cap_eff = cap * (1 - T.DEFAULT_CHG_ALLOWANCE)
    lab = {t: 0.5 * cap for t in range(3)}
    dem = {}
    for d in f.demands:
        t = raw_due_day(d.due, hs)
        if 0 <= t < 3:
            dem.setdefault(d.item, [0.0] * 3)[t] += d.quantity
    inv = {s: 0.5 * sum(v) for s, v in dem.items()}
    with pytest.raises(TypeError):
        lateness_lower_bound([f], hs, 3, cap_eff, labor_cap=lab)
    ignoring = lateness_lower_bound([f], hs, 3, cap_eff, labor_cap=lab,
                                    inv0s=[None])
    applied = lateness_lower_bound([f], hs, 3, cap_eff, labor_cap=lab,
                                   inv0s=[inv])
    r = T.solve_buckets(f, hs, 3, cap, time_limit_s=30, inv0=inv,
                        lab_cap=lab)
    sf = 0.0
    sku = raw_sku_data(f)
    for s, ds in dem.items():
        cum = pr = 0.0
        for t in range(3):
            cum += ds[t]
            pr += sum(r.qty.get((s, t, l), 0.0) for l in sku[s][1])
            sf += max(0.0, cum - inv[s] - pr)
    assert applied <= sf + 1e-6 * max(1.0, sf)       # valid bound
    assert ignoring > sf + 1.0                       # old behaviour invalid
    assert applied < ignoring


def test_rel_tol_is_in_the_manifest_hash():
    from brain_core.guards.anomaly import LATENESS_BOUND_REL_TOL
    from brain_core.guards.manifest import Manifest
    a = Manifest({"lateness_bound_rel_tol": LATENESS_BOUND_REL_TOL}).hash()
    b = Manifest({"lateness_bound_rel_tol": 1e-4}).hash()
    assert a != b and LATENESS_BOUND_REL_TOL == 1e-6
    src = (Path(__file__).resolve().parents[1] / "benchmarks"
           / "monolith_scaling.py").read_text()
    assert '"lateness_bound_rel_tol": LATENESS_BOUND_REL_TOL' in src
