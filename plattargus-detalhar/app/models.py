from sqlalchemy import text

SQL_FIND_DEDUP_ACTIVE = text("""
SELECT job_id, status
FROM detalhar_jobs
WHERE dedup_key = :dedup_key
  AND status IN ('queued','running','retry')
ORDER BY created_at DESC
LIMIT 1
""")

SQL_FIND_DEDUP_DONE_TTL = text("""
SELECT job_id
FROM detalhar_jobs
WHERE dedup_key = :dedup_key
  AND status = 'done'
  AND finished_at >= (NOW() - (:ttl_seconds * INTERVAL '1 second'))
ORDER BY finished_at DESC
LIMIT 1
""")

SQL_INSERT_JOB = text("""
INSERT INTO detalhar_jobs (nup, sigla, chat_id, user_id, status, priority, max_attempts, dedup_key)
VALUES (:nup, :sigla, :chat_id, :user_id, 'queued', :priority, :max_attempts, :dedup_key)
RETURNING job_id
""")

SQL_BUMP_PRIORITY = text("""
UPDATE detalhar_jobs
SET priority = GREATEST(priority, :priority),
    updated_at = NOW()
WHERE job_id = :job_id
RETURNING job_id, status
""")

SQL_GET_JOB = text("""
SELECT job_id, nup, sigla, chat_id, user_id, status, priority, attempts, max_attempts,
       created_at, started_at, finished_at, next_run_at, error, result_path
FROM detalhar_jobs
WHERE job_id = :job_id
""")

SQL_GET_RESULT = text("""
SELECT result_json
FROM detalhar_jobs
WHERE job_id = :job_id AND status='done'
""")

SQL_GET_RESULT_PATH = text("""
SELECT result_path
FROM detalhar_jobs
WHERE job_id = :job_id AND status='done'
""")

SQL_LATEST_BY_NUP = text("""
SELECT job_id, status, finished_at
FROM detalhar_jobs
WHERE nup = :nup AND (CAST(:sigla AS TEXT) IS NULL OR sigla = :sigla)
ORDER BY created_at DESC
LIMIT 1
""")

SQL_LATEST_DONE_BY_NUP_TTL = text("""
SELECT job_id, finished_at
FROM detalhar_jobs
WHERE nup = :nup AND (CAST(:sigla AS TEXT) IS NULL OR sigla = :sigla)
  AND status='done'
  AND finished_at >= (NOW() - (:ttl_seconds * INTERVAL '1 second'))
ORDER BY finished_at DESC
LIMIT 1
""")

SQL_CLAIM_JOB = text("""
UPDATE detalhar_jobs
SET status='running',
    locked_by=:locked_by,
    locked_until = NOW() + (:lock_minutes * INTERVAL '1 minute'),
    attempts = attempts + 1,
    started_at = COALESCE(started_at, NOW()),
    updated_at = NOW()
WHERE job_id = :job_id
  AND status IN ('queued','retry')
  AND next_run_at <= NOW()
  AND (locked_until IS NULL OR locked_until < NOW())
RETURNING job_id, nup, sigla, chat_id, user_id, attempts, max_attempts
""")

SQL_FINISH_DONE = text("""
UPDATE detalhar_jobs
SET status='done',
    result_json=CAST(:result_json AS jsonb),
    result_path=:result_path,
    error=NULL,
    finished_at=NOW(),
    locked_by=NULL,
    locked_until=NULL,
    updated_at=NOW()
WHERE job_id=:job_id
""")

SQL_FINISH_RETRY = text("""
UPDATE detalhar_jobs
SET status='retry',
    error=:error,
    next_run_at = NOW() + (:delay_seconds * INTERVAL '1 second'),
    locked_by=NULL,
    locked_until=NULL,
    updated_at=NOW()
WHERE job_id=:job_id
""")

SQL_FINISH_ERROR = text("""
UPDATE detalhar_jobs
SET status='error',
    error=:error,
    finished_at=NOW(),
    locked_by=NULL,
    locked_until=NULL,
    updated_at=NOW()
WHERE job_id=:job_id
""")

SQL_REQUEUE_STALE = text("""
UPDATE detalhar_jobs
SET status='retry',
    error = COALESCE(error,'') || '\n[reaper] stale lock cleared',
    next_run_at = NOW() + (60 * INTERVAL '1 second'),
    locked_by=NULL,
    locked_until=NULL,
    updated_at=NOW()
WHERE status='running' AND locked_until IS NOT NULL AND locked_until < NOW()
RETURNING job_id
""")

# ========== ADICIONAR AO FINAL DO models.py ==========

# SQL para atualizar status_stage
SQL_UPDATE_STAGE = text("""
UPDATE detalhar_jobs
SET status_stage = :stage,
    updated_at = NOW()
WHERE job_id = :job_id
""")

# SQLs específicos para cada estágio com path
SQL_UPDATE_EXTRACTED = text("""
UPDATE detalhar_jobs
SET status_stage = 'extracted',
    result_path_raw = :path,
    updated_at = NOW()
WHERE job_id = :job_id
""")

SQL_UPDATE_ENRICHED = text("""
UPDATE detalhar_jobs
SET status_stage = 'enriched',
    result_path_enriched = :path,
    updated_at = NOW()
WHERE job_id = :job_id
""")

SQL_UPDATE_HEUR = text("""
UPDATE detalhar_jobs
SET status_stage = 'heur',
    heur_path = :path,
    updated_at = NOW()
WHERE job_id = :job_id
""")

SQL_UPDATE_TRIAGE = text("""
UPDATE detalhar_jobs
SET status_stage = 'triage',
    triage_path = :path,
    updated_at = NOW()
WHERE job_id = :job_id
""")

SQL_UPDATE_CASE = text("""
UPDATE detalhar_jobs
SET status_stage = 'case',
    case_path = :path,
    updated_at = NOW()
WHERE job_id = :job_id
""")

SQL_UPDATE_RESUMO = text("""
UPDATE detalhar_jobs
SET status_stage = 'resumo',
    resumo_path = :path,
    updated_at = NOW()
WHERE job_id = :job_id
""")
