"""Persistence for canonical records (Stage 1 data foundation).

The production database is Postgres (schema.sql in this package is the
DDL of record). The store below speaks the SQLite subset of that DDL
so the engine runs and tests end-to-end with zero infrastructure;
the same statements go through psycopg against Postgres unchanged
(timestamptz -> ISO-8601 text is the only adaptation, applied here).

Honesty rule: load() reconstructs records through the same pydantic
validation and reference checks as fresh input; a corrupted database
fails loudly, never silently.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .models import (
    Buffer, Calendar, Demand, Factory, Item, Location, Operation,
    OperationMaterial, OperationResource, Resource, SetupMatrix, SetupRule,
)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _sqlite_ddl() -> str:
    """Postgres DDL -> SQLite subset: drop CHECKs referencing regexes
    (none), map types. The subset used here translates directly."""
    sql = _SCHEMA_PATH.read_text()
    return (sql.replace("TIMESTAMPTZ", "TEXT")
               .replace("DOUBLE PRECISION", "REAL")
               .replace("BIGINT", "INTEGER"))


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _secs(td: timedelta) -> int:
    return int(td.total_seconds())


def _td(s: int | None) -> timedelta:
    return timedelta(seconds=s or 0)


def save(factory: Factory, db_path: str) -> None:
    problems = factory.validate_references()
    if problems:
        raise ValueError("refusing to save a factory with broken "
                         f"references: {problems}")
    con = sqlite3.connect(db_path)
    try:
        con.executescript(_sqlite_ddl())
        with con:
            for l in factory.locations:
                con.execute("INSERT OR REPLACE INTO location VALUES (?,?,?)",
                            (l.name, l.description, l.available_calendar))
            for i in factory.items:
                con.execute("INSERT OR REPLACE INTO item VALUES (?,?,?)",
                            (i.name, i.description, i.cost))
            for c in factory.calendars:
                con.execute("INSERT OR REPLACE INTO calendar VALUES (?,?)",
                            (c.name, c.default_value))
                for s, e, v in c.buckets:
                    con.execute("INSERT INTO calendar_bucket VALUES (?,?,?,?)",
                                (c.name, _iso(s), _iso(e), v))
            for m in factory.setup_matrices:
                con.execute("INSERT OR REPLACE INTO setup_matrix VALUES (?)",
                            (m.name,))
                for r in m.rules:
                    con.execute(
                        "INSERT OR REPLACE INTO setup_rule VALUES (?,?,?,?,?)",
                        (m.name, r.from_setup, r.to_setup, _secs(r.duration),
                         r.cost))
            for r in factory.resources:
                con.execute(
                    "INSERT OR REPLACE INTO resource VALUES (?,?,?,?,?,?)",
                    (r.name, r.location, r.maximum, r.maximum_calendar,
                     r.setup_matrix, r.efficiency))
            for op in factory.operations:
                con.execute(
                    "INSERT OR REPLACE INTO operation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (op.name, op.item, op.location, _secs(op.duration),
                     _secs(op.duration_per), op.size_minimum, op.size_multiple,
                     op.size_maximum, op.cost, _iso(op.effective_start),
                     _iso(op.effective_end)))
                for m in op.materials:
                    con.execute(
                        "INSERT OR REPLACE INTO operation_material VALUES (?,?,?)",
                        (op.name, m.item, m.quantity))
                for ld in op.loads:
                    con.execute(
                        "INSERT OR REPLACE INTO operation_resource VALUES (?,?,?,?,?)",
                        (op.name, ld.resource, ld.quantity, ld.setup, ld.skill))
            for b in factory.buffers:
                con.execute("INSERT OR REPLACE INTO buffer VALUES (?,?,?,?,?)",
                            (b.item, b.location, b.onhand, b.minimum, b.maximum))
            for d in factory.demands:
                con.execute(
                    "INSERT OR REPLACE INTO demand VALUES (?,?,?,?,?,?,?,?)",
                    (d.name, d.item, d.location, _iso(d.due), d.quantity,
                     d.priority, d.minshipment,
                     _secs(d.maxlateness) if d.maxlateness else None))
    finally:
        con.close()


def load(db_path: str) -> Factory:
    con = sqlite3.connect(db_path)
    try:
        q = lambda sql, args=(): con.execute(sql, args).fetchall()
        calendars = [Calendar(name=n, default_value=v, buckets=[
            (_dt(s), _dt(e), val) for s, e, val in
            q("SELECT starts, ends, value FROM calendar_bucket "
              "WHERE calendar = ?", (n,))])
            for n, v in q("SELECT name, default_value FROM calendar")]
        matrices = [SetupMatrix(name=n, rules=[
            SetupRule(from_setup=f, to_setup=t, duration=_td(d), cost=c)
            for f, t, d, c in q("SELECT from_setup, to_setup, "
                                "duration_seconds, cost FROM setup_rule "
                                "WHERE setup_matrix = ?", (n,))])
            for (n,) in q("SELECT name FROM setup_matrix")]
        operations = [Operation(
            name=n, item=it, location=lo, duration=_td(dur),
            duration_per=_td(dp), size_minimum=sm, size_multiple=smu,
            size_maximum=sma, cost=cost, effective_start=_dt(es),
            effective_end=_dt(ee),
            materials=[OperationMaterial(item=mi, quantity=mq) for mi, mq in
                       q("SELECT item, quantity FROM operation_material "
                         "WHERE operation = ? ORDER BY item", (n,))],
            loads=[OperationResource(resource=rs, quantity=rq, setup=st,
                                     skill=sk)
                   for rs, rq, st, sk in
                   q("SELECT resource, quantity, setup, skill FROM "
                     "operation_resource WHERE operation = ? ORDER BY resource", (n,))])
            for n, it, lo, dur, dp, sm, smu, sma, cost, es, ee in
            q("SELECT name, item, location, duration_seconds, "
              "duration_per_seconds, size_minimum, size_multiple, "
              "size_maximum, cost, effective_start, effective_end "
              "FROM operation")]
        factory = Factory(
            locations=[Location(name=n, description=de, available_calendar=ac)
                       for n, de, ac in
                       q("SELECT name, description, available_calendar "
                         "FROM location")],
            items=[Item(name=n, description=de, cost=c)
                   for n, de, c in q("SELECT name, description, cost FROM item")],
            calendars=calendars,
            setup_matrices=matrices,
            resources=[Resource(name=n, location=lo, maximum=mx,
                                maximum_calendar=mc, setup_matrix=sm,
                                efficiency=ef)
                       for n, lo, mx, mc, sm, ef in
                       q("SELECT name, location, maximum, maximum_calendar, "
                         "setup_matrix, efficiency FROM resource")],
            operations=operations,
            buffers=[Buffer(item=it, location=lo, onhand=oh, minimum=mn,
                            maximum=mx)
                     for it, lo, oh, mn, mx in
                     q("SELECT item, location, onhand, minimum, maximum "
                       "FROM buffer")],
            demands=[Demand(name=n, item=it, location=lo, due=_dt(due),
                            quantity=qt, priority=pr, minshipment=ms,
                            maxlateness=_td(ml) if ml is not None else None)
                     for n, it, lo, due, qt, pr, ms, ml in
                     q("SELECT name, item, location, due, quantity, priority, "
                       "minshipment, maxlateness_seconds FROM demand")])
        problems = factory.validate_references()
        if problems:
            raise ValueError(f"database holds broken references: {problems}")
        return factory
    finally:
        con.close()
