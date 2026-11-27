"""python -m serving: run the worker against DATABASE_URL (postgres DSN)
or a sqlite path (default :memory: is useless across processes - pass a
file path). Roles: API runs serving.api.serve_http separately; both
share the same jobs table.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from job_queue import JobQueue  # noqa: E402
from worker import serve  # noqa: E402

if __name__ == "__main__":
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn:
        q = JobQueue("postgres", dsn)
    else:
        q = JobQueue("sqlite", os.environ.get("SQLITE_PATH", "serving.db"))
    # hard per-job limit and stale-job sweep (0 disables either)
    t = float(os.environ.get("JOB_TIMEOUT_S", "3600"))
    s = float(os.environ.get("STALE_AFTER_S", "7200"))
    serve(q, job_timeout_s=t or None, stale_after_s=s or None)
