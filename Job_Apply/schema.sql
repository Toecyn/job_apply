CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT,
    company TEXT,
    location TEXT,
    source TEXT,
    date_posted TEXT,
    date_found TEXT,
    job_url TEXT,
    description TEXT,
    score INTEGER DEFAULT NULL,
    score_reasons TEXT DEFAULT NULL,
    score_gaps TEXT DEFAULT NULL,
    status TEXT DEFAULT 'new',
    is_stale INTEGER DEFAULT 0,
    country TEXT DEFAULT 'canada',
    is_remote INTEGER DEFAULT 0,
    visa_required INTEGER DEFAULT 0,
    search_pass TEXT DEFAULT 'canada',
    resume_path TEXT DEFAULT NULL,
    batch_id TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS applied_companies (
    id SERIAL PRIMARY KEY,
    company TEXT NOT NULL,
    job_id TEXT NOT NULL,
    resume_path TEXT,
    date_applied TEXT
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    call_type TEXT,
    job_id TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    cost_usd REAL,
    success INTEGER,
    error_text TEXT,
    output_preview TEXT
);

CREATE TABLE IF NOT EXISTS batch_jobs (
    batch_id TEXT PRIMARY KEY,
    submitted_at TEXT,
    job_count INTEGER,
    status TEXT,
    completed_at TEXT,
    jobs_scored INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_is_stale ON jobs (is_stale);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (score);
CREATE INDEX IF NOT EXISTS idx_jobs_search_pass ON jobs (search_pass);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_date_found ON jobs (date_found);
CREATE INDEX IF NOT EXISTS idx_ai_calls_timestamp ON ai_calls (timestamp);
