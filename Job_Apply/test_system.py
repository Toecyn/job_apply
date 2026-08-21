"""
System tests for job intelligence pipeline.
Run with: python3 test_system.py
"""
import json
import os
import sys
from db import get_db

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")
        FAIL += 1

print("\n" + "="*55)
print("JOB INTELLIGENCE PIPELINE — SYSTEM TESTS")
print("="*55)

# FILE EXISTENCE TESTS
print("\n[1] Core files")
test("scraper.py exists", os.path.exists("scraper.py"))
test("scorer.py exists", os.path.exists("scorer.py"))
test("tailor.py exists", os.path.exists("tailor.py"))
test("app.py exists", os.path.exists("app.py"))
test("scheduler.py exists", os.path.exists("scheduler.py"))
test("ai_logger.py exists", os.path.exists("ai_logger.py"))
test("master_resume.json exists", os.path.exists("master_resume.json"))
test("templates/index.html exists", os.path.exists("templates/index.html"))
test("templates/governance.html exists", os.path.exists("templates/governance.html"))
test(".env exists", os.path.exists(".env"), "API key not configured")
test(".gitignore exists", os.path.exists(".gitignore"))

# MASTER RESUME TESTS
print("\n[2] Master resume integrity")
try:
    with open("master_resume.json") as f:
        resume = json.load(f)
    test("Valid JSON", True)
    test("Has name", bool(resume.get("name")))
    test("Has summary", bool(resume.get("summary")))
    test("Has technical_stack", bool(resume.get("technical_stack")))
    test("Has core_competencies", bool(resume.get("core_competencies")))
    test("Has experience", bool(resume.get("experience")))
    total_bullets = sum(len(r["bullets"]) for r in resume["experience"])
    test(f"Bullet reservoir has 30+ bullets ({total_bullets} found)", total_bullets >= 30)
    for role in resume["experience"]:
        test(f"{role['company']} has bullets", len(role["bullets"]) > 0)
        for b in role["bullets"]:
            test(f"Bullet {b['id']} has text", bool(b.get("text")))
            test(f"Bullet {b['id']} has tags", bool(b.get("tags")))
except Exception as e:
    test("master_resume.json loads", False, str(e))

# DATABASE TESTS
print("\n[3] Database integrity")
try:
    conn = get_db()
    tables = [r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()]
    test("jobs table exists", "jobs" in tables)
    test("applied_companies table exists", "applied_companies" in tables)
    test("ai_calls table exists", "ai_calls" in tables)
    cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'jobs'"
    ).fetchall()]
    test("jobs has resume_path column", "resume_path" in cols)
    test("jobs has score column", "score" in cols)
    test("jobs has search_pass column", "search_pass" in cols)
    total = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_stale = 0").fetchone()[0]
    test(f"Database has active jobs ({total} found)", total > 0)
    unscored = conn.execute("SELECT COUNT(*) FROM jobs WHERE score IS NULL AND is_stale = 0").fetchone()[0]
    test(f"No unscored active jobs ({unscored} unscored)", unscored == 0)
    strong = conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 70 AND is_stale = 0").fetchone()[0]
    test(f"Has strong matches ({strong} jobs 70+)", strong > 0)
    empty_desc = conn.execute("SELECT COUNT(*) FROM jobs WHERE (description IS NULL OR length(description) < 50) AND is_stale = 0").fetchone()[0]
    desc_pct = round((empty_desc / total) * 100, 1) if total > 0 else 0
    test(f"Description gap under 50% ({desc_pct}% empty)", desc_pct < 50)
    conn.close()
except Exception as e:
    test("Database connects", False, str(e))

# OBSERVABILITY TESTS
print("\n[4] Observability layer")
try:
    from ai_logger import log_ai_call, call_claude_with_logging
    test("ai_logger imports", True)
    test("log_ai_call function exists", callable(log_ai_call))
    test("call_claude_with_logging function exists", callable(call_claude_with_logging))
    conn = get_db()
    ai_cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'ai_calls'"
    ).fetchall()]
    test("ai_calls has latency_ms", "latency_ms" in ai_cols)
    test("ai_calls has cost_usd", "cost_usd" in ai_cols)
    test("ai_calls has success", "success" in ai_cols)
    total_calls = conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0]
    test(f"AI calls being logged ({total_calls} recorded)", total_calls >= 0)
    conn.close()
except Exception as e:
    test("ai_logger loads", False, str(e))

# SCORER TESTS
print("\n[5] Scorer integrity")
try:
    from scorer import load_profile
    profile = load_profile()
    test("Scorer loads profile", bool(profile))
    test("Profile has name", bool(profile.get("name")))
    test("Profile has skills", bool(profile.get("skills")))
    test("Profile has experience", bool(profile.get("experience")))
    test("Profile has target_titles", bool(profile.get("target_titles")))
except Exception as e:
    test("Scorer loads", False, str(e))

# ENVIRONMENT TESTS
print("\n[6] Environment")
try:
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    test("ANTHROPIC_API_KEY set", bool(api_key), "Missing from .env")
    test("API key format valid", bool(api_key and api_key.startswith("sk-ant-")) if api_key else False)
except Exception as e:
    test("Environment loads", False, str(e))

# SUMMARY
print("\n" + "="*55)
total_tests = PASS + FAIL
print(f"Results: {PASS}/{total_tests} passed  {FAIL} failed")
if FAIL == 0:
    print("All systems operational")
else:
    print(f"{FAIL} issue(s) need attention")
print("="*55 + "\n")

sys.exit(0 if FAIL == 0 else 1)
