"""Fault injection: the validators must refuse wrong values/places.
Each case passed with 0 problems on main 2a9a39f (measured)."""
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_decompose import H0, _solvable_two_cell_factory  # noqa: E402
from brain_core.rolling import solve_window, validate_window_plan  # noqa: E402
from brain_core.rolling.coupled import validate_coupled_plan  # noqa: E402


def _plan():
    f = _solvable_two_cell_factory()
    p = solve_window(f, H0, 2, 480.0, bucket_time_s=5, seq_time_s=2)
    assert p.assignments and p.problems == []
    return f, p


@pytest.mark.parametrize("field,bad", [
    ("qty", float("nan")), ("qty", -5.0), ("qty", 0.0),
    ("qty", float("inf")), ("day", 99), ("day", -1),
    ("seq_pos", -1), ("chg_from_prev_min", float("nan"))])
def test_window_validator_catches_wrong_value_or_place(field, bad):
    f, p = _plan()
    assert validate_window_plan(f, p, 480.0)[0] == []
    bad_a = [replace(p.assignments[0], **{field: bad})] + p.assignments[1:]
    probs, _ = validate_window_plan(f, replace(p, assignments=bad_a), 480.0)
    assert probs, "validator passed a bad plan"


@pytest.mark.parametrize("mode", ["nan", "inf", "day99", "day-1"])
def test_coupled_validator_catches_wrong_value_or_place(mode):
    f, p = _plan()
    q = {}
    for a in p.assignments:
        q[(a.sku, a.day, a.line)] = q.get((a.sku, a.day, a.line), 0.0) + a.qty
    assert validate_coupled_plan([f], [q], H0, 2, 480.0)[0] == []
    k = next(iter(q))
    bad = dict(q)
    if mode == "nan":
        bad[k] = math.nan
    elif mode == "inf":
        bad[k] = math.inf
    elif mode == "day99":
        bad[(k[0], 99, k[2])] = bad.pop(k)
    else:
        bad[(k[0], -1, k[2])] = bad.pop(k)
    assert validate_coupled_plan([f], [bad], H0, 2, 480.0)[0]
