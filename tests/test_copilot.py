"""Stage 4, slice 4: the copilot answers 50 planner questions against
solver output, and every number is checked against an INDEPENDENT
computation of the same fact in the test.

The copilot never computes: it reports validator/explain/twin
numbers with their evidence. Unknown questions are refused.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.copilot import answer
from brain_core.explain import binding_line_days, explain_late
from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)
from brain_core.rolling.two_level import (LotAssignment, WindowPlan,
                                          validate_window_plan)
from brain_core.simtwin import Disruption, execute

H0 = datetime(2026, 11, 30)
CAP = 100.0


def _op(name, item, line):
    return Operation(name=name, item=item, location="P",
                     duration_per=timedelta(minutes=1),
                     materials=[OperationMaterial(item=item, quantity=1)],
                     loads=[OperationResource(resource=line,
                                              setup=f"s{item}")])


def _world():
    skus = ["A", "B", "C"]
    f = Factory(
        locations=[Location(name="P")],
        items=[Item(name=s) for s in skus],
        resources=[Resource(name="L1", location="P", setup_matrix="M"),
                   Resource(name="L2", location="P", setup_matrix="M")],
        setup_matrices=[SetupMatrix(name="M", rules=[
            SetupRule(from_setup=f"s{a}", to_setup=f"s{b}",
                      duration=timedelta(minutes=10))
            for a in skus for b in skus if a != b])],
        operations=[_op("make-A", "A", "L1"), _op("make-B", "B", "L1"),
                    _op("make-C", "C", "L2")],
        demands=[Demand(name="DA", item="A", due=H0 + timedelta(days=2),
                        quantity=150.0),
                 Demand(name="DB", item="B", due=H0 + timedelta(days=2),
                        quantity=40.0),
                 Demand(name="DC", item="C", due=H0 + timedelta(days=3),
                        quantity=60.0)])
    # A: 150 due end of day 1... due_day(H0+2d)=day1. Make 100 by day 1
    # (50 late). B: 40 made day 0 (on time). C: 60 due end day 2, made
    # day 1 (on time). L1 day 0: 100 A = 100 min -> full.
    plan = WindowPlan(horizon_start=H0, days=4,
                      assignments=[
                          LotAssignment("L1", 0, "A", 100.0, 0, 0.0),
                          LotAssignment("L1", 0, "B", 0.0, 1, 0.0),
                          LotAssignment("L1", 1, "B", 40.0, 0, 0.0),
                          LotAssignment("L2", 1, "C", 60.0, 0, 0.0)],
                      bucket=None, seq_status="test")
    return f, plan


def _catalog(f, plan):
    """50 question instances with their independent checks."""
    qs = []
    for sku in ("A", "B", "C", "A", "B"):
        qs.append((f"why is {sku} late?", "why_late"))
    for ph in ("which lines are full?", "any line-days full?",
               "which line-days are full today?", "are all lines full?",
               "show full line-days"):
        qs.append((ph, "full_lines"))
    for ph in ("how much changeover time?", "total changeovers?",
               "changeover minutes?", "how many setups and changeover?",
               "what is the changeover budget?"):
        qs.append((ph, "changeovers"))
    for name in ("DA", "DB", "DC", "DA", "DB", "DC", "DA", "DB", "DC",
                 "DA", "DB", "DC", "DA"):
        qs.append((f"when is {name} produced?", "when_produced"))
    for sku in ("A", "B", "C", "A", "C"):
        qs.append((f"how much of {sku} is late?", "how_late"))
    for ph in ("what is the proxy cost?", "plan cost?",
               "objective value?"):
        qs.append((ph, "proxy_cost"))
    for line, day in (("L1", 0), ("L1", 1), ("L2", 0), ("L2", 1),
                      ("L1", 2), ("L2", 2), ("L1", 3), ("L2", 3)):
        qs.append((f"what if {line} is down on day {day}?",
                   "what_if_down"))
    for line, day in (("L1", 0), ("L1", 1), ("L2", 1), ("L2", 0),
                      ("L1", 2)):
        qs.append((f"how many lots on {line} day {day}?",
                   "lots_on_day"))
    qs.append(("what do you think about my plan?", "unknown"))
    assert len(qs) == 50, len(qs)
    return qs


def test_copilot_answers_50_questions_with_measured_numbers():
    f, plan = _world()
    _, kpis = validate_window_plan(f, plan, CAP)
    exp_full = binding_line_days(f, plan, CAP)
    exp_late = explain_late(f, plan, CAP)
    counts = {}
    for q, intent in _catalog(f, plan):
        a = answer(q, f, plan, CAP)
        assert a.intent == intent, (q, a.intent)
        counts[intent] = counts.get(intent, 0) + 1
        if intent == "why_late":
            sku = q.split()[2]
            mine = [s for s in exp_late if s.startswith(sku + ":")]
            assert (not mine) == (not a.evidence["late"])
            if mine:
                assert a.text == mine[0]
        elif intent == "full_lines":
            assert a.evidence["full"] == exp_full
        elif intent == "changeovers":
            assert a.evidence["changeover_minutes"] == pytest.approx(
                kpis["changeover_minutes"])
            assert a.evidence["setups"] == kpis["setups"]
        elif intent == "when_produced":
            name = q.split()[2]
            dem = next(d for d in f.demands if d.name == name)
            lots = sorted((x["day"], x["line"], x["qty"])
                          for x in a.evidence["lots"])
            truth = sorted((x.day, x.line, x.qty)
                           for x in plan.assignments
                           if x.sku == dem.item and x.qty > 0)
            assert lots == truth
        elif intent == "how_late":
            sku = q.split()[3]
            mine = [s for s in exp_late if s.startswith(sku + ":")]
            if not mine:
                assert a.evidence["late_units"] == 0.0
            else:
                assert a.text == mine[0]
        elif intent == "proxy_cost":
            assert a.evidence["proxy_cost"] == pytest.approx(
                kpis["proxy_cost"])
        elif intent == "what_if_down":
            out = execute(f, plan, Disruption(
                down=((a.evidence["line"], a.evidence["day"]),)))
            assert a.evidence["late_units_end"] == pytest.approx(
                out["backlog_units_end"])
            assert a.evidence["delta_late_units"] == pytest.approx(
                out["backlog_units_end"] - kpis["backlog_units_end"])
        elif intent == "lots_on_day":
            truth = [x for x in plan.assignments
                     if x.line == a.evidence["line"]
                     and x.day == a.evidence["day"] and x.qty > 1e-9]
            assert a.evidence["lots"] == len(truth)
            assert a.evidence["total_units"] == pytest.approx(
                sum(x.qty for x in truth))
        elif intent == "unknown":
            assert a.evidence["refused"]
    assert counts["unknown"] == 1
    assert sum(counts.values()) == 50
