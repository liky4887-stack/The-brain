"""Review fixes in the anomaly/manifest/regress guards (from the user's
local patch, split out)."""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages" / "brain-core"))
sys.path.insert(0, os.path.dirname(__file__))


def test_anomaly_sees_nan_nested_in_lists_and_dicts():
    from brain_core.guards.anomaly import check_record
    rec = {"status": "Optimal", "incumbent": 10.0,
           "shards": [{"obj": 1.0}, {"obj": float("nan")}]}
    assert any(x.rule == "nan_or_missing" and "shards[1].obj" in x.detail
               for x in check_record(rec))


def test_regress_refuses_rows_without_class_keys():
    from brain_core.guards.regress import compare
    out = compare({"objective": 5.0}, {"objective": 1.0})
    assert out and "not comparable" in out[0]


def test_regress_flags_suspiciously_better_objective():
    from brain_core.guards.regress import CLASS_KEYS, compare
    cls = {k: 1 for k in CLASS_KEYS}
    out = compare({**cls, "objective": 50.0}, {**cls, "objective": 100.0})
    assert any("suspiciously better" in x for x in out)
    assert compare({**cls, "objective": 99.0},
                   {**cls, "objective": 100.0}) == []


def test_manifest_bool_vs_number_is_drift_and_set_hash_stable():
    from brain_core.guards.manifest import Manifest, check_manifest
    m = Manifest({"presolve": 1, "pools": {"a", "b", "c"}})
    assert check_manifest(m, {"presolve": True,
                              "pools": {"a", "b", "c"}})
    assert check_manifest(m, {"presolve": 1,
                              "pools": {"a", "b", "c"}}) == []
    assert Manifest({"pools": {"c", "a", "b"}}).hash() == \
        Manifest({"pools": {"b", "c", "a"}}).hash()
