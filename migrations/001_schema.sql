-- Migration 001: Initial schema for media processing pipeline
-- Run with: psql $DATABASE_URL -f migrations/001_schema.sql

CREATE TABLE IF NOT EXISTS jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        TEXT NOT NULL,
    storage_key     TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    status          VARCHAR(20) DEFAULT 'queued',
    result          JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_jobs_status     ON jobs (status);
CREATE INDEX IF NOT EXISTS ix_jobs_created_at ON jobs (created_at DESC);
