"""Linking M: version v1 (one line-day, as published) vs v2 (per-line
sum). Evidence that v1 cuts plans that are feasible per line capacity,
a check of M against the physical maximum, and version separation.
Instance: synthetic plant seed 101, SKU eligible on 3 lines, demand
2.2 x one line-day (feasible: 3 lines can make 3 x)."""
import copy
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))

from brain_core.guards.regress import class_of  # noqa: E402
from brain_core.rolling import two_level as T  # noqa: E402
from brain_core.rolling.coupled import (linking_m_problems,  # noqa: E402
                                        validate_coupled_plan)
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402


def _inst():
    p = generate_fnb_factory(FnbParams(
        seed=101, n_lines=3, n_skus=3, days=1, active_fraction=1.0,
        utilization=0.3, n_raw_materials=3, families=("DAIRY", "BAKERY")))
    f = copy.deepcopy(p.factory)
    hs, cap = p.params.horizon_start, p.day_capacity_minutes
    s = next(iter(T._sku_data(f)))
    rate, lines, _ = T._sku_data(f)[s]
    cap_eff = cap * (1 - T.DEFAULT_CHG_ALLOWANCE)
    dm = [d for d in f.demands if d.item == s][0]
    f.demands = [dm]
    dm.quantity = 2.2 * cap_eff * rate
    dm.due = hs + timedelta(days=1)
    return f, hs, cap, s, rate, lines, cap_eff, dm.quantity


def test_default_is_v1_and_unchanged(monkeypatch):
    monkeypatch.delenv("BRAIN_LINKING_M", raising=False)
    assert T.linking_m_version() == "v1"
    assert T.linking_m((2.0, ["a", "b", "c"], None), 100.0, 1e9) == 200.0


def test_v2_is_the_per_line_sum_and_stays_tight():
    e = (2.0, ["a", "b", "c"], None)
    assert T.linking_m(e, 100.0, 1e9, "v2") == 600.0
    assert T.linking_m(e, 100.0, 50.0, "v2") == 51.0     # demand + 1
    assert T.linking_m(e, 100.0, 1e9, "v2",
                       line_cap={"a": 10.0}) == 2.0 * (10 + 100 + 100)


def test_bad_version_refused(monkeypatch):
    monkeypatch.setenv("BRAIN_LINKING_M", "v3")
    with pytest.raises(ValueError):
        T.linking_m_version()


def test_small_m_cuts_a_plan_that_is_feasible_under_the_right_m(monkeypatch):
    f, hs, cap, s, rate, lines, cap_eff, demand = _inst()
    third = demand / 3.0
    plan = {(s, 0, l): third for l in lines}
    assert third / rate < cap_eff          # each line under its capacity
    monkeypatch.setenv("BRAIN_LINKING_M", "v2")
    probs, k = validate_coupled_plan([f], [plan], hs, 1, cap)
    assert probs == [] and k["backlog_units_end"] == 0     # feasible
    monkeypatch.setenv("BRAIN_LINKING_M", "v1")
    probs, _ = validate_coupled_plan([f], [plan], hs, 1, cap)
    assert probs and all("linking M" in x for x in probs)  # only M cuts
    # and the model itself under v1 cannot deliver it, under v2 it does
    r1 = T.solve_buckets(f, hs, 1, cap, time_limit_s=20)
    monkeypatch.setenv("BRAIN_LINKING_M", "v2")
    r2 = T.solve_buckets(f, hs, 1, cap, time_limit_s=20)
    d1 = sum(v for k, v in r1.qty.items() if k[0] == s)
    d2 = sum(v for k, v in r2.qty.items() if k[0] == s)
    assert d1 < 0.6 * demand and d2 > 0.999 * demand, (d1, d2, demand)


def test_physical_maximum_check_flags_v1_not_v2():
    f, hs, cap, *_ = _inst()
    assert linking_m_problems(f, hs, 1, cap, version="v1")
    assert linking_m_problems(f, hs, 1, cap, version="v2") == []


def test_versions_are_different_classes():
    a = {"pool": 1.5, "caps_v": 2, "regime": "x", "n": 4, "seed": 3,
         "time_limit_s": 600}
    assert class_of(a) == class_of({**a, "linking_m_version": "v1"})
    assert class_of(a) != class_of({**a, "linking_m_version": "v2"})
