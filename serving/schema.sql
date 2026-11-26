-- Serving queue (Postgres). SQLite variant is built in queue.py for
-- local/CI unit tests; the columns and semantics are identical.
CREATE TABLE IF NOT EXISTS jobs (
    id          BIGSERIAL PRIMARY KEY,
    spec        JSONB NOT NULL,          -- plant seed + rolling spec
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
    result      JSONB,                   -- measured outcome + problems
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
