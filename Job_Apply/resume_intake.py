"""
Turns an uploaded CV (PDF or Word) into the resume_json shape the rest of
the app already knows how to score and tailor from (the same shape
master_resume.json used to hold, minus job_search_config — target titles,
exclusions, and open_to_remote now live as their own profile columns, set
separately on the Settings page).

Two-step flow, mirroring the "AI drafts, human confirms" pattern
tailor.py already uses for the resume itself:

  1. extract_text()      — PDF/docx -> plain text
  2. draft_resume_json() — one Claude call -> a resume_json draft

app.py's /api/profile/resume/extract endpoint calls both and returns the
draft to the browser for review. Nothing here writes to the profile table —
that only happens once the user confirms (or edits) the draft, via
/api/profile/resume/confirm -> profile_store.save_profile().
"""
import io
import json
import os
import re
import tempfile

from anthropic import Anthropic
from ai_logger import call_claude_with_logging

client = Anthropic()

RESUME_SCHEMA_EXAMPLE = {
    "name": "Jordan Lee",
    "title": "Senior Data Analyst",
    "contact": {"phone": "555-123-4567", "email": "jordan@example.com", "location": "Toronto, ON"},
    "summary": "2-4 sentence professional summary, written in the resume's own voice.",
    "core_competencies": ["Skill or specialty phrase", "..."],
    "technical_stack": ["Tool or technology name", "..."],
    "experience": [
        {
            "id": "short_slug",
            "company": "Company name",
            "title": "Role title held there",
            "start": "Mon YYYY",
            "end": "Present or Mon YYYY",
            "location": "City, ST",
            "industry": "one or two word industry label, e.g. financial_services",
            "bullets": [
                {"id": "short_slug_1", "text": "The bullet exactly as it reads on the resume.",
                 "tags": ["skill_or_theme_keyword", "..."]}
            ],
        }
    ],
    "education": [{"degree": "...", "institution": "...", "location": "...", "year": "..."}],
    "certifications": [{"name": "...", "issuer": "...", "year": "..."}],
}


def extract_text(file_bytes: bytes, filename: str) -> str:
    """PDF or Word (.docx) -> plain text. Raises ValueError on an unsupported format."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if ext in ("docx", "doc"):
        import docx2txt
        # docx2txt needs a filesystem path, not bytes in memory.
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            return docx2txt.process(tmp_path) or ""
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    raise ValueError(f"Unsupported resume format: .{ext or 'unknown'} — upload a PDF or Word (.docx) file.")


def _slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:24] or fallback


def _backfill_ids(draft: dict) -> dict:
    """Never trust the model's JSON to have unique, present ids — tailor.py
    keys bullets and roles by id throughout, so guarantee them here."""
    seen_role_ids = set()
    for i, role in enumerate(draft.get("experience", [])):
        base = _slugify(role.get("company"), f"role{i+1}")
        role_id, n = base, 1
        while role_id in seen_role_ids:
            n += 1
            role_id = f"{base}{n}"
        seen_role_ids.add(role_id)
        role["id"] = role_id

        for j, bullet in enumerate(role.get("bullets", [])):
            bullet["id"] = f"{role_id}_{j+1}"
            bullet["tags"] = bullet.get("tags") or []
    return draft


def draft_resume_json(resume_text: str) -> dict:
    """One Claude call: raw resume text -> a resume_json draft.

    Raises on a malformed/non-JSON response — app.py surfaces that as a
    500 with the error text; there is no silent fallback, since a garbled
    resume is worse than an explicit failure the user can retry.
    """
    prompt = f"""You are converting a resume/CV into structured JSON for a job-search tool.

Extract every role, bullet, skill, and credential from the resume text below.
Do not invent, embellish, or infer anything that is not stated or clearly
implied by the text — no fabricated metrics, employers, or dates. If a
field genuinely isn't present in the source (e.g. no certifications), return
an empty list for it rather than guessing.

Return ONLY a JSON object matching exactly this shape (the values below are
illustrative, not to be copied):
{json.dumps(RESUME_SCHEMA_EXAMPLE, indent=2)}

Rules:
- "experience" must be ordered most-recent-first, matching the resume.
- Each bullet's "text" should be the bullet as written, not rewritten.
- "tags" per bullet: 1-4 short lowercase keywords capturing the skill/tool/theme
  of that bullet (e.g. "sql", "stakeholder_reporting") — used later to match
  bullets against job descriptions, so keep them specific rather than generic.
- "id" fields can be anything unique and short — they get normalized after parsing.

RESUME TEXT:
{resume_text[:12000]}

Return only the JSON object, no other text."""

    response = call_claude_with_logging(
        client=client,
        call_type="resume_intake",
        job_id=None,
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
    )
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    draft = json.loads(text)
    return _backfill_ids(draft)
