CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS detalhar_jobs (
  job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  nup VARCHAR(50) NOT NULL,
  sigla VARCHAR(20),
  chat_id VARCHAR(50),
  user_id VARCHAR(50),

  status VARCHAR(20) NOT NULL DEFAULT 'queued', -- queued,running,done,retry,error,canceled
  priority INT NOT NULL DEFAULT 5,

  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,

  next_run_at TIMESTAMP NOT NULL DEFAULT NOW(),

  locked_by VARCHAR(80),
  locked_until TIMESTAMP,

  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

  result_json JSONB,
  result_path TEXT,

  error TEXT,

  dedup_key TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_pick
  ON detalhar_jobs(status, next_run_at, priority DESC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_jobs_nup
  ON detalhar_jobs(nup, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_dedup
  ON detalhar_jobs(dedup_key, created_at DESC);
