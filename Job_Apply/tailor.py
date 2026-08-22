import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from anthropic import Anthropic
from ai_logger import call_claude_with_logging, extract_text
from dotenv import load_dotenv
from db import get_db
from profile_store import get_profile as get_stored_profile

load_dotenv()

# Vercel's serverless filesystem is read-only outside /tmp, and even /tmp
# doesn't persist across invocations — so this is scratch space only for
# build_docx.js to write to before build_tailored_docx() uploads the result
# to Blob storage and deletes the local copy. Never treat OUTPUT_DIR itself
# as durable storage.
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "job_apply_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

client = Anthropic()

FORMAT_SPEC = {
    "font": "Arial",
    "name_size": 38,
    "subtitle_size": 21,
    "contact_size": 18,
    "section_header_size": 21,
    "role_company_size": 21,
    "role_title_size": 19,
    "body_size": 19,
    "margin_top": 580,
    "margin_bottom": 580,
    "margin_left": 780,
    "margin_right": 780,
    "blue": "1F4E79",
    "light_blue": "2E75B6",
    "dark": "1A1A1A",
    "mid": "444444",
    "light": "555555",
}

QUALITY_RULES = """
QUALITY RULES — apply to every bullet you write or rewrite:
1. Formula: What you did + at what scale + with what tool + what outcome. Every bullet needs at least 3 of 4.
2. No AI tells: no em dashes, no "leveraged/spearheaded/fostered/championed/utilized", no "actionable insights/data-driven/cross-functional"
3. No vague openers: never "Responsible for", "Assisted with", "Helped to", "Supported the team in"
4. Human voice: must read like a person describing their own work
5. Every claim defensible: only include things the candidate can explain with a specific example
6. Numbers must be real: never fabricate metrics. Reframe context but never invent figures.
"""

def load_resume():
    """Same return shape as before (the master_resume.json document itself) —
    only the source changed, to profile.resume_json."""
    stored = get_stored_profile()
    if not stored or not stored.get("resume_json"):
        raise RuntimeError(
            "No resume on file yet — visit /settings to upload and confirm "
            "a resume before tailoring can run."
        )
    return stored["resume_json"]

def get_job(job_id):
    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
    conn.close()
    return dict(job) if job else None

def get_tier(score):
    if score >= 90: return "tier3"
    elif score >= 80: return "tier2"
    else: return "tier1"


def run_intake(job_id):
    """
    Step 1: Analyse the JD against the candidate profile.
    Infer what activities the candidate likely did based on industry context.
    Return targeted yes/no or one-sentence questions to surface forgotten evidence.
    """
    job = get_job(job_id)
    if not job:
        return {"error": "Job not found"}

    resume = load_resume()
    jd_text = job.get("description", "")
    job_title = job.get("title", "")
    company = job.get("company", "")

    if not jd_text or jd_text == "nan":
        return {"error": "No job description available"}

    existing_bullets = []
    for role in resume["experience"]:
        for b in role["bullets"]:
            existing_bullets.append({
                "company": role["company"],
                "industry": role["industry"],
                "text": b["text"],
                "tags": b.get("tags", [])
            })

    prompt = f"""You are an expert resume coach helping a senior analytics professional tailor their resume.

Your job is to analyse a job description against the candidate's existing experience and generate targeted intake questions that will surface forgotten or unarticulated evidence from their career.

HOW TO GENERATE QUESTIONS:
1. Read the JD carefully. Identify the 5 most important requirements.
2. Look at the candidate's existing bullets. Find which requirements are NOT well covered.
3. For each gap — infer what the candidate LIKELY did in their roles based on industry context.
   For example: if they worked at a telecom and the JD needs revenue forecasting — they almost certainly tracked subscriber revenue by plan type, churn rates, and ARPU. Ask about that specifically.
4. Generate questions that are SPECIFIC and CONFIRMABLE — not "what did you do?" but "did you do X?"
5. Questions should be yes/no or require only one sentence to answer.
6. Maximum 6 questions total. Each must unlock a specific bullet point if answered yes.

CANDIDATE BACKGROUND:
{json.dumps([{"company": r["company"], "title": r["title"], "industry": r["industry"]} for r in resume["experience"]], indent=2)}

EXISTING BULLETS COVERAGE:
{json.dumps(existing_bullets[:10], indent=2)}

JOB POSTING:
Title: {job_title}
Company: {company}
Description:
{jd_text[:3000]}

Return ONLY this JSON with no other text:
{{
  "job_title": "{job_title}",
  "company": "{company}",
  "industry_context": "<2 sentences: what this company/team actually does and what an analyst there works on day to day>",
  "jd_top_requirements": ["req1", "req2", "req3", "req4", "req5"],
  "coverage_gaps": ["gap1", "gap2", "gap3"],
  "questions": [
    {{
      "id": "q1",
      "role": "<which company this question relates to>",
      "question": "<specific yes/no or one-sentence question>",
      "why": "<what bullet this unlocks if answered yes>",
      "type": "yesno|sentence"
    }}
  ]
}}"""

    try:
        response = call_claude_with_logging(
            client=client,
            call_type='intake',
            job_id=job_id,
            model='claude-sonnet-5',
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500
        )
        text = extract_text(response.content).strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        result["job_id"] = job_id
        return result
    except Exception as e:
        return {"error": f"Intake failed: {str(e)}"}


def tailor_for_job(job_id, intake_answers=None):
    """
    Step 2: Tailor the resume using JD analysis + intake answers.
    intake_answers: dict of {question_id: answer_text}
    """
    job = get_job(job_id)
    if not job:
        return {"error": "Job not found"}

    resume = load_resume()
    jd_text = job.get("description", "")
    job_title = job.get("title", "")
    company = job.get("company", "")
    score = job.get("score", 75)
    tier = get_tier(score)

    if not jd_text or jd_text == "nan":
        return {"error": "No job description available"}

    all_bullets = []
    for role in resume["experience"]:
        for b in role["bullets"]:
            all_bullets.append({
                "id": b["id"],
                "company": role["company"],
                "role_title": role["title"],
                "industry": role["industry"],
                "text": b["text"],
                "tags": b.get("tags", [])
            })

    intake_context = ""
    if intake_answers:
        intake_context = f"""
CANDIDATE INTAKE ANSWERS — use these to write new bullets or strengthen existing ones:
{json.dumps(intake_answers, indent=2)}

For each yes answer: write a new bullet or enhance an existing bullet using the industry context and the candidate's confirmed experience.
For each sentence answer: use the exact detail provided to make the bullet specific and defensible.
"""

    tier_instruction = {
        "tier1": "Reorder bullets — most JD-relevant first. Rewrite summary first sentence only. Do not rewrite bullets.",
        "tier2": "Rewrite top 3 bullets per role to mirror JD language. Rewrite full summary. Reorder all bullets.",
        "tier3": "Rewrite every bullet through the JD narrative lens. Full summary rewrite. Add bullets from intake answers."
    }[tier]

    prompt = f"""You are an expert resume writer with 20 years of experience helping senior analytics professionals land interviews.

TASK: Tailor this resume for a specific job. Score: {score}/100. Tier: {tier.upper()}.

TIER INSTRUCTION: {tier_instruction}

{QUALITY_RULES}

{intake_context}

CANDIDATE PROFILE:
Name: {resume['name']}
Summary: {resume['summary']}
Technical stack: {', '.join(resume['technical_stack'])}
Experience: {json.dumps([{"company": r["company"], "title": r["title"], "industry": r["industry"]} for r in resume["experience"]], indent=2)}

JOB POSTING:
Title: {job_title}
Company: {company}
Description:
{jd_text[:4000]}

EXISTING BULLETS:
{json.dumps(all_bullets, indent=2)}

CRITICAL: Use industry context to shape bullet language. If the JD is from a media company, use media industry vocabulary. If financial services, use FS vocabulary. Mirror the exact language the hiring manager uses in their JD.

Return ONLY this JSON:
{{
  "suggested_title": "<mirror exact JD title>",
  "jd_narrative": "<2 sentences: what this team needs>",
  "jd_keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
  "summary": "<tailored summary>",
  "core_competencies": ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"],
  "tech_stack_ordered": ["t1", "t2"],
  "tailored_bullets": [
    {{
      "id": "<bullet id or new_N for new bullets>",
      "company": "<company>",
      "original": "<original text or empty if new>",
      "tailored": "<rewritten or new bullet text>",
      "enhanced": <true/false>,
      "is_new": <true if from intake answers>,
      "enhancement_note": "<what changed and why>"
    }}
  ],
  "gate_scores": {{
    "ats": "<X/10 — note>",
    "recruiter": "<X/10 — note>",
    "hiring_manager": "<X/10 — note>"
  }},
  "gaps": ["gap1", "gap2"]
}}"""

    try:
        response = call_claude_with_logging(
            client=client,
            call_type='tailor',
            job_id=job_id,
            model='claude-sonnet-5',
            messages=[{"role": "user", "content": prompt}],
            # Same reasoning as resume_intake.py's draft call — this covers
            # every bullet across every role plus gate scores, and Sonnet
            # 5's default thinking eats into the same budget. 4000 was
            # truncating mid-string on real resumes.
            max_tokens=16000
        )
        text = extract_text(response.content).strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)

        result["job_id"] = job_id
        result["job_title"] = job_title
        result["company"] = company
        result["score"] = score
        result["tier"] = tier
        result["job_description"] = jd_text[:2000]
        result["search_pass"] = job.get("search_pass", "")
        result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        safe_company = re.sub(r'[^a-zA-Z0-9]', '_', company)
        review_path = os.path.join(OUTPUT_DIR, f"review_{job_id[:8]}_{safe_company}.json")
        with open(review_path, "w") as f:
            json.dump(result, f, indent=2)

        return result

    except Exception as e:
        return {"error": f"Tailoring failed: {str(e)}"}




# Tool equivalence mapping — transferable tools
# If JD lists a tool not in candidate stack, map to closest equivalent
TOOL_EQUIVALENCE = {
    # Azure tools
    "azure synapse": {"equivalent": "AWS Redshift", "add_as": "Azure Synapse Analytics"},
    "azure synapse analytics": {"equivalent": "AWS Redshift", "add_as": "Azure Synapse Analytics"},
    "azure databricks": {"equivalent": "AWS Glue", "add_as": "Azure Databricks"},
    "databricks": {"equivalent": "AWS Glue", "add_as": "Databricks"},
    "azure data factory": {"equivalent": "AWS Glue", "add_as": "Azure Data Factory"},
    "adf": {"equivalent": "AWS Glue", "add_as": "Azure Data Factory"},
    "azure data lake": {"equivalent": "AWS Redshift", "add_as": "Azure Data Lake"},
    "azure sql": {"equivalent": "SQL", "add_as": "Azure SQL"},
    "azure ml": {"equivalent": "Python", "add_as": "Azure ML"},
    # BI tools
    "looker": {"equivalent": "Power BI", "add_as": "Looker"},
    "thoughtspot": {"equivalent": "Power BI", "add_as": "ThoughtSpot"},
    "qlik": {"equivalent": "Power BI", "add_as": "Qlik"},
    "microstrategy": {"equivalent": "IBM Cognos Analytics", "add_as": "MicroStrategy"},
    "domo": {"equivalent": "Power BI", "add_as": "Domo"},
    # Data transformation
    "dbt": {"equivalent": "SQL", "add_as": "dbt"},
    "spark": {"equivalent": "AWS Glue", "add_as": "Apache Spark"},
    "airflow": {"equivalent": "APScheduler", "add_as": "Apache Airflow"},
    # CRM and cloud
    "hubspot": {"equivalent": "Salesforce", "add_as": "HubSpot"},
    "dynamics": {"equivalent": "Salesforce", "add_as": "Microsoft Dynamics"},
    "google bigquery": {"equivalent": "AWS Redshift", "add_as": "Google BigQuery"},
    "bigquery": {"equivalent": "AWS Redshift", "add_as": "Google BigQuery"},
    "redshift": {"equivalent": "AWS Redshift", "add_as": "AWS Redshift"},
    # Statistical
    "r ": {"equivalent": "Python", "add_as": "R"},
    "stata": {"equivalent": "SAS", "add_as": "Stata"},
    "spss": {"equivalent": "SAS", "add_as": "SPSS"},
    "matlab": {"equivalent": "Python", "add_as": "MATLAB"},
}


def detect_transferable_tools(jd_text, current_stack):
    """
    Scan JD for tools not in current stack.
    Return list of tools to add based on equivalence mapping.
    """
    jd_lower = jd_text.lower()
    current_lower = [t.lower() for t in current_stack]
    tools_to_add = []
    flagged = []

    for jd_tool, mapping in TOOL_EQUIVALENCE.items():
        if jd_tool in jd_lower:
            add_as = mapping["add_as"]
            equivalent = mapping["equivalent"]
            # Only add if not already in stack
            if add_as.lower() not in current_lower and not any(
                add_as.lower() in t.lower() for t in current_stack
            ):
                tools_to_add.append(add_as)
                flagged.append({
                    "added": add_as,
                    "because": f"JD mentions {jd_tool}, transferable from your {equivalent} experience",
                    "defensible": f"You have used {equivalent} for the same purpose"
                })

    return tools_to_add, flagged

BULLET_CAPS = {
    'bmo': 7,
    'docebo': 5,
    'rogers': 6,
    'nestle': 4
}


def detect_location(jd_text, search_pass=None):
    """
    Extract short-form location from JD text.
    - Specific Canadian city found: mirror in short form
    - Remote or Telework: default to Toronto, ON
    - US Remote job: Toronto, ON
    - Nothing found: Toronto, ON
    """
    import re

    if search_pass == 'us_remote':
        return 'Toronto, ON'

    canadian_patterns = [
        r'Ottawa,?\s*ON', r'Toronto,?\s*ON', r'Montreal,?\s*QC',
        r'Vancouver,?\s*BC', r'Calgary,?\s*AB', r'Edmonton,?\s*AB',
        r'Mississauga,?\s*ON', r'Waterloo,?\s*ON', r'Hamilton,?\s*ON',
        r'Winnipeg,?\s*MB', r'Halifax,?\s*NS', r'Victoria,?\s*BC',
    ]
    remote_patterns = [r'Remote', r'Work from Home', r'Telework', r'WFH']
    us_patterns = [
        r'New York,?\s*NY', r'Chicago,?\s*IL', r'San Francisco,?\s*CA',
        r'Boston,?\s*MA', r'Seattle,?\s*WA', r'Austin,?\s*TX',
    ]

    for pattern in canadian_patterns:
        match = re.search(pattern, jd_text, re.IGNORECASE)
        if match:
            return match.group(0).strip()

    for pattern in remote_patterns:
        if re.search(pattern, jd_text, re.IGNORECASE):
            return 'Toronto, ON'

    for pattern in us_patterns:
        match = re.search(pattern, jd_text, re.IGNORECASE)
        if match:
            return match.group(0).strip()

    return 'Toronto, ON'


def apply_bullet_caps(tailored_resume):
    for role in tailored_resume.get('experience', []):
        role_id = role.get('id', '').lower()
        cap = BULLET_CAPS.get(role_id, 6)
        if len(role.get('bullets', [])) > cap:
            role['bullets'] = role['bullets'][:cap]
    return tailored_resume

def build_tailored_docx(review_data):
    resume = load_resume()

    tailored_map = {b["id"]: b["tailored"] for b in review_data.get("tailored_bullets", []) if not b.get("is_new")}
    new_bullets_by_company = {}
    for b in review_data.get("tailored_bullets", []):
        if b.get("is_new"):
            co = b.get("company", "")
            if co not in new_bullets_by_company:
                new_bullets_by_company[co] = []
            new_bullets_by_company[co].append(b["tailored"])

    suggested_title = review_data.get("suggested_title", resume.get("title", "Senior Analytics Professional"))
    company = review_data.get("company", "")
    job_title = review_data.get("job_title", "")
    core_competencies = review_data.get("core_competencies", [])
    tech_stack = review_data.get("tech_stack_ordered", resume.get("technical_stack", []))
    tailored_summary = review_data.get("summary", resume.get("summary", ""))

    tailored_resume = json.loads(json.dumps(resume))
    tailored_resume["title"] = suggested_title
    tailored_resume["summary"] = tailored_summary
    tailored_resume["technical_stack"] = tech_stack
    tailored_resume["core_competencies"] = core_competencies

    for role in tailored_resume["experience"]:
        for bullet in role["bullets"]:
            if bullet["id"] in tailored_map:
                bullet["text"] = tailored_map[bullet["id"]]
        if role["company"] in new_bullets_by_company:
            for new_text in new_bullets_by_company[role["company"]]:
                role["bullets"].insert(0, {"id": f"new_{role['company'][:3]}", "text": new_text})

    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', resume.get("name", "Resume"))
    safe_company = re.sub(r'[^a-zA-Z0-9]', '_', company)
    safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_title)[:30]
    filename = f"{safe_name}_{safe_company}_{safe_title}_{date_str}.docx"
    output_path = os.path.join(OUTPUT_DIR, filename)

    temp_path = os.path.join(OUTPUT_DIR, "temp_tailored.json")
    with open(temp_path, "w") as f:
        json.dump(tailored_resume, f, indent=2)

    # Per-profile accent color (Settings -> Preferences), falling back to
    # the original navy if nothing has been configured yet.
    F = dict(FORMAT_SPEC)
    stored = get_stored_profile()
    if stored and stored.get("brand_color"):
        F["blue"] = stored["brand_color"].lstrip("#")


    # Detect transferable tools from JD and add to tech stack
    job_desc = review_data.get("job_description", "") or ""
    current_stack = tailored_resume.get("technical_stack", [])
    tools_to_add, flagged_tools = detect_transferable_tools(job_desc, current_stack)
    if tools_to_add:
        # Add transferable tools after existing stack
        tailored_resume["technical_stack"] = current_stack + tools_to_add
        print(f"  Added {len(tools_to_add)} transferable tools: {', '.join(tools_to_add)}")
        for f in flagged_tools:
            print(f"    + {f['added']} — {f['because']}")

    # Detect and apply JD location to resume header
    job_desc = review_data.get("job_description", "") or ""
    search_pass = review_data.get("search_pass", "")
    detected_location = detect_location(job_desc, search_pass)
    tailored_resume["contact"]["location"] = detected_location

    # Apply bullet caps before building
    tailored_resume = apply_bullet_caps(tailored_resume)

    # Add format spec into resume data for build_docx.js
    tailored_resume["_fmt"] = {
        "blue": F["blue"], "light_blue": F["light_blue"],
        "dark": F["dark"], "mid": F["mid"], "light": F["light"],
        "margin_top": F["margin_top"], "margin_right": F["margin_right"],
        "margin_bottom": F["margin_bottom"], "margin_left": F["margin_left"],
        "body_size": F["body_size"], "name_size": F["name_size"],
        "subtitle_size": F["subtitle_size"], "contact_size": F["contact_size"],
        "section_header_size": F["section_header_size"],
        "role_company_size": F["role_company_size"],
        "role_title_size": F["role_title_size"]
    }

    with open(temp_path, "w") as f:
        json.dump(tailored_resume, f, indent=2)

    build_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_docx.js")
    result = subprocess.run(
        ["/usr/local/bin/node", build_script_path, temp_path, output_path],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )

    try:
        os.remove(temp_path)
    except Exception:
        pass

    if "SUCCESS" not in result.stdout:
        return {"error": result.stderr or result.stdout or "Failed to generate docx"}

    # output_path is local /tmp scratch space only (see OUTPUT_DIR comment
    # above) — upload to Blob storage so the file survives past this request
    # and is actually downloadable, then discard the local copy.
    try:
        from storage import upload as blob_upload
        with open(output_path, "rb") as f:
            blob_url = blob_upload(
                f"tailored/{filename}", f.read(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        try:
            os.remove(output_path)
        except OSError:
            pass
        return {"success": True, "path": blob_url, "filename": filename}
    except Exception as e:
        # Blob storage not configured yet, or the upload failed — fall back
        # to the local /tmp path rather than losing the generated docx
        # outright. This path will not survive past the current invocation
        # on Vercel, so treat this branch as a signal to set up
        # BLOB_READ_WRITE_TOKEN, not as a working download link in prod.
        print(f"tailor: Blob upload failed, returning local path instead: {e}")
        return {"success": True, "path": output_path, "filename": filename}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 tailor.py <job_id>")
        sys.exit(1)

    job_id = sys.argv[1]
    job = get_job(job_id)
    if not job:
        print("Job not found")
        sys.exit(1)

    score = job.get("score", 75)
    tier = get_tier(score)
    print(f"\nRole: {job['title']} at {job['company']}")
    print(f"Score: {score}/100 — Tier: {tier.upper()}")

    print("\nRunning intake analysis...")
    intake = run_intake(job_id)
    if "error" in intake:
        print(f"Intake error: {intake['error']}")
        sys.exit(1)

    print(f"\nIndustry context: {intake.get('industry_context', '')}")
    print(f"\nCoverage gaps: {', '.join(intake.get('coverage_gaps', []))}")
    print(f"\nQuestions ({len(intake.get('questions', []))} total):")

    answers = {}
    for q in intake.get("questions", []):
        print(f"\n[{q['role']}] {q['question']}")
        print(f"  → Unlocks: {q['why']}")
        answer = input("  Your answer: ").strip()
        if answer:
            answers[q["id"]] = {"question": q["question"], "answer": answer, "role": q["role"]}

    print("\nTailoring resume with your answers...")
    result = tailor_for_job(job_id, intake_answers=answers)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"\nSuggested title: {result.get('suggested_title', '')}")
    print(f"Gate scores: {result.get('gate_scores', {})}")

    enhanced = [b for b in result.get("tailored_bullets", []) if b.get("enhanced") or b.get("is_new")]
    print(f"\n{len(enhanced)} bullets changed or added")

    print("\nBuilding .docx...")
    docx = build_tailored_docx(result)
    if docx.get("success"):
        print(f"Resume saved: {docx['path']}")
    else:
        print(f"Error: {docx.get('error')}")