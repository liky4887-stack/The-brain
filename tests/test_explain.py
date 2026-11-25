"""Stage 3, slice 5: plain-words factual explanations.

Every assertion checks the MEASURED numbers appear in the words: the
explanations recomputed from records + plan, never the solver's word.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.explain import (binding_line_days, explain_infeasible,
                                explain_late)
from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)
from brain_core.rolling.two_level import LotAssignment, WindowPlan

H0 = datetime(2026, 1, 5)          # a Monday
CAP = 100.0                        # minutes per line-day


def _factory(demands):
    return Factory(
        locations=[Location(name="P")],
        items=[Item(name="A"), Item(name="B")],
        resources=[Resource(name="L1", location="P", setup_matrix="M")],
        setup_matrices=[SetupMatrix(
            name="M",
            rules=[SetupRule(from_setup="sA", to_setup="sB",
                             duration=timedelta(minutes=20)),
                   SetupRule(from_setup="sB", to_setup="sA",
                             duration=timedelta(minutes=20))])],
        operations=[
            Operation(name="makeA", item="A", location="P",
                      duration_per=timedelta(minutes=1),
                      materials=[OperationMaterial(item="A", quantity=1)],
                      loads=[OperationResource(resource="L1",
                                               setup="sA")]),
            Operation(name="makeB", item="B", location="P",
                      duration_per=timedelta(minutes=1),
                      materials=[OperationMaterial(item="B", quantity=1)],
                      loads=[OperationResource(resource="L1",
                                               setup="sB")])],
        demands=demands)


def _plan(pairs, days=7):
    return WindowPlan(horizon_start=H0, days=days,
                      assignments=[LotAssignment(line=l, day=d, sku=s,
                                                 qty=q, seq_pos=i,
                                                 chg_from_prev_min=c)
                                   for i, (l, d, s, q, c)
                                   in enumerate(pairs)],
                      bucket=None, seq_status="test")


def test_binding_line_day_reports_measured_minutes():
    f = _factory([])
    # 60 units A + 20 units B + 20 min changeover = 100 of 100 -> full
    plan = _plan([("L1", 2, "A", 60.0, 0.0),
                  ("L1", 2, "B", 20.0, 20.0)])
    lines = binding_line_days(f, plan, CAP)
    assert len(lines) == 1
    assert "L1 day 2 is FULL: 100 of 100 minutes used" in lines[0]
    assert "(80 production + 20 changeover in 1 changeovers)" in lines[0]


def test_non_binding_day_not_reported():
    f = _factory([])
    plan = _plan([("L1", 2, "A", 50.0, 0.0)])
    assert binding_line_days(f, plan, CAP) == []


def test_explain_late_reports_due_vs_made_and_capacity_use():
    # due at midnight ending day 2 (repo convention: due_day maps a
    # midnight due to the day it closes)
    demands = [Demand(name="O1", item="A", due=H0 + timedelta(days=3),
                      quantity=100.0)]
    f = _factory(demands)
    # day 0+1 fully used making A, nothing on day 2 ->
    # 200 of 300 eligible minutes used
    plan = _plan([("L1", 0, "A", 100.0, 0.0),
                  ("L1", 1, "A", 100.0, 0.0)])
    # 200 produced total, but demand is 100 -> not late; force late:
    demands[0].quantity = 250.0
    out = explain_late(f, plan, CAP)
    assert len(out) == 1
    assert "250 units due day 2 (O1)" in out[0]
    assert "the plan makes 200 by then - 50 late" in out[0]
    assert "ran at 67% of minutes on days 0..2" in out[0]
    assert "(200 of 300 min incl. changeovers)" in out[0]


def test_explain_late_silent_when_on_time():
    demands = [Demand(name="O1", item="A", due=H0 + timedelta(days=2),
                      quantity=50.0)]
    f = _factory(demands)
    plan = _plan([("L1", 0, "A", 60.0, 0.0)])
    assert explain_late(f, plan, CAP) == []


def test_explain_infeasible_aggregate_overload():
    demands = [Demand(name="O1", item="A", due=H0 + timedelta(days=1),
                      quantity=250.0)]      # 250 min needed, 200 offered
    f = _factory(demands)
    out = explain_infeasible(f, H0, days=2, cap_min=CAP)
    assert "needs 250 production minutes" in out[0]
    assert "1 lines x 2 days offer 200 minutes" in out[0]
    assert any("INFEASIBLE in aggregate" in s for s in out)
    assert any("L1: 250 minutes of demand can ONLY run here" in s
               for s in out)


def test_explain_infeasible_no_overload_no_infeasible_claim():
    demands = [Demand(name="O1", item="A", due=H0 + timedelta(days=1),
                      quantity=150.0)]
    f = _factory(demands)
    out = explain_infeasible(f, H0, days=2, cap_min=CAP)
    assert not any("INFEASIBLE" in s for s in out)
