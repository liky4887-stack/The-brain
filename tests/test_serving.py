"""Serving layer: queue semantics (sqlite) + worker end-to-end through
the real brain_core rolling solver + API round-trip. The postgres path
runs in CI via the serving workflow's postgres service; sqlite keeps the
unit contract identical so a queue regression fails fast everywhere.
"""

import json
import os
import sys
import threading
import urllib.request

from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages" / "brain-core"))  # pinned: bare source dir, repo convention
sys.path.insert(0, str(_ROOT / "serving"))

from job_queue import JobQueue  # noqa: E402
from worker import run_job, serve  # noqa: E402
from api import serve_http  # noqa: E402


def test_submit_claim_finish_cycle():
    q = JobQueue("sqlite", ":memory:")
    jid = q.submit({"seed": 1})
    assert q.get(jid)["status"] == "queued"
    job = q.claim()
    assert job == {"id": jid, "spec": {"seed": 1}}
    assert q.claim() is None  # nothing left to claim
    q.finish(jid, True, {"ok": True, "assignments": 5})
    got = q.get(jid)
    assert got["status"] == "done"
    assert got["result"]["assignments"] == 5


def test_claim_is_atomic_under_two_workers():
    q = JobQueue("sqlite", ":memory:")
    for i in range(3):
        q.submit({"seed": i})
    taken = {q.claim()["id"] for _ in range(3)}
    assert len(taken) == 3  # no double-claim, no loss


def test_worker_runs_the_brain_and_validates():
    q = JobQueue("sqlite", ":memory:")
    jid = q.submit({"seed": 3, "n_skus": 12, "n_lines": 2, "days": 6,
                    "window_days": 6, "freeze_days": 3, "n_windows": 2})
    serve(q, once=True)
    got = q.get(jid)
    assert got["status"] == "done"
    r = got["result"]
    assert r["ok"] is True and r["problems"] == []
    assert r["assignments"] > 0
    assert r["solve_s"] > 0  # measured, not fabricated


def test_worker_records_failure_honestly():
    q = JobQueue("sqlite", ":memory:")
    # window_days < freeze_days violates solve_rolling's contract;
    # the crash must land in the record, not vanish.
    jid = q.submit({"seed": 1, "window_days": 1, "freeze_days": 3})
    serve(q, once=True)
    got = q.get(jid)
    assert got["status"] == "failed"
    assert any("worker exception" in p for p in got["result"]["problems"])


def test_api_submit_and_read_back(tmp_path):
    q = JobQueue("sqlite", ":memory:")
    httpd = serve_http(q, port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/jobs",
            data=json.dumps({"seed": 7, "n_skus": 10}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 201
            jid = json.load(resp)["id"]
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/jobs/{jid}") as resp:
            job = json.load(resp)
        assert job["spec"]["seed"] == 7
        assert job["status"] == "queued"
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health") as resp:
            assert json.load(resp)["ok"] is True
    finally:
        httpd.shutdown()
