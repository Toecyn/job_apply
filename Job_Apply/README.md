# Job Intelligence Pipeline

An automated job search and application system built to surface strong matches, score them using AI, and generate tailored resumes at scale.

## What it does
- Scrapes Indeed and LinkedIn across 4 markets (Canada, Ottawa, US Remote, Financial Services)
- Scores every job using Claude AI across 5 dimensions — role fit, tools, location, seniority, employment type
- Surfaces strong matches (70+) in a real-time dashboard with filters
- Generates tailored resumes using a 3-tier system based on job score
- Tracks applications and surfaces follow-up opportunities at the same company
- Runs on an evidence-based schedule — 7:30am, 10am, 4pm, 8pm daily

## Architecture
- `scraper.py` — multi-pass job scraper with deduplication
- `scorer.py` — 5-dimension Claude API scorer with observability logging
- `tailor.py` — 3-tier resume tailoring with intake system and retry logic
- `app.py` — Flask dashboard with follow-up opportunities and governance page
- `scheduler.py` — evidence-based CronTrigger automation
- `ai_logger.py` — observability wrapper logging every AI call with latency, cost, and success rate
- `master_resume.json` — 34-bullet reservoir across 4 companies

## Operational stats
- 3,669 active jobs in database
- 545 jobs scoring 70+
- 37 jobs scoring 80+ fresh in last 72hrs
- 37% description coverage gap identified and flagged
- AI call logging: score calls average 5,130ms at $0.009 per job

## Governance
Every Claude API call is logged with latency, token usage, cost, and success status.
A live governance dashboard is available at `/governance` showing system health in real time.

## Operational change log
Every meaningful system change is documented with problem, root cause, fix, result, and enterprise pattern.
See [CHANGELOG.md](CHANGELOG.md) for the full operational history.

## Stack
Python, Flask, SQLite, APScheduler, Claude API (Anthropic), Node.js (docx generation)

## Setup
```bash
cp .env.example .env  # add your ANTHROPIC_API_KEY
pip install -r requirements.txt
./start.sh
```
