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
