import json
import os
from urllib.parse import quote
from flask import Flask, render_template, jsonify, request, redirect
from dotenv import load_dotenv
from db import get_db, init_db

load_dotenv()

app = Flask(__name__)

# Ensure the schema (including the profile table) exists before any route
# runs. Previously this only ran as a side effect of a scrape, or in the
# local `python app.py` dev block below — neither of which fires on
# Vercel's cold start, so a fresh deploy's Settings page would 500 on
# save until someone happened to trigger a scrape first. Idempotent
# (CREATE TABLE IF NOT EXISTS / INSERT ... ON CONFLICT DO NOTHING), so
# running it on every cold start is safe and cheap.
try:
    init_db()
except Exception as e:
    print(f"init_db() at startup failed (DATABASE_URL unset locally, etc.): {e}")


def get_jobs_data(status="all", market="all", min_score=70, fresh_hours=72):
    conn = get_db()
    query = "SELECT * FROM jobs WHERE is_stale = 0"
    params = []
    if status != "all":
        query += " AND status = %s"
        params.append(status)
    if min_score > 0:
        query += " AND score >= %s"
        params.append(min_score)
    if market != "all":
        query += " AND search_pass = %s"
        params.append(market)
    if fresh_hours and fresh_hours > 0:
        query += " AND date_found >= to_char(NOW() - %s::interval, 'YYYY-MM-DD HH24:MI:SS')"
        params.append(f"{fresh_hours} hours")
    query += " ORDER BY score DESC LIMIT 50"
    jobs = conn.execute(query, params).fetchall()
    conn.close()
    result = []
    for job in jobs:
        j = dict(job)
        for f in ["score_reasons", "score_gaps"]:
            if j.get(f):
                try:
                    j[f] = json.loads(j[f])
                except Exception:
                    j[f] = []
        result.append(j)
    return result


def get_stats_data():
    """Per-market counts (stats["markets"]) are now driven by the profile's
    configured markets instead of a fixed canada/ottawa/us_remote set —
    see profile_store.market_pass_name(). A market you've since removed
    from Settings, or a job scraped under the old hardcoded passes before
    this migration, simply won't appear in this list; it still counts
    toward total/scored/etc. and still shows in the "All markets" job list."""
    from profile_store import get_profile, market_pass_name, market_label

    conn = get_db()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM jobs WHERE is_stale = 0").fetchone()[0],
        "scored": conn.execute("SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL AND is_stale = 0").fetchone()[0],
        "high_match": conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 70 AND is_stale = 0").fetchone()[0],
        "applied": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'").fetchone()[0],
        "fresh": conn.execute("SELECT COUNT(*) FROM jobs WHERE date_found >= to_char(NOW() - INTERVAL '3 days', 'YYYY-MM-DD HH24:MI:SS') AND is_stale = 0").fetchone()[0],
        "fresh_scored": conn.execute("SELECT COUNT(*) FROM jobs WHERE date_found >= to_char(NOW() - INTERVAL '3 days', 'YYYY-MM-DD HH24:MI:SS') AND score >= 70 AND is_stale = 0").fetchone()[0],
    }

    profile = get_profile()
    markets = []
    for market in (profile or {}).get("markets", []):
        pass_name = market_pass_name(market)
        count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE search_pass = %s AND is_stale = 0", (pass_name,)
        ).fetchone()[0]
        markets.append({"pass_name": pass_name, "label": market_label(market), "count": count})
    stats["markets"] = markets

    conn.close()
    return stats


@app.route("/")
def index():
    status = request.args.get("status", "all")
    market = request.args.get("market", "all")
    min_score = int(request.args.get("min_score", 70))
    fresh_hours = int(request.args.get("fresh_hours", 72))
    jobs = get_jobs_data(status, market, min_score, fresh_hours)
    stats = get_stats_data()
    return render_template("index.html",
        jobs=jobs, stats=stats,
        filters={"status": status, "market": market, "min_score": min_score, "fresh_hours": fresh_hours},
        refresh_ok=request.args.get("refresh_ok"),
        refresh_scored=request.args.get("refresh_scored"),
        refresh_error=request.args.get("refresh_error"),
    )


@app.route("/status/<job_id>", methods=["POST"])
def update_status(job_id):
    new_status = request.form.get("status")
    resume_path = request.form.get("resume_path", "")
    valid = ["new", "reviewing", "applied", "interviewing", "rejected", "offer"]
    if new_status in valid:
        conn = get_db()
        conn.execute("UPDATE jobs SET status = %s WHERE id = %s", (new_status, job_id))

        # If marking as applied — record company and resume
        if new_status == "applied":
            job = conn.execute("SELECT company, resume_path FROM jobs WHERE id = %s", (job_id,)).fetchone()
            if job:
                company = job["company"]
                used_resume = resume_path or job["resume_path"] or ""
                # Record in applied_companies
                conn.execute(
                    "INSERT INTO applied_companies (company, job_id, resume_path, date_applied) VALUES (%s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))",
                    (company, job_id, used_resume)
                )
                if used_resume:
                    conn.execute("UPDATE jobs SET resume_path = %s WHERE id = %s", (used_resume, job_id))

        conn.commit()
        conn.close()
    return redirect(request.referrer or "/")


@app.route("/refresh", methods=["POST"])
def refresh():
    """Was silently swallowing every failure here — a missing dependency,
    a scrape timeout, an unconfigured profile, anything — and just
    redirecting back to a page that looked unchanged, with the real reason
    only ever reaching the server log. Now passes a status message through
    as a query param so index.html can actually show what happened."""
    scored = 0
    try:
        from scraper import run_scrape
        new_jobs = run_scrape()
        if new_jobs > 0:
            try:
                from scorer import score_all_unscored
                scored = score_all_unscored()
            except Exception as e:
                print(f"Scoring error: {e}")
                return redirect(f"/?refresh_ok={new_jobs}&refresh_scored={scored}&refresh_error={quote(f'Found {new_jobs} jobs but scoring failed: {e}')}")
        return redirect(f"/?refresh_ok={new_jobs}&refresh_scored={scored}")
    except Exception as e:
        print(f"Refresh error: {e}")
        return redirect(f"/?refresh_error={quote(str(e))}")


@app.route("/tailor/<job_id>", methods=["POST"])
def tailor(job_id):
    try:
        from tailor import tailor_for_job, build_tailored_docx
        result = tailor_for_job(job_id)
        if "error" not in result:
            docx = build_tailored_docx(result)
            if docx.get("success"):
                # Store resume path against job
                conn = get_db()
                conn.execute("UPDATE jobs SET resume_path = %s WHERE id = %s", (docx["path"], job_id))
                conn.commit()
                conn.close()
    except Exception as e:
        print(f"Tailor error: {e}")
    return redirect(request.referrer or "/")


# ── JSON API endpoints ──

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats_data())


@app.route("/api/jobs")
def api_jobs():
    status = request.args.get("status", "all")
    market = request.args.get("search_pass", "all")
    min_score = int(request.args.get("min_score", 70))
    fresh_hours = int(request.args.get("fresh_hours", 72))
    jobs = get_jobs_data(status, market, min_score, fresh_hours)
    return jsonify(jobs)


@app.route("/api/jobs/<job_id>/status", methods=["POST"])
def api_update_status(job_id):
    data = request.json or {}
    new_status = data.get("status")
    resume_path = data.get("resume_path", "")
    valid = ["new", "reviewing", "applied", "interviewing", "rejected", "offer"]
    if new_status in valid:
        conn = get_db()
        conn.execute("UPDATE jobs SET status = %s WHERE id = %s", (new_status, job_id))
        if new_status == "applied":
            job = conn.execute("SELECT company, resume_path FROM jobs WHERE id = %s", (job_id,)).fetchone()
            if job:
                company = job["company"]
                used_resume = resume_path or job["resume_path"] or ""
                conn.execute(
                    "INSERT INTO applied_companies (company, job_id, resume_path, date_applied) VALUES (%s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))",
                    (company, job_id, used_resume)
                )
                if used_resume:
                    conn.execute("UPDATE jobs SET resume_path = %s WHERE id = %s", (used_resume, job_id))
        conn.commit()
        conn.close()
    return jsonify({"success": True})


@app.route("/api/jobs/<job_id>/follow-up")
def api_follow_up(job_id):
    """Return fresh roles at the same company posted within 72hrs."""
    conn = get_db()
    source_job = conn.execute("SELECT company, resume_path FROM jobs WHERE id = %s", (job_id,)).fetchone()
    if not source_job:
        conn.close()
        return jsonify([])

    company = source_job["company"]
    resume_path = source_job["resume_path"]

    follow_ups = conn.execute("""
        SELECT id, title, company, location, score, search_pass,
               date_found, job_url, status, resume_path
        FROM jobs
        WHERE company = %s
        AND id != %s
        AND status != 'applied'
        AND is_stale = 0
        AND date_found >= to_char(NOW() - INTERVAL '3 days', 'YYYY-MM-DD HH24:MI:SS')
        ORDER BY score DESC
        LIMIT 5
    """, (company, job_id)).fetchall()
    conn.close()

    return jsonify({
        "company": company,
        "source_resume": resume_path,
        "follow_ups": [dict(j) for j in follow_ups]
    })


@app.route("/api/jobs/<job_id>/reuse-resume", methods=["POST"])
def api_reuse_resume(job_id):
    """Reuse resume from source job for this job, swapping location only."""
    data = request.json or {}
    source_job_id = data.get("source_job_id")
    if not source_job_id:
        return jsonify({"error": "source_job_id required"}), 400
    try:
        from tailor import reuse_resume
        result = reuse_resume(source_job_id, job_id)
        if result.get("success"):
            # Store the new resume path
            conn = get_db()
            conn.execute("UPDATE jobs SET resume_path = %s WHERE id = %s", (result["path"], job_id))
            conn.commit()
            conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh/scrape", methods=["POST"])
def api_refresh_scrape():
    """Scrape exactly one market (index `i`, 0-based). One request per market
    instead of one request for the whole profile — a full scrape across every
    market plus scoring was blowing past Vercel's 60s function timeout every
    time (confirmed in runtime logs: it never even finished market 1 of 3).
    The dashboard's Refresh Jobs button calls this once per configured market."""
    try:
        i = int(request.args.get("i", 0))
        from scraper import run_scrape_market
        return jsonify(run_scrape_market(i))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh/score", methods=["POST"])
def api_refresh_score():
    """Score up to `limit` unscored jobs (one live Claude call each) and
    report how many are still left, so the dashboard can keep calling this
    in a loop instead of one unbounded call that can time out mid-batch."""
    try:
        limit = int(request.args.get("limit", 12))
        from scorer import score_all_unscored, count_unscored
        scored = score_all_unscored(limit=limit)
        remaining = count_unscored()
        return jsonify({"scored": scored, "remaining": remaining})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        from scraper import run_scrape
        new_jobs = run_scrape()
        scored = 0
        if new_jobs > 0:
            try:
                from scorer import score_all_unscored
                scored = score_all_unscored()
            except Exception as e:
                print(f"Scoring error: {e}")
        return jsonify({"success": True, "new_jobs": new_jobs, "scored": scored})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jobs/<job_id>/intake", methods=["POST"])
def job_intake(job_id):
    try:
        from tailor import run_intake
        return jsonify(run_intake(job_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jobs/<job_id>/tailor", methods=["POST"])
def api_tailor(job_id):
    try:
        from tailor import tailor_for_job, build_tailored_docx
        data = request.json or {}
        intake_answers = data.get("intake_answers", None)
        result = tailor_for_job(job_id, intake_answers=intake_answers)
        if "error" in result:
            return jsonify(result), 500
        docx_result = build_tailored_docx(result)
        if docx_result.get("success"):
            conn = get_db()
            conn.execute("UPDATE jobs SET resume_path = %s WHERE id = %s", (docx_result["path"], job_id))
            conn.commit()
            conn.close()
        result["docx"] = docx_result
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/governance")
def governance():
    conn = get_db()
    total_calls = conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0]
    today_calls = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE timestamp >= to_char(CURRENT_DATE, 'YYYY-MM-DD')").fetchone()[0]
    today_cost = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_calls WHERE timestamp >= to_char(CURRENT_DATE, 'YYYY-MM-DD')").fetchone()[0]
    today_success = conn.execute("SELECT COALESCE(AVG(success),0)*100 FROM ai_calls WHERE timestamp >= to_char(CURRENT_DATE, 'YYYY-MM-DD')").fetchone()[0]
    week_calls = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE timestamp >= to_char(CURRENT_DATE - INTERVAL '7 days', 'YYYY-MM-DD')").fetchone()[0]
    week_cost = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_calls WHERE timestamp >= to_char(CURRENT_DATE - INTERVAL '7 days', 'YYYY-MM-DD')").fetchone()[0]
    latency = conn.execute("SELECT call_type, ROUND(AVG(latency_ms),0), COUNT(*) FROM ai_calls GROUP BY call_type").fetchall()
    failures = conn.execute("SELECT timestamp, call_type, job_id, error_text FROM ai_calls WHERE success = 0 ORDER BY timestamp DESC LIMIT 5").fetchall()
    recent = conn.execute("SELECT timestamp, call_type, latency_ms, cost_usd, success FROM ai_calls ORDER BY timestamp DESC LIMIT 10").fetchall()
    conn.close()
    return render_template("governance.html",
        total_calls=total_calls,
        today_calls=today_calls,
        today_cost=round(today_cost, 4),
        today_success=round(today_success, 1),
        week_calls=week_calls,
        week_cost=round(week_cost, 4),
        latency=latency,
        failures=failures,
        recent=recent
    )


@app.route("/skills")
def skills():
    import json
    try:
        data = json.load(open("data/skills.json"))
        skills_list = data.get("skills", [])
        concepts = list(set(s["enterprise_concept"] for s in skills_list))
        questions_count = sum(len(s["interview_questions"]) for s in skills_list)
        return render_template("skills.html",
            skills=skills_list,
            concepts=concepts,
            questions_count=questions_count,
            concepts_count=len(concepts)
        )
    except Exception as e:
        return render_template("skills.html",
            skills=[], concepts=[], questions_count=0, concepts_count=0
        )

@app.route("/api/skills/<skill_id>/refine", methods=["POST"])
def refine_skill_answer(skill_id):
    import json
    try:
        data = json.load(open("data/skills.json"))
        skill = next((s for s in data["skills"] if s["id"] == skill_id), None)
        if not skill:
            return jsonify({"error": "Skill not found"}), 404
        from ai_logger import call_claude_with_logging, extract_text
        from anthropic import Anthropic
        client = Anthropic()
        prompt = f"""You are a career coach helping a senior analytics professional prepare for enterprise AI operator roles.

Refine this STAR format interview answer to make it more concise, confident, and specific. 
Keep all the real details. Remove any filler. Make it sound like someone who knows exactly what they did and why it mattered.
Keep it under 150 words.

Enterprise concept: {skill["enterprise_concept"]}
Current answer: {skill["star_answer"]}

Return only the refined answer, no preamble."""

        response = call_claude_with_logging(
            client=client,
            call_type="skills_refine",
            job_id=skill_id,
            model="claude-sonnet-5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        refined = extract_text(response.content).strip()
        return jsonify({"refined": refined})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/simulate")
def simulate():
    import json
    try:
        data = json.load(open("data/skills.json"))
        companies = data.get("target_companies", [])
        return render_template("simulate.html", companies=companies)
    except Exception as e:
        return render_template("simulate.html", companies=[])


@app.route("/api/simulate/question")
def api_simulate_question():
    import json, random
    company_id = request.args.get("company_id", request.args.get("company", "wells_fargo"))
    try:
        data = json.load(open("data/skills.json"))
        skills = data.get("skills", [])
        companies = data.get("target_companies", [])
        company = next((c for c in companies if c["id"] == company_id), None)
        if not skills or not company:
            return jsonify({"error": "No data found"})
        skill = random.choice(skills)
        question_base = random.choice(skill["interview_questions"])
        from ai_logger import call_claude_with_logging, extract_text
        from anthropic import Anthropic
        client = Anthropic()
        prompt = f"""Reframe this interview question from the perspective of {company["name"]} hiring for {company["role"]}.
Company framing: {company["framing"]}
Original question: {question_base}
Return ONLY JSON: {{"question": "<reframed question>", "skill_id": "{skill["id"]}", "skill_concept": "{skill["enterprise_concept"]}", "star_answer": "{skill["star_answer"][:200]}"}}"""
        response = call_claude_with_logging(client=client, call_type="simulate_question",
            job_id=company_id, model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}], max_tokens=400)
        text = extract_text(response.content).strip().replace("```json","").replace("```","").strip()
        return jsonify(json.loads(text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulate/feedback", methods=["POST"])
def api_simulate_feedback():
    import json
    req = request.json or {}
    company_id = req.get("company_id", "wells_fargo")
    question = req.get("question", "")
    answer = req.get("answer", "")
    skill_id = req.get("skill_id")
    try:
        data = json.load(open("data/skills.json"))
        companies = data.get("target_companies", [])
        company = next((c for c in companies if c["id"] == company_id), None)
        skill_context = ""
        if skill_id:
            skill = next((s for s in data.get("skills", []) if s["id"] == skill_id), None)
            if skill:
                skill_context = f"Candidate documented STAR answer: {skill['star_answer'][:300]}"
        from ai_logger import call_claude_with_logging, extract_text
        from anthropic import Anthropic
        client = Anthropic()
        prompt = f"""You are a senior interviewer at {company["name"]} for {company["role"]}.
Framing: {company["framing"]}
Follow-up pattern: {company["follow_up_pattern"]}
{skill_context}
Question: {question}
Candidate answer: {answer}
Score 0-100 where 80+ is strong hire signal.
Return ONLY JSON: {{"score": <int>, "verdict": "<one sentence>", "strong": "<what was strong>", "improve": "<what was missing>", "model_answer": "<3-4 sentence model answer>"}}"""
        response = call_claude_with_logging(client=client, call_type="simulate_feedback",
            job_id=company_id, model="claude-sonnet-5",
            messages=[{"role": "user", "content": prompt}], max_tokens=600)
        text = extract_text(response.content).strip().replace("```json","").replace("```","").strip()
        return jsonify(json.loads(text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulate/harder", methods=["POST"])
def api_simulate_harder():
    import json
    req = request.json or {}
    company_id = req.get("company_id", "wells_fargo")
    original = req.get("original_question", "")
    try:
        data = json.load(open("data/skills.json"))
        company = next((c for c in data.get("target_companies", []) if c["id"] == company_id), None)
        from ai_logger import call_claude_with_logging, extract_text
        from anthropic import Anthropic
        client = Anthropic()
        prompt = f"""Senior interviewer at {company["name"]} for {company["role"]}.
Original question: {original}
Generate a harder follow-up that digs into failure modes, edge cases, or governance implications.
Return ONLY JSON: {{"question": "<harder question>"}}"""
        response = call_claude_with_logging(client=client, call_type="simulate_harder",
            job_id=company_id, model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}], max_tokens=200)
        text = extract_text(response.content).strip().replace("```json","").replace("```","").strip()
        return jsonify(json.loads(text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jobs/add", methods=["POST"])
def api_add_job():
    import hashlib, json
    from datetime import datetime
    data = request.json or {}
    
    title = data.get("title", "").strip()
    company = data.get("company", "").strip()
    location = data.get("location", "").strip()
    description = data.get("description", "").strip()
    job_url = data.get("job_url", "").strip()
    
    if not title or not company or not description:
        return jsonify({"error": "Title, company and description are required"}), 400
    
    job_id = hashlib.md5(f"{title}{company}{location}".encode()).hexdigest()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = get_db()
    existing = conn.execute("SELECT id FROM jobs WHERE id = %s", (job_id,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Job already exists", "job_id": job_id}), 200

    conn.execute("""
        INSERT INTO jobs (
            id, title, company, location, source, job_url,
            description, status, search_pass, is_remote, is_stale,
            date_found, date_posted
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        job_id, title, company, location,
        "manual", job_url, description,
        "new", "canada", 0, 0, now, now
    ))
    conn.commit()
    conn.close()
    
    # Score immediately
    try:
        from scorer import score_single_job
        score_single_job(job_id)
        conn = get_db()
        job = conn.execute("SELECT score FROM jobs WHERE id = %s", (job_id,)).fetchone()
        conn.close()
        score = job[0] if job else 0
    except Exception as e:
        score = 0
    
    return jsonify({"success": True, "job_id": job_id, "score": score})


# ── Settings / Profile ──
# Backs templates/settings.html. Everything here is single-tenant (one
# profile row, id=1 — see profile_store.py) matching the rest of the app's
# zero-auth architecture; going multi-tenant later means adding auth and
# threading an account id through profile_store instead of these routes.

@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/api/profile", methods=["GET"])
def api_get_profile():
    try:
        from profile_store import get_profile
        return jsonify(get_profile() or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile", methods=["POST"])
def api_save_profile():
    from profile_store import save_profile, SETTINGS_FIELDS
    data = request.json or {}
    fields = {k: v for k, v in data.items() if k in SETTINGS_FIELDS}
    if not fields:
        return jsonify({"error": "No recognized profile fields in request"}), 400
    try:
        save_profile(fields)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile/resume/extract", methods=["POST"])
def api_profile_resume_extract():
    """Step 1 of the CV upload flow: PDF/Word -> plain text -> one Claude
    call -> a resume_json draft. Returns the draft for the settings page to
    show in an editable review screen — nothing is saved to the profile yet.
    The original file is uploaded to Blob storage and its URL saved
    immediately though, since that part needs no human review."""
    if "resume" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["resume"]
    filename = file.filename or "resume"
    data = file.read()
    if not data:
        return jsonify({"error": "Uploaded file is empty"}), 400
    if len(data) > 8 * 1024 * 1024:
        return jsonify({"error": "File too large — 8MB max"}), 400

    try:
        from resume_intake import extract_text, draft_resume_json
        text = extract_text(data, filename)
        if len(text.strip()) < 200:
            return jsonify({"error": "Couldn't read enough text from that file — try a different export."}), 400
        draft = draft_resume_json(text)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Non-fatal: the draft is still useful even if storage isn't set up yet.
    try:
        from storage import upload as blob_upload
        from profile_store import save_profile
        lower = filename.lower()
        if lower.endswith(".pdf"):
            content_type = "application/pdf"
        else:
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        file_url = blob_upload(f"resumes/{filename}", data, content_type)
        save_profile({"resume_file_url": file_url, "resume_filename": filename})
    except Exception as e:
        print(f"Resume storage upload failed (draft still returned): {e}")

    return jsonify({"draft": draft})


@app.route("/api/profile/resume/confirm", methods=["POST"])
def api_profile_resume_confirm():
    """Step 2: the user has reviewed/edited the draft from /extract — save
    it as the real resume_json. Kept as a separate endpoint from
    /api/profile (POST) so a raw client payload can never silently
    overwrite resume_json outside this reviewed path."""
    from profile_store import save_profile
    data = request.json or {}
    resume_json = data.get("resume_json")
    if not resume_json:
        return jsonify({"error": "resume_json required"}), 400
    try:
        save_profile({"resume_json": resume_json})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile/resume/skills", methods=["POST"])
def api_profile_resume_skills():
    """Edits just resume_json.technical_stack — the Settings page's "Core
    skills" chips aren't their own profile column, they're a view onto this
    field (the same one scorer.py reads as profile['skills']). A dedicated,
    merge-only endpoint so this can edit that one field without exposing
    the rest of resume_json to a raw client overwrite the way a generic
    PATCH would."""
    from profile_store import get_profile, save_profile
    data = request.json or {}
    skills = data.get("technical_stack")
    if not isinstance(skills, list):
        return jsonify({"error": "technical_stack (a list) is required"}), 400

    try:
        stored = get_profile()
        if not stored or not stored.get("resume_json"):
            return jsonify({"error": "No resume on file yet — upload one first."}), 400

        resume = dict(stored["resume_json"])
        resume["technical_stack"] = [s.strip() for s in skills if isinstance(s, str) and s.strip()]
        save_profile({"resume_json": resume})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # init_db() already ran unconditionally at module import time above.
    print("\n" + "="*50)
    print("Job Apply Dashboard running at http://127.0.0.1:5001")
    print("="*50 + "\n")
    app.run(host="127.0.0.1", port=5001, debug=False)