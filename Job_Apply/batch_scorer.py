"""
Batch scorer — uses Anthropic Batch API for 50% cost reduction.
Submit:  python3 batch_scorer.py --submit
Collect: python3 batch_scorer.py --collect <batch_id>
Auto:    python3 batch_scorer.py
"""
import json
import os
import sys
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from db import get_db
from profile_store import get_profile as get_stored_profile

load_dotenv()

client = Anthropic()


def load_profile():
    """Same shape as before — sourced from the profile table instead of
    master_resume.json now. See scorer.load_profile() for the same change."""
    stored = get_stored_profile()
    if not stored or not stored.get("resume_json"):
        raise RuntimeError(
            "No resume on file yet — visit /settings before running a batch."
        )
    data = stored["resume_json"]
    return {
        "name": data["name"],
        "summary": data["summary"],
        "skills": data["technical_stack"],
        "expertise": data.get("core_competencies", []),
        "experience": [
            {
                "company": r["company"],
                "title": r["title"],
                "industry": r["industry"],
                "tags": list(set(
                    tag for b in r["bullets"]
                    for tag in b.get("tags", [])
                ))
            }
            for r in data["experience"]
        ],
        "target_titles": stored["target_titles"]
    }


def build_prompt(job, profile):
    return (
        f"You are evaluating a job posting for a senior analytics professional.\n"
        f"CANDIDATE: {profile['name']} | {profile['summary'][:200]}\n"
        f"SKILLS: {', '.join(profile['skills'][:8])}\n"
        f"TARGET ROLES: {', '.join(profile['target_titles'][:5])}\n"
        f"JOB: {job['title']} at {job['company']} | {job['location']}\n"
        f"DESCRIPTION: {(job['description'] or '')[:2000]}\n"
        f"Score 0-100. Return ONLY JSON:\n"
        f"{{\"score\": <int>, \"reasons\": [\"r1\",\"r2\",\"r3\"], \"gaps\": [\"g1\",\"g2\"]}}"
    )


def ensure_batch_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS batch_jobs (
            batch_id TEXT PRIMARY KEY,
            submitted_at TEXT,
            job_count INTEGER,
            status TEXT,
            completed_at TEXT,
            jobs_scored INTEGER DEFAULT 0
        )
    """)


def submit_batch():
    conn = get_db()

    jobs = conn.execute("""
        SELECT id, title, company, location, description
        FROM jobs
        WHERE score IS NULL
        AND is_stale = 0
        AND description IS NOT NULL
        AND length(description) >= 200
        AND batch_id IS NULL
        ORDER BY date_found DESC
        LIMIT 500
    """).fetchall()

    if not jobs:
        print("No unscored jobs to batch.")
        conn.close()
        return None

    print(f"Preparing batch for {len(jobs)} jobs...")
    profile = load_profile()
    requests = []
    job_id_map = {}

    for job in jobs:
        job = dict(job)
        cid = f"score_{job['id'][:16]}"
        job_id_map[cid] = job["id"]
        requests.append({
            "custom_id": cid,
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{
                    "role": "user",
                    "content": build_prompt(job, profile)
                }]
            }
        })

    batch = client.beta.messages.batches.create(requests=requests)
    batch_id = batch.id

    for cid, jid in job_id_map.items():
        conn.execute("UPDATE jobs SET batch_id = %s WHERE id = %s", (batch_id, jid))

    ensure_batch_table(conn)
    conn.execute(
        """INSERT INTO batch_jobs (batch_id, submitted_at, job_count, status) VALUES (%s,%s,%s,%s)
           ON CONFLICT (batch_id) DO UPDATE SET
               submitted_at = EXCLUDED.submitted_at,
               job_count = EXCLUDED.job_count,
               status = EXCLUDED.status""",
        (batch_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(jobs), "submitted")
    )
    conn.commit()
    conn.close()

    os.makedirs("output", exist_ok=True)
    with open(f"output/batch_{batch_id[:8]}_map.json", "w") as f:
        json.dump(job_id_map, f)

    est_cost = len(jobs) * 0.002
    print(f"Batch submitted: {batch_id}")
    print(f"Jobs: {len(jobs)} | Est cost: ${est_cost:.2f} | Ready in ~1hr")
    print(f"Collect with: python3 batch_scorer.py --collect {batch_id}")
    return batch_id


def collect_results(batch_id):
    print(f"Checking batch {batch_id[:16]}...")
    batch = client.beta.messages.batches.retrieve(batch_id)
    status = batch.processing_status
    print(f"Status: {status}")

    if status != "ended":
        print("Not ready yet. Try again in a few minutes.")
        return False

    maps = [
        f for f in os.listdir("output")
        if f.startswith(f"batch_{batch_id[:8]}") and f.endswith("_map.json")
    ]
    if not maps:
        print("Job ID map not found.")
        return False

    with open(f"output/{maps[0]}") as f:
        job_id_map = json.load(f)

    conn = get_db()
    scored = 0
    failed = 0

    for result in client.beta.messages.batches.results(batch_id):
        jid = job_id_map.get(result.custom_id)
        if not jid:
            continue
        if result.result.type == "succeeded":
            try:
                text = result.result.message.content[0].text
                text = text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text)
                conn.execute(
                    "UPDATE jobs SET score=%s, score_reasons=%s, score_gaps=%s WHERE id=%s",
                    (
                        int(data.get("score", 0)),
                        json.dumps(data.get("reasons", [])),
                        json.dumps(data.get("gaps", [])),
                        jid
                    )
                )
                scored += 1
            except Exception as e:
                print(f"  Parse error for {jid[:8]}: {e}")
                failed += 1
        else:
            failed += 1

    ensure_batch_table(conn)
    conn.execute(
        "UPDATE batch_jobs SET status='completed', completed_at=%s, jobs_scored=%s WHERE batch_id=%s",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scored, batch_id)
    )
    conn.commit()
    conn.close()

    print(f"Done. Scored: {scored} | Failed: {failed}")
    return True


def score_batch():
    conn = get_db()
    try:
        ensure_batch_table(conn)
        pending = conn.execute(
            "SELECT batch_id FROM batch_jobs WHERE status='submitted' ORDER BY submitted_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        pending = None
    conn.close()

    if pending:
        print(f"Found pending batch: {pending[0][:16]}...")
        if not collect_results(pending[0]):
            print("Batch not ready. Falling back to real-time scoring.")
            from scorer import score_all_unscored
            score_all_unscored()
    else:
        submit_batch()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--collect" and len(sys.argv) > 2:
        collect_results(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "--submit":
        submit_batch()
    else:
        score_batch()
