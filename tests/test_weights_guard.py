import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))
from brain_core.guards.weights_guard import compare_weights, row_weights  # noqa: E402

CG = {"weights": {"setup": 50.0, "late": 1000.0, "early": 0.001,
                  "energy": 0.0}}


def rules(a, b):
    return [f.rule for f in compare_weights(a, b)]


def test_equal_weights_pass():
    assert rules(CG, dict(CG)) == []


def test_unequal_setup_weight_is_refused():
    other = {"weights": {**CG["weights"], "setup": 27.0}}
    assert rules(CG, other) == ["weights_differ_not_comparable"]


def test_calibration_row_is_labelled_non_comparable_with_cg():
    cal = {"calibration": {"setup_weight": 20.68071428571429,
                           "holding_weight": 0.001}}
    assert rules(CG, cal) == ["calibration_weights_not_comparable"]


def test_row_without_weights_is_a_finding_not_a_pass():
    assert rules(CG, {"status": "ok"}) == ["weights_not_recorded"]
    assert row_weights({"status": "ok"}) is None


def test_real_raw_rows_on_the_results_branch_if_present():
    """Measured on monolith-results: the 18 retained plans declare
    50/1000/0.001 and compare clean with a CG row at the defaults; the
    calibration rows do not. Skipped when the raw files are not checked out."""
    import pytest
    base = Path("/tmp/mr/codespace-results")
    p = base / "mono-plan" / "mp-v1-100003.json"
    c = next(iter(sorted(Path("/tmp/mr").glob("cs-calib3-4-s0-none.json"))),
             None)
    if not p.exists() or c is None:
        pytest.skip("results branch not checked out")
    plan = json.loads(p.read_text())
    assert rules(CG, plan) == []
    assert rules(CG, json.loads(c.read_text())) == [
        "calibration_weights_not_comparable"]


def test_cg_trace_rows_declare_weights_in_the_manifest():
    row = {"manifest": {"weights": CG["weights"]}}
    assert row_weights(row)["setup"] == 50.0
    assert rules(row, CG) == []
