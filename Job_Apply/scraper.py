import json
import hashlib
from datetime import datetime
from jobspy import scrape_jobs
from dotenv import load_dotenv
from db import get_db, init_db
from profile_store import get_profile as get_stored_profile, market_pass_name
load_dotenv()

# Results requested per market, by work mode — same figures the old
# per-pass hardcoding used (remote passes searched hardest, on-site least).
RESULTS_BY_MODE = {"remote": 25, "hybrid": 20, "contract": 15, "on-site": 15}
DEFAULT_RESULTS = 15


def load_config():
    """Same shape as before ({'target_titles': [...], 'exclude_keywords': [...]})
    — only the source changed, from master_resume.json's job_search_config
    to the profile table."""
    stored = get_stored_profile()
    if not stored:
        raise RuntimeError("Profile table missing its seed row — run init_db() first.")
    return {
        "target_titles": stored["target_titles"],
        "exclude_keywords": stored["exclude_keywords"],
    }


def fingerprint(title, company, location):
    raw = f"{title.lower().strip()}{company.lower().strip()}{location.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()

def is_excluded(title, exclude_keywords):
    return any(k.lower() in title.lower() for k in exclude_keywords)

def detect_remote(title, description):
    text = (title + " " + (description or "")).lower()
    return any(s in text for s in ["remote","work from home","wfh","telework","distributed"])

def detect_hybrid(title, description):
    text = (title + " " + (description or "")).lower()
    return any(s in text for s in ["hybrid","flexible","partially remote"])

def detect_contract(title, description):
    text = (title + " " + (description or "")).lower()
    return any(s in text for s in ["contract","contractor","fixed term","fixed-term","temporary"])

def detect_visa_required(description):
    text = (description or "").lower()
    return any(s in text for s in ["sponsorship not available","no sponsorship","us citizens only"])

def run_search(titles, location, country, exclude_keywords,
               is_remote_search=False, results=25, pass_name="canada", mode=""):
    """mode is the market's own work-mode ("remote"/"hybrid"/"contract"/"on-site"),
    used for the same post-filtering the old code keyed off specific pass_name
    strings — pass_name itself is now just the label saved onto each job.

    country is now the market's actual country name (e.g. "Canada", "United
    Kingdom", "Germany") from the Settings page's full country list, passed
    straight through to jobspy's country_indeed rather than collapsed to a
    Canada/US binary. jobspy isn't installed in the environment this was
    written in, so which country names it actually recognizes is unverified
    here — an unsupported one will surface as a per-market scrape error
    below rather than a silent mismap to the wrong country's job board."""
    all_jobs = []
    for title in titles:
        try:
            kwargs = {
                "site_name": ["indeed", "linkedin"],
                "search_term": title,
                "location": location,
                "results_wanted": results,
                "hours_old": 168,
                "description_format": "markdown",
                "country_indeed": country or "Canada"
            }
            if is_remote_search:
                kwargs["is_remote"] = True
            jobs = scrape_jobs(**kwargs)
            added = 0
            excluded = 0
            for _, row in jobs.iterrows():
                job_title = str(row.get("title", ""))
                if is_excluded(job_title, exclude_keywords):
                    excluded += 1
                    continue
                description = str(row.get("description", ""))
                is_remote = 1 if detect_remote(job_title, description) else 0
                is_contr = 1 if detect_contract(job_title, description) else 0
                if mode == "remote" and not is_remote:
                    excluded += 1
                    continue
                if mode == "hybrid" and not detect_hybrid(job_title, description):
                    excluded += 1
                    continue
                if mode == "contract" and not is_contr:
                    excluded += 1
                    continue
                all_jobs.append({
                    "title": job_title,
                    "company": str(row.get("company", "")),
                    "location": str(row.get("location", "")),
                    "source": str(row.get("site", "")),
                    "date_posted": str(row.get("date_posted", "")),
                    "job_url": str(row.get("job_url", "")),
                    "description": description,
                    "country": country,
                    "is_remote": is_remote,
                    # Was gated on country == "us" — that was really just
                    # standing in for "this market is the US". The keywords
                    # detect_visa_required() looks for aren't US-exclusive
                    # phrasing, so run it for every market now rather than
                    # add another country-name string match.
                    "visa_required": 1 if detect_visa_required(description) else 0,
                    "search_pass": pass_name
                })
                added += 1
            print(f"  [{pass_name.upper()}] '{title}': {added} kept, {excluded} excluded")
        except Exception as e:
            print(f"  Error '{title}' [{pass_name}]: {e}")
    return all_jobs

def save_jobs(jobs):
    conn = get_db()
    c = conn.cursor()
    new_count = 0
    duplicate_count = 0
    for job in jobs:
        job_id = fingerprint(job.get("title",""), job.get("company",""), job.get("location",""))
        c.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
        if c.fetchone():
            duplicate_count += 1
            continue
        c.execute("""INSERT INTO jobs (
            id, title, company, location, source, date_posted,
            date_found, job_url, description, status, country,
            is_remote, visa_required, search_pass
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
            job_id, job.get("title",""), job.get("company",""),
            job.get("location",""), job.get("source",""),
            job.get("date_posted",""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            job.get("job_url",""), job.get("description",""),
            "new", job.get("country","canada"),
            job.get("is_remote",0), job.get("visa_required",0),
            job.get("search_pass","canada")
        ))
        new_count += 1
    conn.commit()
    conn.close()
    print(f"\n  Saved {new_count} new jobs, skipped {duplicate_count} duplicates")
    return new_count

def mark_stale_jobs():
    conn = get_db()
    c = conn.cursor()
    c.execute("""UPDATE jobs SET is_stale = 1
        WHERE status = 'new' AND date_found < to_char(NOW() - INTERVAL '7 days', 'YYYY-MM-DD HH24:MI:SS')""")
    stale = c.rowcount
    conn.commit()
    conn.close()
    if stale > 0:
        print(f"  Marked {stale} jobs as stale (older than 7 days)")

def run_scrape_market(market_index):
    """Scrape exactly one configured market and save its results.

    Vercel's function timeout (60s even after the maxDuration fix) is not
    enough to scrape every market plus score every job in one request —
    runtime logs showed /refresh timing out mid-way through market 1 of 3,
    every time. Splitting the scrape into one-market-per-request calls
    (driven by the dashboard's Refresh Jobs button in app.py) keeps each
    request well inside the limit. init_db()/mark_stale_jobs() are cheap
    and idempotent, so running them on every call is fine.

    Returns a dict describing what happened; total_markets/market_index
    let the caller know whether to request the next index.
    """
    init_db()
    stored = get_stored_profile()
    if not stored or not stored.get("target_titles") or not stored.get("markets"):
        return {
            "new_jobs": 0, "market_index": market_index, "total_markets": 0,
            "pass_name": None, "label": None,
            "skipped": "No profile configured yet (target roles and/or search "
                       "markets are empty) — visit /settings before running a scrape.",
        }

    titles = stored["target_titles"]
    exclude = stored["exclude_keywords"]
    markets = stored["markets"]
    total_markets = len(markets)

    if market_index < 0 or market_index >= total_markets:
        return {
            "new_jobs": 0, "market_index": market_index, "total_markets": total_markets,
            "pass_name": None, "label": None, "skipped": "market_index out of range",
        }

    market = markets[market_index]
    location = market.get("location") or ""
    mode = (market.get("mode") or "").lower()
    country = market.get("country") or "Canada"
    pass_name = market_pass_name(market)
    results = RESULTS_BY_MODE.get(mode, DEFAULT_RESULTS)

    print(f"\n--- Market {market_index + 1}/{total_markets}: {location or 'anywhere'} "
          f"({mode or 'any mode'}, {country}) -> pass '{pass_name}' ---")
    jobs = run_search(
        titles, location, country, exclude,
        is_remote_search=(mode == "remote"), results=results,
        pass_name=pass_name, mode=mode,
    )
    new_count = save_jobs(jobs)
    mark_stale_jobs()

    print(f"  {pass_name}: {len(jobs)} found, {new_count} new")
    return {
        "new_jobs": new_count, "market_index": market_index, "total_markets": total_markets,
        "pass_name": pass_name, "label": market.get("location") or pass_name, "skipped": None,
    }


def run_scrape():
    """Scrape every configured market in one call. Fine for a local/background
    process (scheduler.py) that isn't bound by Vercel's request timeout — the
    live dashboard drives run_scrape_market() one market at a time instead."""
    print("\n" + "="*50)
    print(f"Job scrape started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    stored = get_stored_profile()
    total_markets = len(stored["markets"]) if stored else 0
    total_new = 0
    for i in range(total_markets):
        result = run_scrape_market(i)
        total_new += result["new_jobs"]

    print("\n" + "="*50)
    print(f"Scrape complete. {total_new} new jobs added.")
    print("="*50)
    return total_new

if __name__ == "__main__":
    run_scrape()
