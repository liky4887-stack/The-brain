import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import helpers_guard_steps as h
import pytest
from brain_core.guards.manifest import (Manifest, ManifestDrift,
    accept_row, assert_manifest, check_manifest, stamp, unchecked_keys)
from brain_core.guards.watchdog import Checkpoint, run_step

M = Manifest({"sha": "abc", "caps_v": 2, "pool": 1.5, "seed": 0})


def test_manifest_ok_and_stamp():
    act = dict(M.declared, extra=1)
    assert check_manifest(M, act) == []
    assert unchecked_keys(M, act) == ["extra"]
    row = stamp({"obj": 1}, M)
    assert accept_row(row, M) == []


@pytest.mark.parametrize("key,bad", [("sha", "zzz"), ("caps_v", 1),
                                     ("pool", 2.0)])
def test_fault_injection_manifest_drift_caught(key, bad):
    act = dict(M.declared)
    act[key] = bad
    assert any(key in p for p in check_manifest(M, act))
    with pytest.raises(ManifestDrift):
        assert_manifest(M, act, "step 3")


def test_missing_key_caught():
    act = dict(M.declared)
    del act["seed"]
    assert any("MISSING" in p for p in check_manifest(M, act))


def test_row_filed_under_wrong_class_rejected():
    other = Manifest(dict(M.declared, pool=2.0))
    assert accept_row(stamp({"obj": 1}, other), M)


def test_step_ok():
    r = run_step("q", h.quick, (4,), timeout_s=60)
    assert (r.status, r.value) == ("ok", 8)


def test_fault_injection_hang_is_named_timeout():
    r = run_step("hang", h.hang, timeout_s=3)
    assert r.status == "timeout" and r.wall_s < 30


def test_fault_injection_crash_and_kill_caught():
    assert run_step("boom", h.boom, timeout_s=60).status == "error"
    assert run_step("die", h.die, timeout_s=60).status == "killed"


def test_fault_injection_low_disk_blocks_step():
    r = run_step("d", h.quick, (1,), min_free_disk_bytes=1 << 60)
    assert r.status == "low_disk"


def test_checkpoint_resume_skips_done(tmp_path):
    p = str(tmp_path / "ck.json")
    c = Checkpoint(p)
    assert c.run("a", h.quick, (2,), timeout_s=60).value == 4
    c2 = Checkpoint(p)
    r = c2.run("a", h.hang, timeout_s=1)
    assert r.value == 4 and "resumed" in r.detail
