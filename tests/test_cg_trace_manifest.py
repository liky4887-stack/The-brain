"""cg_trace: the class label comes from the sealed manifest, and a declared
class that differs from the observed one stops the run (the 0.75/0.8 vs
0.9/0.9 mislabel)."""
import os
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))
import cg_trace  # noqa: E402
from brain_core.guards.manifest import ManifestDrift  # noqa: E402


def test_class_name_is_built_from_observed_values():
    m = cg_trace.build_manifest(7, 2)
    d = m.declared
    assert d["class_name"] == cg_trace.class_name(d)
    assert f"pools {d['supplier']}/{d['labor']}" in d["class_name"]
    assert "seed_base 7" in d["class_name"]


def test_declared_class_mismatch_stops_before_any_solve():
    d = cg_trace.build_manifest(0, 2).declared
    wrong = d["class_name"].replace(f"pools {d['supplier']}/{d['labor']}", "pools 0.123/0.456")
    with pytest.raises(ManifestDrift):
        cg_trace.build_manifest(0, 2, expect=wrong)


def test_declared_class_match_passes_and_hash_is_stable():
    a = cg_trace.build_manifest(0, 2)
    b = cg_trace.build_manifest(0, 2, expect=a.declared["class_name"])
    assert a.hash() == b.hash()


def test_pool_guard_records_identity_and_flags_a_converged_value_below_bound():
    import cg_trace
    from types import SimpleNamespace
    import coupled_comparison as cc
    ps, hs, cap = cc.build_cluster(2, seed_base=400012)
    sup, lab, _ = cc.binding_caps(ps, hs, cap)
    ok = cg_trace.pool_guard(ps, hs, cap, sup, lab, SimpleNamespace(
        converged=False, master_series=[1.0], lb_series=[]))
    assert ok["pools_hash"] and ok["pool_findings"] == []   # weak LB: fine
    bad = cg_trace.pool_guard(ps, hs, cap, sup, lab, SimpleNamespace(
        converged=True, master_series=[1.0], lb_series=[]))
    assert bad["pool_findings"][0][0] == "below_physical_bound_pool"


def test_weights_are_sealed_in_the_manifest_and_shown_in_the_class_name():
    d = cg_trace.build_manifest(3, 2).declared
    assert d["weights"] == {"setup": 50.0, "late": 1000.0,
                            "early": 0.001, "energy": 0.0}
    assert "weights setup 50/late 1000" in d["class_name"]


def test_the_weights_sealed_are_the_weights_passed_to_the_solver(
        monkeypatch, tmp_path):
    """Fail-before: the runner passed no weights (solver default) and the
    row did not say which were used. Intercept column_generation and
    compare what it receives with the manifest."""
    import runpy
    import brain_core.rolling.coupled_dw as dwmod
    seen = {}

    def fake(*a, **k):
        seen.update(k)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(dwmod, "column_generation", fake)
    monkeypatch.setattr(sys, "argv", ["cg_trace.py", "3", str(tmp_path / "o")])
    monkeypatch.setenv("CMP_SIZE", "2")
    with pytest.raises(RuntimeError, match="stop after capture"):
        runpy.run_path(cg_trace.__file__, run_name="__main__")
    assert seen["weights"].setup == 50.0 and seen["weights"].late == 1000.0
    assert seen["weights"] == cg_trace.WEIGHTS
