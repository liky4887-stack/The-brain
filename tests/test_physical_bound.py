"""Pool-level lower bound as an anomaly rule. Fail-before: a record that
claims less lateness than the pools allow used to pass."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from brain_core.guards.anomaly import check_record  # noqa: E402
from brain_core.guards.physical_bound import lateness_lower_bound  # noqa: E402
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
    lb = lateness_lower_bound([f], hs, 3, cap_eff, labor_cap=lab)
    return k["backlog_unit_days"], lb


def test_optimum_is_at_or_above_bound_and_passes():
    bud, lb = _case()
    assert lb > 0 and bud >= lb - 1e-6 * lb
    rec = {"status": "optimal", "incumbent": 1.0, "nodes": 1,
           "lateness_check": {"backlog_unit_days": bud, "lower_bound": lb}}
    assert not [x for x in check_record(rec)
                if x.rule == "below_physical_bound"]


def test_equal_within_noise_passes_and_tolerance_is_recorded():
    bud, lb = _case()
    for claim in (lb, lb * (1 - 1e-8), lb * (1 - 5e-7)):
        rec = {"status": "optimal", "incumbent": 1.0, "nodes": 1,
               "lateness_check": {"backlog_unit_days": claim,
                                  "lower_bound": lb, "rel_tol": 1e-6}}
        assert not [x for x in check_record(rec)
                    if x.rule == "below_physical_bound"], claim
    rec["lateness_check"]["backlog_unit_days"] = lb * (1 - 1e-4)
    f = [x for x in check_record(rec) if x.rule == "below_physical_bound"]
    assert f and "1e-06" in f[0].detail


def test_claim_below_the_bound_is_refused():
    bud, lb = _case()
    for claim in (0.0, 0.5 * lb, lb * (1 - 1e-3)):
        rec = {"status": "optimal", "incumbent": 1.0, "nodes": 1,
               "lateness_check": {"backlog_unit_days": claim,
                                  "lower_bound": lb}}
        assert [x for x in check_record(rec)
                if x.rule == "below_physical_bound"], claim
