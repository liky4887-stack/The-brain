-- Canonical factory records: Postgres DDL (Stage 1 data foundation).
-- Mirrors brain_core.records.models one table per record type.
-- frePPLe stays the data/screens layer; this is The-brain's own
-- system of record for the compiler. Durations are seconds (bigint),
-- timestamps timestamptz.

CREATE TABLE IF NOT EXISTS location (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    available_calendar TEXT
);

CREATE TABLE IF NOT EXISTS item (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    cost DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS calendar (
    name TEXT PRIMARY KEY,
    default_value DOUBLE PRECISION NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS calendar_bucket (
    calendar TEXT NOT NULL REFERENCES calendar(name),
    starts TIMESTAMPTZ NOT NULL,
    ends TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    CHECK (ends > starts),
    CHECK (value >= 0)
);

CREATE TABLE IF NOT EXISTS setup_matrix (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS setup_rule (
    setup_matrix TEXT NOT NULL REFERENCES setup_matrix(name),
    from_setup TEXT NOT NULL,
    to_setup TEXT NOT NULL,
    duration_seconds BIGINT NOT NULL CHECK (duration_seconds >= 0),
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (setup_matrix, from_setup, to_setup)
);

CREATE TABLE IF NOT EXISTS resource (
    name TEXT PRIMARY KEY,
    location TEXT REFERENCES location(name),
    maximum DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK (maximum > 0),
    maximum_calendar TEXT REFERENCES calendar(name),
    setup_matrix TEXT REFERENCES setup_matrix(name),
    efficiency DOUBLE PRECISION NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS operation (
    name TEXT PRIMARY KEY,
    item TEXT REFERENCES item(name),
    location TEXT REFERENCES location(name),
    duration_seconds BIGINT NOT NULL DEFAULT 0 CHECK (duration_seconds >= 0),
    duration_per_seconds BIGINT NOT NULL DEFAULT 0 CHECK (duration_per_seconds >= 0),
    size_minimum DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK (size_minimum > 0),
    size_multiple DOUBLE PRECISION,
    size_maximum DOUBLE PRECISION,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    effective_start TIMESTAMPTZ,
    effective_end TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS operation_material (
    operation TEXT NOT NULL REFERENCES operation(name),
    item TEXT NOT NULL REFERENCES item(name),
    quantity DOUBLE PRECISION NOT NULL CHECK (quantity <> 0),
    PRIMARY KEY (operation, item)
);

CREATE TABLE IF NOT EXISTS operation_resource (
    operation TEXT NOT NULL REFERENCES operation(name),
    resource TEXT NOT NULL REFERENCES resource(name),
    quantity DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK (quantity > 0),
    setup TEXT,
    skill TEXT,
    PRIMARY KEY (operation, resource)
);

CREATE TABLE IF NOT EXISTS buffer (
    item TEXT NOT NULL REFERENCES item(name),
    location TEXT NOT NULL REFERENCES location(name),
    onhand DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (onhand >= 0),
    minimum DOUBLE PRECISION NOT NULL DEFAULT 0,
    maximum DOUBLE PRECISION,
    PRIMARY KEY (item, location)
);

CREATE TABLE IF NOT EXISTS demand (
    name TEXT PRIMARY KEY,
    item TEXT NOT NULL REFERENCES item(name),
    location TEXT REFERENCES location(name),
    due TIMESTAMPTZ NOT NULL,
    quantity DOUBLE PRECISION NOT NULL CHECK (quantity > 0),
    priority INTEGER NOT NULL DEFAULT 1 CHECK (priority >= 0),
    minshipment DOUBLE PRECISION,
    maxlateness_seconds BIGINT
);
