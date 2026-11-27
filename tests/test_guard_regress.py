import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_core.guards.regress import compare

REF = {"pool": 0.9, "caps_v": 2, "regime": "bind", "n": 2, "seed": 0,
       "time_limit_s": 600, "objective": 100.0, "wall_s": 10.0}


def test_same_is_clean():
    assert compare(dict(REF), REF) == []


def test_fault_injection_each_regression_caught():
    assert any("objective" in p for p in compare(
        dict(REF, objective=101.0), REF))
    assert any("wall" in p for p in compare(dict(REF, wall_s=25.0), REF))
    assert any("validation" in p for p in compare(
        dict(REF, validation_problems=["x"]), REF))


def test_different_class_never_compared():
    r = compare(dict(REF, caps_v=1, objective=1.0), REF)
    assert len(r) == 1 and "not comparable" in r[0]
