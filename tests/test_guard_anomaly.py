import pytest
from brain_core.guards.anomaly import (RunPaused, check_record,
                                       guarded_step)

GOOD = {"status": "Optimal", "incumbent": 10.0, "bound": 10.0,
        "mip_gap": 0.0, "nodes": 5, "int_violation": 0.0,
        "mip_valid": True, "manifest_hash": "h"}


def rules(r, mh="h"):
    return {x.rule for x in check_record(r, mh)}


def test_good_record_passes():
    assert rules(GOOD) == set()


@pytest.mark.parametrize("mut,rule", [
    ({"manifest_hash": "other"}, "class_mismatch"),
    ({"nodes": -1}, "invalid_not_a_mip"),
    ({"int_violation": 0.4}, "invalid_not_a_mip"),
    ({"mip_valid": False}, "invalid_not_a_mip"),
    ({"mip_gap": 0.2}, "status_incoherent"),
    ({"bound": 11.0}, "bound_crossed"),
    ({"incumbent": float("nan")}, "nan_or_missing"),
    ({"incumbent": None}, "nan_or_missing"),
    ({"ub_used": True, "validation_problems": ["x"]},
     "ub_not_validated"),
    ({"ub_used": True}, "ub_not_validated"),
])
def test_fault_injection_each_rule_caught(mut, rule):
    assert rule in rules(dict(GOOD, **mut))


def test_ub_used_with_clean_validator_ok():
    assert rules(dict(GOOD, ub_used=True,
                      validation_problems=[])) == set()


def test_pause_without_declared_fix():
    log = []
    with pytest.raises(RunPaused):
        guarded_step(lambda: dict(GOOD, nodes=-1), "h", fault_log=log)
    assert log and log[0]["findings"][0][0] == "invalid_not_a_mip"


def test_declared_safe_fix_runs_then_passes():
    log = []
    rec = guarded_step(lambda: dict(GOOD, int_violation=0.5), "h",
                       safe_fixes={"invalid_not_a_mip": lambda: GOOD},
                       fault_log=log)
    assert rec == GOOD and len(log) == 1


def test_fix_that_keeps_failing_stops_after_two_attempts():
    bad = lambda: dict(GOOD, nodes=-1)
    with pytest.raises(RunPaused):
        guarded_step(bad, "h", safe_fixes={"invalid_not_a_mip": bad})


def test_wrong_class_has_no_auto_fix():
    with pytest.raises(RunPaused):
        guarded_step(lambda: dict(GOOD, manifest_hash="z"), "h",
                     safe_fixes={"invalid_not_a_mip": lambda: GOOD})
