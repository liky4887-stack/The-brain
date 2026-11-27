"""Known-failure registry: signatures stable, healing bounded, learning."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "benchmarks"))

from failure_registry import (MAX_HEAL_ATTEMPTS, healing_decision,
                              load, record, save, signature)


def test_signature_stable_across_volatile_details():
    a = signature("plant 14: CP-SAT UNKNOWN after 120 s on shard 3")
    b = signature("plant 82: CP-SAT UNKNOWN after 40 s on shard 11")
    assert a == b
    assert a != signature("plant 14: INFEASIBLE proven")


def test_record_and_load_roundtrip(tmp_path):
    e = record(str(tmp_path), "abc123def456", summary="boom",
               run_id="r1", sha="deadbeef", step=2)
    assert e["status"] == "open" and e["attempts"] == 0
    reg = load(str(tmp_path))
    assert reg["entries"]["abc123def456"]["last_seen"]["step"] == 2
    # fix lands: status + fix commit recorded
    record(str(tmp_path), "abc123def456", summary="boom", run_id="r2",
           sha="cafe", step=2, status="fixed", fix_commit="cafe99",
           avoidance="escalate day limit")
    reg = load(str(tmp_path))
    assert reg["entries"]["abc123def456"]["fix_commit"] == "cafe99"
    assert reg["entries"]["abc123def456"]["first_seen"]["sha"] == \
        "deadbeef"   # provenance kept


def test_healing_decision_boundaries():
    reg = {"version": 1, "entries": {}}
    assert healing_decision(reg, "new", 1, False)["action"] == "diagnose"
    reg["entries"]["s1"] = {"status": "open", "attempts": 0}
    d = healing_decision(reg, "s1", 1, False)
    assert d["action"] == "pause" and "already open" in d["why"]
    reg["entries"]["s1"] = {"status": "fixed", "fix_commit": "f123",
                            "attempts": 0}
    d = healing_decision(reg, "s1", 1, run_has_fix=False)
    assert d["action"] == "pause" and "does not contain" in d["why"]
    d = healing_decision(reg, "s1", 1, run_has_fix=True)
    assert d["action"] == "redispatch"
    reg["entries"]["s1"]["attempts"] = MAX_HEAL_ATTEMPTS
    d = healing_decision(reg, "s1", 1, run_has_fix=True)
    assert d["action"] == "pause" and "budget" in d["why"]


def test_master_status15_failure_is_registered_as_fixed_with_commit():
    import os
    reg = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                      "benchmarks", "registry", "known-failures.json")))
    hits = [e for e in reg["entries"].values() if "Status 15" in e.get("summary", "")]
    assert len(hits) == 1
    e = hits[0]
    assert e["status"] == "fixed" and e["attempts"] == 2 and len(e["fix_commit"]) == 40
    assert "scale mismatch" in e["root_cause"]
