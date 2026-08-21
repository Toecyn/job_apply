import sqlite3
import json
import os
from anthropic import Anthropic
from ai_logger import call_claude_with_logging
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "tracker.db"
RESUME_PATH = "master_resume.json"
client = Anthropic()


def load_profile():
    with open(RESUME_PATH) as f:
        data = json.load(f)
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
        "target_titles": data["job_search_config"]["target_titles"],
        "open_to_remote": data["job_search_config"].get("open_to_remote", True)
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

        text = response.content[0].text.strip()
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            UPDATE jobs
            SET score = ?, score_reasons = ?, score_gaps = ?
            WHERE id = ?
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



# Keywords that must appear in title for a job to be worth scoring
SCORE_WORTHY_TITLES = [
    "analyst", "analytics", "intelligence", "reporting", "insights",
    "data", " bi ", "crm", "campaign", "revenue", "governance",
    "operations", "metrics", "performance", "dashboard", "visualization",
    "forecasting", "segmentation", "modeling", "modelling"
]

def is_score_worthy(title, description):
    """Return True only if job is worth spending API credits on."""
    if not description or len(description) < 200:
        return False
    title_lower = title.lower()
    return any(kw in title_lower for kw in SCORE_WORTHY_TITLES)

def score_all_unscored():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    jobs = conn.execute("""
        SELECT * FROM jobs
        WHERE score IS NULL
        AND is_stale = 0
        AND description IS NOT NULL
        AND length(description) >= 200
        AND (
            lower(title) LIKE '%analyst%' OR
            lower(title) LIKE '%analytics%' OR
            lower(title) LIKE '%intelligence%' OR
            lower(title) LIKE '%reporting%' OR
            lower(title) LIKE '%insights%' OR
            lower(title) LIKE '%data%' OR
            lower(title) LIKE '%governance%' OR
            lower(title) LIKE '%campaign%' OR
            lower(title) LIKE '%revenue%' OR
            lower(title) LIKE '%metrics%' OR
            lower(title) LIKE '%dashboard%' OR
            lower(title) LIKE '%forecasting%'
        )
        ORDER BY date_found DESC
    """).fetchall()
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
            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                UPDATE jobs
                SET score = ?, score_reasons = ?, score_gaps = ?
                WHERE id = ?
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
