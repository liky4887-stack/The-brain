"""The weights guard is part of the comparison path, not a helper.
Fail-before: no comparison path called it. These tests fail if a path
bypasses it: (1) the run refuses BEFORE any solve, (2) the sanctioned
compare script exits non-zero with the verdict by name, (3) a scan fails
when a benchmark file that combines CG and monolith solves does not call
require_comparable."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))
import coupled_comparison as cc  # noqa: E402
from brain_core.guards.weights_guard import ComparisonRefused  # noqa: E402

W50 = {"setup": 50.0, "late": 1000.0, "early": 0.001, "energy": 0.0}


def test_run_is_refused_before_any_solve_when_cg_weights_differ(monkeypatch):
    called = []
    for n in ("solve_mip", "build_coupled_mip", "column_generation",
              "integer_master", "coupled_dual"):
        monkeypatch.setattr(cc, n, lambda *a, _n=n, **k: called.append(_n))
    monkeypatch.setenv("CMP_CG_SETUP_W", "27")
    with pytest.raises(ComparisonRefused, match="weights_differ_not_comparable"):
        cc.run(2, monolith_limit_s=3.0)
    assert called == [], called


def _mk(tmp_path, name, d):
    p = tmp_path / name
    p.write_text(json.dumps(d))
    return str(p)


def _cmp(tmp_path, cg, mono, *extra):
    r = subprocess.run([sys.executable, str(ROOT / "benchmarks"
                                            / "compare_cg_monolith.py"),
                        _mk(tmp_path, "cg.json", cg),
                        _mk(tmp_path, "m.json", mono), *extra],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


CG = {"manifest": {"weights": W50}, "pools_hash": "abc", "status": "ok",
      "lower_bound": 100.0, "upper_bound": None, "iterations": 3}
MONO = {"weights": W50, "pools_hash": "abc", "objective": 101.0, "gap": 0}


def test_compare_script_names_the_verdict_and_prints_numbers(tmp_path):
    rc, out = _cmp(tmp_path, CG, MONO)
    assert rc == 0
    assert "weights_verdict: weights_comparable" in out
    assert '"monolith_minus_cg_lb": 1.0' in out


@pytest.mark.parametrize("mono,rule", [
    ({**MONO, "weights": {**W50, "setup": 27.0}},
     "weights_differ_not_comparable"),
    ({"calibration": {"setup_weight": 20.68, "holding_weight": 0.001},
      "pools_hash": "abc", "objective": 1.0},
     "calibration_weights_not_comparable"),
    ({"pools_hash": "abc", "objective": 1.0}, "weights_not_recorded"),
])
def test_compare_script_refuses_and_prints_no_numbers(tmp_path, mono, rule):
    rc, out = _cmp(tmp_path, CG, mono)
    assert rc == 2 and out.startswith("REFUSED") and rule in out
    assert '"objective":' not in out and '"lower_bound":' not in out


def test_compare_script_refuses_different_pools(tmp_path):
    rc, out = _cmp(tmp_path, CG, {**MONO, "pools_hash": "other"})
    assert rc == 3 and "pools_differ_not_comparable" in out


def _combines_cg_and_monolith(text):
    return ("column_generation" in text
            and re.search(r"solve_mip|build_coupled_mip|solve_highspy", text)
            is not None)


def test_every_file_that_combines_cg_and_monolith_calls_the_guard():
    found = []
    for p in sorted((ROOT / "benchmarks").glob("*.py")):
        t = p.read_text()
        if _combines_cg_and_monolith(t):
            found.append(p.name)
            assert "require_comparable" in t, (
                f"{p.name} combines CG and monolith but never calls "
                "require_comparable")
    assert "coupled_comparison.py" in found       # the scan is not vacuous


def test_the_scan_predicate_catches_an_unguarded_file():
    bad = "from x import column_generation\nsolve_mip(m)\n"
    assert _combines_cg_and_monolith(bad)
    assert "require_comparable" not in bad


def test_cg_value_falls_back_to_the_converged_master_and_says_so(tmp_path):
    cg = {**CG, "lower_bound": None, "status": "converged (certified)",
          "master_series": [102.0, 100.5]}
    rc, out = _cmp(tmp_path, cg, MONO)
    assert rc == 0
    assert '"value_source": "master_final_converged_lp"' in out
    assert '"monolith_minus_cg_lb": 0.5' in out
