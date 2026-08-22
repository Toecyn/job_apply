import json
import os
from anthropic import Anthropic
from ai_logger import call_claude_with_logging, extract_text
from dotenv import load_dotenv
from db import get_db
from profile_store import get_profile as get_stored_profile

load_dotenv()

client = Anthropic()


def load_profile():
    """Same shape as before — only the source changed, from master_resume.json
    to the profile table (profile.resume_json holds the resume content;
    target_titles/open_to_remote are now their own profile columns rather
    than nested under a job_search_config key)."""
    stored = get_stored_profile()
    if not stored or not stored.get("resume_json"):
        raise RuntimeError(
            "No resume on file yet — visit /settings to upload a resume "
            "and set target roles before scoring can run."
        )
    data = stored["resume_json"]
    profile = {
        "name": data["name"],
        "summary": data["summary"],
        "skills": data["technical_stack"],
        "expertise": data.get("core_competencies", data.get("areas_of_expertise", [])),
        "experience": [
            {
                "company": role["company"],
                "title": role["title"],
                "industry": role["industry"],
                "tags": list(set(
                    tag for bullet in role["bullets"]
                    for tag in bullet.get("tags", [])
                ))
            }
            for role in data["experience"]
        ],
        "target_titles": stored["target_titles"],
        "open_to_remote": bool(stored.get("open_to_remote", True))
    }
    return profile


def score_job(job_id, title, company, location, description, profile):
    prompt = f"""You are evaluating a job posting for a senior analytics professional.

CANDIDATE PROFILE:
Name: {profile['name']}
Summary: {profile['summary']}
Technical skills: {', '.join(profile['skills'])}
Areas of expertise: {', '.join(profile['expertise'])}
Experience:
{json.dumps(profile['experience'], indent=2)}
Target roles: {', '.join(profile['target_titles'])}
Open to remote: {profile['open_to_remote']}

JOB POSTING:
Title: {title}
Company: {company}
Location: {location}
Description:
{description[:3000]}

Score this job from 0 to 100 based on how well it matches the candidate.

Scoring criteria:
- 85-100: Excellent match. Title, skills, domain, and seniority all align strongly
- 70-84: Good match. Most requirements align, minor gaps
- 50-69: Partial match. Some relevant experience but notable gaps
- 0-49: Poor match. Wrong domain, level, or skill set

Return ONLY a JSON object with no other text:
{{
  "score": <integer 0-100>,
  "reasons": ["reason 1", "reason 2", "reason 3"],
  "gaps": ["gap 1", "gap 2"]
}}"""

    try:
        response = call_claude_with_logging(
            client=client,
            call_type='score',
            job_id=job_id,
            model='claude-haiku-4-5-20251001',
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )

        text = extract_text(response.content).strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)

        return {
            "score": int(result.get("score", 0)),
            "reasons": result.get("reasons", []),
            "gaps": result.get("gaps", [])
        }

    except Exception as e:
        print(f"  Scoring error for {title} at {company}: {e}")
        return None


def score_single_job(job_id):
    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
    conn.close()

    if not job:
        return {"error": "Job not found"}

    job = dict(job)
    profile = load_profile()

    result = score_job(
        job_id,
        job["title"],
        job["company"],
        job["location"],
        job["description"] or "",
        profile
    )

    if result:
        conn = get_db()
        conn.execute("""
            UPDATE jobs
            SET score = %s, score_reasons = %s, score_gaps = %s
            WHERE id = %s
        """, (
            result["score"],
            json.dumps(result["reasons"]),
            json.dumps(result["gaps"]),
            job_id
        ))
        conn.commit()
        conn.close()
        return result

    return {"error": "Scoring failed"}



def _score_keywords():
    """profile.score_keywords, set on the Settings page (auto-suggested from
    target titles, editable). Empty list means "no title gate" rather than
    "score nothing" — a fresh profile shouldn't silently block every job."""
    stored = get_stored_profile()
    return [kw for kw in (stored or {}).get("score_keywords", []) if kw and kw.strip()]

def is_score_worthy(title, description):
    """Return True only if job is worth spending API credits on."""
    if not description or len(description) < 200:
        return False
    keywords = _score_keywords()
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)

def score_all_unscored():
    keywords = _score_keywords()

    conn = get_db()
    base_query = """
        SELECT * FROM jobs
        WHERE score IS NULL
        AND is_stale = 0
        AND description IS NOT NULL
        AND length(description) >= 200
    """
    if keywords:
        like_clauses = " OR ".join(["lower(title) LIKE %s"] * len(keywords))
        query = f"{base_query} AND ({like_clauses}) ORDER BY date_found DESC"
        params = [f"%{kw.lower()}%" for kw in keywords]
    else:
        query = f"{base_query} ORDER BY date_found DESC"
        params = []
    jobs = conn.execute(query, params).fetchall()
    conn.close()

    if not jobs:
        print("No unscored jobs found.")
        return 0

    print(f"\nScoring {len(jobs)} jobs...")
    profile = load_profile()

    scored = 0
    high_match = 0

    for job in jobs:
        job = dict(job)
        print(f"  Scoring: {job['title']} at {job['company']}...", end=" ")

        result = score_job(
            job["id"],
            job["title"],
            job["company"],
            job["location"],
            job["description"] or "",
            profile
        )

        if result:
            conn = get_db()
            conn.execute("""
                UPDATE jobs
                SET score = %s, score_reasons = %s, score_gaps = %s
                WHERE id = %s
            """, (
                result["score"],
                json.dumps(result["reasons"]),
                json.dumps(result["gaps"]),
                job["id"]
            ))
            conn.commit()
            conn.close()

            scored += 1
            if result["score"] >= 70:
                high_match += 1

            print(f"{result['score']}/100")
        else:
            print("failed")

    print(f"\nDone. Scored {scored} jobs, {high_match} strong matches (70+).")
    return scored


if __name__ == "__main__":
    score_all_unscored()
