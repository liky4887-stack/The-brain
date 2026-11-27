"""The coupled validator must not share data code with the model.

Fail-before: with the validator reading the model's _sku_data, a
corrupted helper (rate x3, i.e. capacity tripled) is seen by the model
AND the validator, so the over-capacity plan validated with 0 problems.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_decompose import H0, _solvable_two_cell_factory  # noqa: E402
from brain_core.rolling import solve_window  # noqa: E402
from brain_core.rolling import coupled as C  # noqa: E402
from brain_core.rolling import two_level as T  # noqa: E402
from brain_core.guards.independent_data import (raw_recipe_data,  # noqa: E402
                                                raw_sku_data, raw_due_day)


def _corrupt(orig, k=3.0):
    def bad(f):
        return {s: (r * k, l, st) for s, (r, l, st) in orig(f).items()}
    return bad


def _qty(plan):
    q = {}
    for a in plan.assignments:
        q[(a.sku, a.day, a.line)] = q.get((a.sku, a.day, a.line), 0.0) + a.qty
    return q


def test_independent_data_equals_model_data_on_clean_records():
    f = _solvable_two_cell_factory()
    m = T._sku_data(f)
    r = raw_sku_data(f)
    assert set(m) == set(r)
    for s in m:
        assert abs(m[s][0] - r[s][0]) < 1e-12
        assert sorted(m[s][1]) == r[s][1]
    assert T._recipe_data(f) == raw_recipe_data(f)
    for d in f.demands:
        assert T.due_day(d.due, H0) == raw_due_day(d.due, H0)


def test_corrupted_model_helper_cannot_pass_the_validator(monkeypatch):
    f = _solvable_two_cell_factory()
    # make the cells so loaded that real capacity binds: demand x20
    for d in f.demands:
        d.quantity = d.quantity * 20
    monkeypatch.setattr(T, "_sku_data", _corrupt(T._sku_data))
    if hasattr(C, "_sku_data"):                 # the pre-fix coupling
        monkeypatch.setattr(C, "_sku_data", _corrupt(C._sku_data))
    p = solve_window(f, H0, 2, 480.0, bucket_time_s=5, seq_time_s=2)
    probs, _ = C.validate_coupled_plan([f], [_qty(p)], H0, 2, 480.0)
    assert any("min >" in x or "linking M" in x for x in probs), probs
