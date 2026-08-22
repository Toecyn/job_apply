"""
Single-row user profile — replaces master_resume.json as the source of
target titles, exclusions, scoring keywords, search markets, and resume
content for scraper.py / scorer.py / tailor.py.

Single-tenant for now: one deploy, one profile, always id=1. Going
multi-tenant later means adding an account_id column and threading it
through get_profile()/save_profile() instead of the hardcoded PROFILE_ID —
everything else in this module stays the same shape.
"""
import json
import re
from datetime import datetime
from db import get_db

PROFILE_ID = 1

JSON_FIELDS = ("target_titles", "exclude_keywords", "score_keywords", "markets", "resume_json")

DEFAULTS = {
    "target_titles": [],
    "exclude_keywords": [],
    "score_keywords": [],
    "markets": [],
    "resume_json": None,
}

# Columns api_save_profile() is allowed to write from the Settings page.
# resume_json is deliberately excluded — it's only ever written by the
# extract/confirm flow in resume_intake.py, never a raw client payload.
SETTINGS_FIELDS = {
    "target_titles", "exclude_keywords", "score_keywords", "markets",
    "open_to_remote", "visa_required", "country",
    "min_score_default", "stale_days", "brand_color",
}


def get_profile():
    """Return the profile as a dict with JSON columns already decoded.

    Returns None only if the seed row from schema.sql is somehow missing
    (e.g. init_db() hasn't run yet) — callers should treat that the same
    as "not configured."
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM profile WHERE id = %s", (PROFILE_ID,)).fetchone()
    conn.close()
    if not row:
        return None

    profile = dict(row)
    for field in JSON_FIELDS:
        raw = profile.get(field)
        if raw:
            try:
                profile[field] = json.loads(raw)
            except (TypeError, ValueError):
                profile[field] = DEFAULTS[field]
        else:
            profile[field] = DEFAULTS[field]
    return profile


def save_profile(fields):
    """Upsert one or more profile columns.

    `fields` values for JSON_FIELDS should be plain Python lists/dicts —
    this handles the json.dumps. Unknown keys are written as-is (callers
    are expected to have already filtered against SETTINGS_FIELDS where
    that matters, e.g. api_save_profile in app.py).
    """
    if not fields:
        return

    payload = dict(fields)
    for field in JSON_FIELDS:
        if field in payload and payload[field] is not None:
            payload[field] = json.dumps(payload[field])
    # open_to_remote / visa_required are INTEGER columns (matching
    # jobs.is_remote / jobs.visa_required's existing 0/1 convention in this
    # schema), but settings.html sends real JSON booleans from checkbox
    # state. psycopg2 adapts a Python bool to SQL boolean, not integer, and
    # Postgres refuses that against an INTEGER column outright ("column is
    # of type integer but expression is of type boolean") — coerce
    # generically so any future boolean field doesn't hit the same trap.
    for key, value in payload.items():
        if isinstance(value, bool):
            payload[key] = int(value)
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    columns = list(payload.keys())
    values = [payload[c] for c in columns]
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns)

    conn = get_db()
    conn.execute(
        f"""INSERT INTO profile (id, {col_list}) VALUES (%s, {placeholders})
            ON CONFLICT (id) DO UPDATE SET {update_list}""",
        [PROFILE_ID] + values,
    )
    conn.commit()
    conn.close()


def market_pass_name(market):
    """Derive a stable, human-readable search_pass slug from a user-defined
    market row ({"location": ..., "mode": ..., "country": ...}) — replaces
    the old fixed set of pass names (canada_remote, ottawa, us_remote, ...).

    Lives here (not scraper.py, its original home) so app.py can use the
    exact same slugging for dashboard stats/filtering without importing
    scraper.py — which pulls in jobspy at module level, and jobspy is
    deliberately excluded from requirements.txt (see db.init_db()'s
    docstring for the same reasoning). scraper.py imports this from here."""
    loc_slug = re.sub(r'[^a-z0-9]+', '_', (market.get("location") or "").lower()).strip('_') or "anywhere"
    mode_slug = (market.get("mode") or "").lower().replace(" ", "_").replace("-", "_")
    return f"{loc_slug}_{mode_slug}" if mode_slug else loc_slug


def market_label(market):
    """Human-readable label for a market row, e.g. "Lagos · Hybrid" or just
    "Canada" if no mode is set."""
    location = market.get("location") or "Anywhere"
    mode = market.get("mode") or ""
    return f"{location} · {mode}" if mode else location


def is_configured():
    """True once a resume has been confirmed and at least one target title is set.

    scraper.py and scorer.py check this before doing any work, so a fresh
    deploy that nobody has visited /settings on yet fails with a clear
    message instead of scraping/scoring against empty keyword lists.
    """
    p = get_profile()
    return bool(p and p.get("resume_json") and p.get("target_titles"))
