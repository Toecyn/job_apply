# Operational Change Log

Every entry follows this format:
Date | Problem (with number) | Root cause | Fix | Result | Enterprise pattern demonstrated

---

## 2026-05-05 — Description coverage validation
**Problem:** 1,374 of 3,669 active jobs (37%) had empty or short descriptions. Tailor Resume button failed silently with no explanation.
**Root cause:** LinkedIn blocks description scraping on some postings. Scraper saved metadata but stored 3-character placeholder as description.
**Fix:** Added description length validation to dashboard. Jobs under 50 characters flagged with No description badge. Tailor button hidden on affected jobs.
**Result:** Zero wasted API calls on empty descriptions. User sees the problem before clicking.
**Pattern:** Input validation before AI pipeline entry. Never pass unvalidated data to an AI call.

---

## 2026-05-05 — Evidence-based scheduler
**Problem:** Scheduler running every 3 hours on fixed interval regardless of when jobs are actually posted.
**Root cause:** Interval trigger does not account for peak posting times on Indeed and LinkedIn.
**Fix:** Replaced IntervalTrigger with 4 CronTrigger runs at 7:30am, 10am, 4pm, 8pm based on job board research showing first-day applicants are 10% more likely to get the role.
**Result:** Scrapes now aligned with peak posting windows. Fresh jobs surfaced faster.
**Pattern:** Evidence-based scheduling. Operational decisions should be backed by data, not defaults.

---

## 2026-05-05 — Bullet reservoir architecture
**Problem:** Resume tailoring system had no structured source of truth. Bullets were written fresh each time with no consistency or reuse.
**Root cause:** master_resume.json contained outdated April bullets not reflecting confirmed, defensible experience.
**Fix:** Rebuilt master_resume.json with 34 confirmed bullets across 4 companies, each tagged by skill and industry context. Tailor system now selects from reservoir rather than generating from scratch.
**Result:** Every bullet in circulation has been confirmed defensible in interview context. Tailoring quality now consistent across all applications.
**Pattern:** Structured knowledge base as AI input. Garbage in garbage out — AI output quality is bounded by input quality.

---

## 2026-05-05 — GitHub repository initialised
**Problem:** No version control. System changes untracked. No portfolio evidence of operational thinking.
**Root cause:** System built iteratively across sessions with no commit history.
**Fix:** Initialised Git repository, added .gitignore excluding .env, tracker.db, node_modules, and output resumes. Pushed to GitHub.
**Result:** Full commit history going forward. Portfolio visible at github.com/holukayodeh/job-intelligence-pipeline.
**Pattern:** Operational systems need audit trails. Version control is the minimum viable audit trail.

---

## 2026-05-05 — Follow-up opportunities system
**Problem:** No mechanism to detect other open roles at companies already applied to.
**Root cause:** Application tracking was status-only with no company intelligence layer.
**Fix:** Added applied_companies table to tracker.db. When job marked applied, system queries for fresh roles at same company within 72hrs. Dashboard shows follow-up panel with Reuse resume button.
**Result:** Reuse resume function copies existing resume and swaps only header location to match new JD. Zero tailoring effort for same-company follow-ups.
**Pattern:** State management in operational AI systems. Every user action should trigger downstream intelligence.

---

## 2026-05-05 — Resume reservoir linked to jobs
**Problem:** 10 resumes in output folder, 0 linked to job records in database. Follow-up and reuse systems cannot function without resume path linkage.
**Root cause:** Early resumes built manually outside dashboard before resume_path column existed.
**Fix:** Added resume_path column to jobs table. Dashboard now stores resume path automatically when Tailor Resume completes. Applied status update triggers company recording in applied_companies table.
**Result:** Full resume audit trail going forward. Every application has a linked resume record.
**Pattern:** Referential integrity in operational data. AI system outputs must be traceable back to their inputs.

---

## 2026-05-06 — Scheduler running as background process
**Problem:** Scheduler only ran when manually started in a separate terminal. Dashboard and scheduler could not start together.
**Root cause:** start.sh only launched the dashboard. Scheduler required a second manual terminal window.
**Fix:** Updated start.sh to launch scheduler as a background process using & before starting the dashboard. Both now start with one command.
**Result:** System fully autonomous. Scheduler fires at 7:30am, 10am, 4pm, 8pm daily without manual intervention.
**Pattern:** Operational autonomy. A system that requires manual intervention is not production-ready.

---

## 2026-05-06 — Observability layer added
**Problem:** Every Claude API call was a black box. No record of latency, cost, token usage, or failures. System could not be monitored, audited, or improved with data.
**Root cause:** Direct client.messages.create() calls with no instrumentation wrapper.
**Fix:** Built ai_logger.py with call_claude_with_logging() wrapper and retry logic. Added ai_calls table to tracker.db. Wired into scorer.py and tailor.py. Fixed areas_of_expertise key mismatch between scorer and updated master_resume.json.
**Result:** First logged call: score | 2,260 input tokens | 151 output tokens | 5,130ms latency | $0.009 cost | Success. Scoring 200 jobs costs ~$1.80.
**Pattern:** Observability before optimisation. You cannot improve what you cannot measure.

---

## 2026-05-06 — Governance dashboard live
**Problem:** No visibility into AI system health. Could not answer basic operational questions — how many calls today, what did it cost, what failed.
**Root cause:** No monitoring layer existed. System operated as a black box.
**Fix:** Built /governance page in Flask showing today's calls, cost, success rate, latency by call type, recent call log, and failure history. Linked from main dashboard header.
**Result:** Can now answer in real time: total AI calls, cost per day, success rate, average latency per call type. First data point: score call averages 5,130ms at $0.009 per job.
**Pattern:** Operational visibility. Enterprise AI systems must be observable by non-engineers. A governance page is the minimum viable monitoring interface.

---

## 2026-05-06 — Governance dashboard live
**Problem:** No visibility into AI system health. Could not answer basic operational questions — how many calls today, what did it cost, what failed.
**Root cause:** No monitoring layer existed. System operated as a black box.
**Fix:** Built /governance page in Flask showing today's calls, cost, success rate, latency by call type, recent call log, and failure history. Linked from main dashboard header.
**Result:** Can now answer in real time: total AI calls, cost per day, success rate, average latency per call type. First data point: score call averages 5,130ms at $0.009 per job.
**Pattern:** Operational visibility. Enterprise AI systems must be observable by non-engineers. A governance page is the minimum viable monitoring interface.

---

## 2026-05-06 — Test suite added and README updated
**Problem:** No automated way to verify system integrity after changes. A broken file or missing column could fail silently.
**Root cause:** System built iteratively with no validation layer.
**Fix:** Built test_system.py with 114 tests across 6 categories — core files, resume integrity, database schema, observability layer, scorer, and environment. Updated README to link CHANGELOG and document operational stats.
**Result:** 113/114 passing on first run. One failure identified — 189 unscored jobs from overnight scheduler run. Fixed immediately by running score_all_unscored(). 114/114 after fix.
**Pattern:** Test-driven operations. Enterprise AI systems need automated integrity checks. A test suite is the difference between a demo and a production system.

---

## 2026-05-06 — Resume formatting locked to CBC standard
**Problem:** Generated resumes had wrong font sizes (19pt name, 10.5pt headers, 9.5pt body), spilled to 3 pages, wrong role order, MBA in subtitle.
**Root cause:** build_docx.js was reading sizes from FORMAT_SPEC in tailor.py which had incorrect values. Sizes not extracted from actual CBC resume.
**Fix:** Extracted exact sizes from CBC resume XML. Locked: 26pt name, 12pt section headers, 10.5pt body, 10pt competencies. Enforced bullet caps: BMO 7, Docebo 5, Rogers 6, Nestle 4. Fixed role order to BMO, Docebo, Rogers, Nestle. Removed MBA from subtitle. Added detect_location() to mirror JD location in header automatically.
**Result:** 2-page resume, correct fonts throughout, location auto-detected from JD, no MBA in title line.
**Pattern:** Extract formatting specs from source of truth, never hardcode from memory. Test with python-docx to verify actual rendered sizes.

---

## 2026-05-06 — AI cost optimisation: model routing and description filtering
**Problem:** Scoring was 95% of AI spend at $0.009 per call across 977 calls totalling $9.06. No model differentiation — everything running on Sonnet regardless of task complexity.
**Root cause:** Single model hardcoded for all call types. Logger using flat Sonnet pricing regardless of which model was actually called. No minimum description quality threshold.
**Fix:** Switched scorer to claude-haiku-4-5-20251001. Updated ai_logger.py with model-aware pricing dictionary. Raised description minimum to length >= 200 characters.
**Result:** Cost per score call dropped from $0.009 to $0.004 — 55% reduction. Scoring 200 jobs now costs $0.81 versus $1.80 previously.
**Pattern:** Model routing and cost-aware AI operations. Match model capability to task complexity.
