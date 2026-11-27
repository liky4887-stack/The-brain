"""Serving hardening: input bounds at the door, stale-job sweep, per-job
watchdog timeout. Fail-before: n_skus=10**7 was accepted, a misspelt key
was silently ignored, a job left 'running' by a lost worker stayed
'running' forever, a hung solve blocked the worker."""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "serving"))
sys.path.insert(0, str(_ROOT / "packages" / "brain-core"))

import pytest  # noqa: E402


def test_spec_limits():
    from worker import validate_spec, run_job
    assert validate_spec({"seed": 1, "days": 14}) == []
    bad = validate_spec({"seed": "x", "n_skus": 10**7, "days": -1,
                         "utilization": float("nan")})
    assert len(bad) == 4
    typo = validate_spec({"seed": 1, "n_sku": 50})
    assert typo and "n_sku" in typo[0]
    r = run_job({"n_skus": 10**7})
    assert r["ok"] is False and r["status"] == "rejected"


def test_api_rejects_out_of_bounds_spec():
    import threading
    import urllib.error
    import urllib.request
    from api import serve_http
    from job_queue import JobQueue
    q = JobQueue("sqlite", ":memory:")
    srv = serve_http(q, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/jobs"
    req = urllib.request.Request(url, data=json.dumps(
        {"n_skus": 10**7}).encode(), method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400
    srv.shutdown()


def test_stale_running_job_is_closed_with_reason():
    from job_queue import JobQueue
    q = JobQueue("sqlite", ":memory:")
    jid = q.submit({"seed": 1})
    assert q.claim()["id"] == jid
    assert q.fail_stale(3600) == 0          # fresh claim: left alone
    q._conn.execute("UPDATE jobs SET claimed_at=datetime('now','-2 hours')")
    assert q.fail_stale(3600) == 1
    job = q.get(jid)
    assert job["status"] == "failed"
    assert "worker lost" in json.dumps(job["result"])


def test_worker_job_timeout_records_failure_and_survives():
    from job_queue import JobQueue
    from worker import serve
    q = JobQueue("sqlite", ":memory:")
    jid = q.submit({"seed": 1, "days": 7, "window_days": 7,
                    "freeze_days": 1})
    serve(q, once=True, poll_s=0.01, job_timeout_s=0.05)
    job = q.get(jid)
    assert job["status"] == "failed"
    assert "timeout" in json.dumps(job["result"])
