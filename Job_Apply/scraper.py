import json
import sqlite3
import hashlib
from datetime import datetime
from jobspy import scrape_jobs
from dotenv import load_dotenv
load_dotenv()

DB_PATH = "tracker.db"
RESUME_PATH = "master_resume.json"

CORE_TITLES = [
    "Senior Data Analyst", "Senior BI Analyst", "Senior Business Intelligence Analyst",
    "Senior Reporting Analyst", "Senior Analytics Analyst", "Senior Marketing Analyst",
    "Senior Campaign Analyst", "Analytics Manager", "BI Manager", "Reporting Manager",
    "Analytics Lead", "BI Lead", "Insights Manager", "Campaign Analytics Manager",
    "Revenue Analytics Manager", "Performance Analytics Manager",
    "Data Analyst", "BI Analyst", "Business Intelligence Analyst",
    "Reporting Analyst", "Analytics Analyst", "Marketing Analytics Analyst",
    "Customer Analytics Analyst", "CRM Analyst", "Campaign Analyst",
    "Insights Analyst", "Performance Analyst", "Revenue Analyst",
    "Commercial Analyst", "Growth Analytics Analyst", "Financial Analyst",
    "Power BI Analyst", "Power BI Developer", "BI Developer", "BI Engineer",
    "Data Visualization Analyst", "Dashboard Developer", "Reporting Developer",
    "Tableau Developer", "Tableau Analyst", "CRM Analytics Analyst",
    "Customer Intelligence Analyst", "Data and Reporting Analyst",
    "Business Insights Analyst", "Decision Support Analyst",
    "Analytics Consultant", "Performance Measurement Analyst",
    "Loyalty Analytics Analyst", "Revenue Analytics Analyst",
    "Data Analyst Finance", "Campaign Performance Analyst",
]

OTTAWA_TITLES = [
    "Senior Data Analyst", "Data Analyst", "Senior BI Analyst", "BI Analyst",
    "Power BI Analyst", "Senior Reporting Analyst", "Reporting Analyst",
    "Business Intelligence Analyst", "Data and Reporting Analyst",
    "Performance Measurement Analyst", "Senior Analytics Analyst",
    "Analytics Analyst", "Revenue Analytics Analyst", "Analytics Manager",
    "Reporting Manager", "Decision Support Analyst", "Business Insights Analyst",
]

CONTRACT_TITLES = [
    "Data Analyst contract", "BI Analyst contract", "Analytics Analyst contract",
    "Reporting Analyst contract", "Campaign Analytics contract",
    "Business Intelligence contract", "Power BI contract",
]

def load_config():
    with open(RESUME_PATH) as f:
        data = json.load(f)
    return data["job_search_config"]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
        source TEXT, date_posted TEXT, date_found TEXT, job_url TEXT,
        description TEXT, score INTEGER DEFAULT NULL,
        score_reasons TEXT DEFAULT NULL, score_gaps TEXT DEFAULT NULL,
        status TEXT DEFAULT 'new', is_stale INTEGER DEFAULT 0,
        country TEXT DEFAULT 'canada', is_remote INTEGER DEFAULT 0,
        visa_required INTEGER DEFAULT 0, search_pass TEXT DEFAULT 'canada',
        resume_path TEXT DEFAULT NULL, batch_id TEXT DEFAULT NULL)""")
    for col, default in [
        ("country",'"canada"'),("is_remote","0"),("visa_required","0"),
        ("search_pass",'"canada"'),("resume_path","NULL"),("batch_id","NULL")]:
        try:
            conn.execute(f'ALTER TABLE jobs ADD COLUMN {col} TEXT DEFAULT {default}')
        except Exception:
            pass
    conn.commit()
    conn.close()

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
               is_remote_search=False, results=25, pass_name="canada"):
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
                "country_indeed": "Canada" if country == "canada" else "USA"
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
                if pass_name == "canada_remote" and not is_remote:
                    excluded += 1
                    continue
                if pass_name == "canada_hybrid" and not detect_hybrid(job_title, description):
                    excluded += 1
                    continue
                if pass_name == "contract" and not is_contr:
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
                    "visa_required": 1 if (country == "us" and detect_visa_required(description)) else 0,
                    "search_pass": pass_name
                })
                added += 1
            print(f"  [{pass_name.upper()}] '{title}': {added} kept, {excluded} excluded")
        except Exception as e:
            print(f"  Error '{title}' [{pass_name}]: {e}")
    return all_jobs

def save_jobs(jobs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    new_count = 0
    duplicate_count = 0
    for job in jobs:
        job_id = fingerprint(job.get("title",""), job.get("company",""), job.get("location",""))
        c.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
        if c.fetchone():
            duplicate_count += 1
            continue
        c.execute("""INSERT INTO jobs (
            id, title, company, location, source, date_posted,
            date_found, job_url, description, status, country,
            is_remote, visa_required, search_pass
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""UPDATE jobs SET is_stale = 1
        WHERE status = 'new' AND date_found < datetime('now', '-7 days')""")
    stale = conn.total_changes
    conn.commit()
    conn.close()
    if stale > 0:
        print(f"  Marked {stale} jobs as stale (older than 7 days)")

def run_scrape():
    print("\n" + "="*50)
    print(f"Job scrape started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    init_db()
    config = load_config()
    exclude = config.get("exclude_keywords", [])
    all_jobs = []

    print("\n--- Pass 1: Canada Remote ---")
    all_jobs.extend(run_search(CORE_TITLES, "Canada", "canada", exclude,
                               is_remote_search=True, results=25, pass_name="canada_remote"))
    print("\n--- Pass 2: Canada Hybrid ---")
    all_jobs.extend(run_search(CORE_TITLES, "Canada", "canada", exclude,
                               results=20, pass_name="canada_hybrid"))
    print("\n--- Pass 3: Canada Wide ---")
    all_jobs.extend(run_search(CORE_TITLES, "Canada", "canada", exclude,
                               results=15, pass_name="canada"))
    print("\n--- Pass 4: Ottawa ---")
    all_jobs.extend(run_search(OTTAWA_TITLES, "Ottawa, Ontario", "canada", exclude,
                               results=20, pass_name="ottawa"))
    print("\n--- Pass 5: US Remote ---")
    all_jobs.extend(run_search(CORE_TITLES, "United States", "us", exclude,
                               is_remote_search=True, results=20, pass_name="us_remote"))
    print("\n--- Pass 6: Contract ---")
    all_jobs.extend(run_search(CONTRACT_TITLES, "Canada", "canada", exclude,
                               results=15, pass_name="contract"))

    print("\n--- Saving results ---")
    total_new = save_jobs(all_jobs)
    mark_stale_jobs()

    print("\n" + "="*50)
    print(f"Scrape complete. {total_new} new jobs added.")
    from collections import Counter
    passes = Counter(j["search_pass"] for j in all_jobs)
    for p, count in sorted(passes.items()):
        print(f"  {p}: {count} found")
    print("="*50)
    return total_new

if __name__ == "__main__":
    run_scrape()
