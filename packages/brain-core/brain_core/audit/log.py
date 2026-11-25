"""Append-only decision audit log (Stage 3, slice 4).

Every plan the system commits - an overnight window solve, a local
re-solve after an event, a scenario comparison, a shadow-pilot week -
is one JSON line: what triggered it, when the trigger was known, when
the decision was ready, how long it took, a content digest of the
plan, and the KPIs the independent validator measured.

Honesty rules honored:
- decision_latency_s is MEASURED (decision_at - event_at when the
  event time is supplied, else the solve wall time), never asserted.
- KPIs come from the caller (validator output); the log records, it
  does not compute or vouch.
- The plan digest is a sha256 over the canonical assignment list, so
  "same plan" claims are checkable.
- stdlib only (json, hashlib, datetime): no new dependency
  (decision 4).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def plan_digest(plan) -> str:
    """sha256 over the canonical assignment list of a WindowPlan.

    Canonical: (day, line, sku, qty rounded to 1e-6) sorted. Two plans
    with the same production in different assignment order digest
    identically; any real change flips the digest.
    """
    rows = sorted((a.day, a.line, a.sku, round(a.qty, 6))
                  for a in plan.assignments)
    blob = json.dumps(rows).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass
class DecisionRecord:
    kind: str                     # window_solve | local_resolve | scenario | shadow_week | ...
    trigger: str                  # human-readable cause ("LINE-01 down day 2")
    event_at: datetime | None     # when the trigger became known (None: planned run)
    decision_at: datetime         # when the plan was ready
    wall_s: float                 # measured solve wall time
    digest: str                   # plan_digest of the committed plan
    kpis: dict = field(default_factory=dict)     # validator-measured
    problems: int = 0
    detail: dict = field(default_factory=dict)   # anything else worth keeping

    @property
    def decision_latency_s(self) -> float:
        """Trigger-known -> decision-ready. Falls back to wall time
        for planned runs with no external event."""
        if self.event_at is not None:
            return (self.decision_at
                    - self.event_at).total_seconds()
        return self.wall_s

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "trigger": self.trigger,
            "event_at": _iso(self.event_at) if self.event_at else None,
            "decision_at": _iso(self.decision_at),
            "wall_s": round(self.wall_s, 3),
            "decision_latency_s": round(self.decision_latency_s, 3),
            "digest": self.digest,
            "kpis": self.kpis,
            "problems": self.problems,
            "detail": self.detail,
        }


class AuditLog:
    """Append-only JSONL writer/reader. One decision per line."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, rec: DecisionRecord) -> dict:
        entry = rec.to_json()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def record_decision(self, kind: str, trigger: str, plan,
                        wall_s: float,
                        event_at: datetime | None = None,
                        kpis: dict | None = None,
                        problems: int = 0,
                        detail: dict | None = None,
                        decision_at: datetime | None = None) -> dict:
        """Digest the plan, stamp the decision time, append, return
        the written entry."""
        rec = DecisionRecord(
            kind=kind, trigger=trigger, event_at=event_at,
            decision_at=decision_at or _utcnow(), wall_s=wall_s,
            digest=plan_digest(plan), kpis=kpis or {},
            problems=problems, detail=detail or {})
        return self.record(rec)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line)
                for line in self.path.read_text().splitlines()
                if line.strip()]

    def summary(self) -> dict:
        """Measured facts over the log: counts per kind and latency
        stats. Nothing derived beyond the recorded numbers."""
        es = self.entries()
        by_kind: dict[str, int] = {}
        lat: list[float] = []
        for e in es:
            by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
            lat.append(e["decision_latency_s"])
        return {
            "decisions": len(es),
            "by_kind": dict(sorted(by_kind.items())),
            "max_decision_latency_s": max(lat) if lat else None,
            "mean_decision_latency_s": (sum(lat) / len(lat)
                                        if lat else None),
        }
