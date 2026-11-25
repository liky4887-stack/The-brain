"""Stage 3, slice 4: the decision audit log.

Measured facts only: round-trip of entries, digest stability, and
decision latency computed from recorded timestamps.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.audit import AuditLog, plan_digest
from brain_core.rolling.two_level import LotAssignment, WindowPlan


def _plan(pairs, day0=None):
    return WindowPlan(horizon_start=day0 or datetime(2026, 1, 5),
                      days=7,
                      assignments=[LotAssignment(line=l, day=d, sku=s,
                                                 qty=q, seq_pos=0,
                                                 chg_from_prev_min=0.0)
                                   for (l, d, s, q) in pairs],
                      bucket=None, seq_status="test")


def test_round_trip_one_json_object_per_line(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    plan = _plan([("L1", 0, "SKU-A", 100.0), ("L1", 1, "SKU-B", 50.0)])
    e1 = log.record_decision("window_solve", "nightly run", plan,
                             wall_s=12.5,
                             kpis={"late_units": 0.0, "chg_min": 240.0})
    e2 = log.record_decision("local_resolve", "L1 down day 3", plan,
                             wall_s=0.4,
                             event_at=datetime(2026, 1, 8, 10, 0,
                                               tzinfo=timezone.utc),
                             detail={"moved_fraction": 0.01})
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)          # each line is one valid JSON object
    es = log.entries()
    assert [e["kind"] for e in es] == ["window_solve", "local_resolve"]
    assert e1["digest"] == e2["digest"] == plan_digest(plan)
    assert e2["decision_latency_s"] > 0


def test_decision_latency_measured_from_event_time():
    event = datetime(2026, 1, 8, 10, 0, tzinfo=timezone.utc)
    ready = event + timedelta(seconds=47.2)
    log = AuditLog(Path("/nonexistent/never-written.jsonl"))
    from brain_core.audit.log import DecisionRecord
    rec = DecisionRecord(kind="local_resolve", trigger="line down",
                         event_at=event, decision_at=ready,
                         wall_s=0.4, digest="x")
    assert abs(rec.decision_latency_s - 47.2) < 1e-6
    # planned run: no event time -> latency is the solve wall time
    rec2 = DecisionRecord(kind="window_solve", trigger="nightly",
                          event_at=None, decision_at=ready,
                          wall_s=238.5, digest="x")
    assert rec2.decision_latency_s == 238.5


def test_digest_order_insensitive_but_change_sensitive():
    p1 = _plan([("L1", 0, "A", 100.0), ("L2", 1, "B", 50.0)])
    p2 = _plan([("L2", 1, "B", 50.0), ("L1", 0, "A", 100.0)])
    p3 = _plan([("L1", 0, "A", 100.0), ("L2", 1, "B", 51.0)])
    assert plan_digest(p1) == plan_digest(p2)
    assert plan_digest(p1) != plan_digest(p3)


def test_summary_counts_and_latency(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    plan = _plan([("L1", 0, "A", 10.0)])
    base = datetime(2026, 1, 8, 9, 0, tzinfo=timezone.utc)
    for i, kind in enumerate(["window_solve", "local_resolve",
                              "local_resolve"]):
        ev = base + timedelta(hours=i)
        log.record_decision(kind, f"trigger {i}", plan, wall_s=1.0,
                            event_at=ev,
                            decision_at=ev + timedelta(seconds=10 * (i + 1)))
    s = log.summary()
    assert s["decisions"] == 3
    assert s["by_kind"] == {"local_resolve": 2, "window_solve": 1}
    assert s["max_decision_latency_s"] == 30.0
    assert s["mean_decision_latency_s"] == 20.0
