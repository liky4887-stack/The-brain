# serving - the brain behind a queue

Two-track architecture, one repo:

- **Track 1 (ladder)**: `benchmarks/` measures how far the brain scales on
  free compute, pushing PASS records to `gate-scale-results`.
- **Track 2 (this folder)**: serves the same brain behind a durable job
  queue. The worker calls the same `brain_core.rolling.solve_rolling`
  the ladder measures, so a served plan carries the same independent
  validation and honesty bar (`res.problems` empty or the job fails -
  no silent wrong answers).

Pieces: `schema.sql` (Postgres jobs table), `job_queue.py` (atomic claim;
postgres via pg8000 [BSD-3], sqlite twin for local/CI), `api.py`
(stdlib http.server: POST/GET `/jobs`, `/health`), `worker.py`
(claim -> generate factory from spec seed -> solve_rolling -> store
measured result), `Dockerfile.worker` (worker container).

Local: `python -m serving` (SQLite at $SQLITE_PATH, default
serving.db). Postgres: set `DATABASE_URL`. API: `python -c "from
serving.api import serve_http; from serving.job_queue import JobQueue;
serve_http(JobQueue('sqlite','serving.db'), port=8080).serve_forever()"`.

Note: GitHub Actions/Pages terms prohibit customer-facing hosting
(docs/DECISIONS.md) - production hosting of this layer is a separate
deployment decision; CI here only tests it.
