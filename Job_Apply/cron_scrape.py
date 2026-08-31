"""Entry point for the scheduled GitHub Actions scrape (see
.github/workflows/scrape.yml). Runs one full scrape + score pass and exits —
unlike scheduler.py's BlockingScheduler, which is meant for a
persistent process and isn't a fit for a CI job.

Scraping every configured market via live Indeed/LinkedIn lookups routinely
takes minutes, which is why this no longer runs inside the Vercel-hosted
Flask app's request/response cycle (see app.py's /refresh) — it reliably blew
past Vercel's serverless function timeout. Running it here instead, against
the same Postgres database, means the dashboard only ever has to read
whatever this job already wrote.
"""
from scraper import run_scrape
from scorer import score_all_unscored


def main():
    new_jobs = run_scrape()
    if new_jobs > 0:
        try:
            scored = score_all_unscored()
            print(f"Scored {scored} jobs")
        except Exception as e:
            print(f"Scoring error: {e}")
    print(f"Done. {new_jobs} new job(s) added.")


if __name__ == "__main__":
    main()
