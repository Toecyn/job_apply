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

-- Single-row user profile — replaces master_resume.json as the source of
-- truth for target titles, exclusions, scoring keywords, search markets,
-- and resume content. Single-tenant for now: id is always 1. Going
-- multi-tenant later means swapping id for a real account_id and dropping
-- the DEFAULT 1 / seed row below.
--
-- target_titles, exclude_keywords, score_keywords, markets, resume_json
-- hold JSON, stored as TEXT and hand-encoded/decoded in profile_store.py —
-- matching how jobs.score_reasons/score_gaps already do it in this schema,
-- rather than introducing native jsonb handling for just one table.
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY DEFAULT 1,
    target_titles TEXT DEFAULT '[]',
    exclude_keywords TEXT DEFAULT '[]',
    score_keywords TEXT DEFAULT '[]',
    markets TEXT DEFAULT '[]',
    open_to_remote INTEGER DEFAULT 1,
    visa_required INTEGER DEFAULT 0,
    country TEXT DEFAULT 'canada',
    min_score_default INTEGER DEFAULT 70,
    stale_days INTEGER DEFAULT 7,
    brand_color TEXT DEFAULT '1F4E79',
    resume_json TEXT DEFAULT NULL,
    resume_file_url TEXT DEFAULT NULL,
    resume_filename TEXT DEFAULT NULL,
    updated_at TEXT
);

-- Seed the single row so get_profile() always has something to read/upsert
-- against, even before anyone has visited /settings.
INSERT INTO profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Generating a tailored resume (Claude call + docx build + blob upload) runs
-- too long for Vercel's serverless timeout, so it now runs in a GitHub
-- Actions workflow (see .github/workflows/tailor.yml / cron_tailor.py)
-- dispatched by /api/jobs/<id>/tailor, with the dashboard polling
-- /api/jobs/<id>/tailor-status for this column: JSON like
-- {"status": "pending"} while running, {"status": "done", ...result} or
-- {"status": "error", "error": "..."} once the workflow finishes.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tailor_result TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_is_stale ON jobs (is_stale);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (score);
CREATE INDEX IF NOT EXISTS idx_jobs_search_pass ON jobs (search_pass);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_date_found ON jobs (date_found);
CREATE INDEX IF NOT EXISTS idx_ai_calls_timestamp ON ai_calls (timestamp);
