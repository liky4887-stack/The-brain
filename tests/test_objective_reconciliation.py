"""Objective reconciliation guard and the backlog_unit_days KPI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from brain_core.guards.anomaly import check_record  # noqa: E402
from brain_core.guards.objective import reconciliation  # noqa: E402
from brain_core.rolling import two_level as T  # noqa: E402
from brain_core.rolling.coupled import (build_coupled_mip,  # noqa: E402
                                        validate_coupled_plan)
from brain_core.solvers.highs_mip import solve_mip  # noqa: E402
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from coupled_comparison import qty_from_mip_x  # noqa: E402


def _solved(util=0.6):
    p = generate_fnb_factory(FnbParams(
        seed=101, n_lines=3, n_skus=6, days=3, active_fraction=1.0,
        utilization=util, n_raw_materials=3,
        families=("DAIRY", "BAKERY")))
    f, hs, cap = p.factory, p.params.horizon_start, p.day_capacity_minutes
    # tight labor pool so lateness appears
    mip, meta = build_coupled_mip([f], hs, 3, cap, {}, {0: 0.5 * cap, 1: 0.5 * cap, 2: 0.5 * cap})
    r = solve_mip(mip, time_limit_s=30)
    q = qty_from_mip_x(r["x"], meta["maps"], meta["offsets"])
    probs, k = validate_coupled_plan([f], q, hs, 3, cap, labor_cap={0: 0.5 * cap, 1: 0.5 * cap, 2: 0.5 * cap})
    return r["objective"], k, probs


def test_objective_reconciles_with_backlog_unit_days():
    obj, k, probs = _solved()
    assert probs == []
    assert k["backlog_unit_days"] > 0          # shortfall exists
    rec = {"status": "optimal", "incumbent": obj, "nodes": 1,
           "objective_reconciliation": reconciliation(obj, k, T.DEFAULT_WEIGHTS)}
    assert abs(rec["objective_reconciliation"]["recomputed"] - obj) <= 1e-6 * obj
    assert not [x for x in check_record(rec) if x.rule == "objective_mismatch"]


def test_late_unit_days_alone_does_not_reconcile():
    """Why the second KPI exists: the old KPI misses persisting shortfall."""
    obj, k, _ = _solved()
    k2 = dict(k, backlog_unit_days=k["late_unit_days"])
    r = reconciliation(obj, k2, T.DEFAULT_WEIGHTS)
    assert k["backlog_unit_days"] > k["late_unit_days"] + 1.0
    assert abs(r["recomputed"] - obj) > 1e-3 * obj


def test_hidden_term_mismatch_stops_the_run():
    obj, k, _ = _solved()
    rec = {"status": "optimal", "incumbent": obj, "nodes": 1,
           "objective_reconciliation": {"solver": obj * 1.01,
                                        "recomputed": obj}}
    assert [x for x in check_record(rec) if x.rule == "objective_mismatch"]
    rec["objective_reconciliation"] = {"solver": obj, "recomputed": float("nan")}
    assert [x for x in check_record(rec) if x.rule == "objective_mismatch"]


def test_wrong_weight_is_caught():
    obj, k, _ = _solved()
    bad = T.ObjectiveWeights(setup=T.DEFAULT_WEIGHTS.setup,
                             late=T.DEFAULT_WEIGHTS.late * 0.5,
                             early=T.DEFAULT_WEIGHTS.early)
    rec = {"status": "optimal", "incumbent": obj, "nodes": 1,
           "objective_reconciliation": reconciliation(obj, k, bad)}
    assert [x for x in check_record(rec) if x.rule == "objective_mismatch"]
