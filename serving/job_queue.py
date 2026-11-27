"""Postgres-backed job queue for the serving layer (SQLite twin for tests).

Semantics are identical on both backends: a worker claims the oldest
queued job atomically (Postgres: SELECT ... FOR UPDATE SKIP LOCKED;
SQLite: one IMMEDIATE transaction), runs it, then stores the result.
No ORM, no framework: the queue is a table, the API is stdlib
http.server, the worker is a loop. pg8000 (BSD-3) is the Postgres
driver - imported lazily so the sqlite path needs nothing installed.
"""

from __future__ import annotations

import json
import sqlite3

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    result TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    claimed_at TEXT,
    finished_at TEXT
);
"""


class JobQueue:
    """backend: 'sqlite' (path or :memory:) or 'postgres' (dsn)."""

    def __init__(self, backend: str, target: str):
        self.backend = backend
        if backend == "sqlite":
            self._conn = sqlite3.connect(target, check_same_thread=False)
            self._conn.execute(DDL_SQLITE)
            self._conn.commit()
        elif backend == "postgres":
            import pg8000  # lazy: BSD-3 driver, optional dependency
            self._conn = pg8000.connect(target) if isinstance(
                target, str) else pg8000.connect(**target)
            cur = self._conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id BIGSERIAL PRIMARY KEY, spec JSONB NOT NULL,"
                " status TEXT NOT NULL DEFAULT 'queued', result JSONB,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                " claimed_at TIMESTAMPTZ, finished_at TIMESTAMPTZ)")
            self._conn.commit()
        else:
            raise ValueError(f"bad backend {backend!r}")

    def submit(self, spec: dict) -> int:
        if self.backend == "sqlite":
            cur = self._conn.execute("INSERT INTO jobs (spec) VALUES (?)",
                                     (json.dumps(spec),))
            self._conn.commit()
            return int(cur.lastrowid)
        cur = self._conn.cursor()
        cur.execute("INSERT INTO jobs (spec) VALUES (%s) RETURNING id",
                    (json.dumps(spec),))
        jid = cur.fetchone()[0]
        self._conn.commit()
        return int(jid)

    def claim(self) -> dict | None:
        """Atomically take the oldest queued job -> running. None if empty."""
        if self.backend == "sqlite":
            self._conn.isolation_level = "IMMEDIATE"
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT id, spec FROM jobs WHERE status='queued'"
                " ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self._conn.rollback()
                return None
            self._conn.execute(
                "UPDATE jobs SET status='running',"
                " claimed_at=datetime('now') WHERE id=?", (row[0],))
            self._conn.commit()
            return {"id": row[0], "spec": json.loads(row[1])}
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE jobs SET status='running', claimed_at=now()"
            " WHERE id = (SELECT id FROM jobs WHERE status='queued'"
            " ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)"
            " RETURNING id, spec::text")
        row = cur.fetchone()
        self._conn.commit()
        if row is None:
            return None
        return {"id": row[0], "spec": json.loads(row[1])}

    def finish(self, job_id: int, ok: bool, result: dict) -> None:
        status = "done" if ok else "failed"
        if self.backend == "sqlite":
            self._conn.execute(
                "UPDATE jobs SET status=?, result=?,"
                " finished_at=datetime('now') WHERE id=?",
                (status, json.dumps(result), job_id))
            self._conn.commit()
            return
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE jobs SET status=%s, result=%s, finished_at=now()"
            " WHERE id=%s", (status, json.dumps(result), job_id))
        self._conn.commit()

    def get(self, job_id: int) -> dict | None:
        if self.backend == "sqlite":
            row = self._conn.execute(
                "SELECT id, spec, status, result FROM jobs WHERE id=?",
                (job_id,)).fetchone()
        else:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, spec::text, status, result::text FROM jobs"
                " WHERE id=%s", (job_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return {"id": row[0], "spec": json.loads(row[1]), "status": row[2],
                "result": json.loads(row[3]) if row[3] else None}
