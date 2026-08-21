import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from scraper import run_scrape

scheduler = BlockingScheduler()


def scheduled_scrape():
    print(f"\n[Scheduler] Triggered at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        new_jobs = run_scrape()
        print(f"[Scheduler] Done. {new_jobs} new jobs added.")
        if new_jobs > 0:
            try:
                from batch_scorer import score_batch
                score_batch()
                print(f"[Scheduler] Batch scoring initiated.")
            except Exception as e:
                print(f"[Scheduler] Batch scoring error: {e}. Falling back to real-time.")
                try:
                    from scorer import score_all_unscored
                    score_all_unscored()
                except Exception as e2:
                    print(f"[Scheduler] Real-time scoring error: {e2}")
    except Exception as e:
        print(f"[Scheduler] Scrape error: {e}")


# Evidence-based schedule:
# 7:30am  — catches overnight and early morning postings
# 10:00am — Tuesday/Wednesday peak posting window
# 4:00pm  — 2026 data shows 3-8pm is peak LinkedIn engagement
# 8:00pm  — catches late evening postings and Friday contract roles

scheduler.add_job(scheduled_scrape, CronTrigger(hour=7, minute=30))
scheduler.add_job(scheduled_scrape, CronTrigger(hour=10, minute=0))
scheduler.add_job(scheduled_scrape, CronTrigger(hour=16, minute=0))
scheduler.add_job(scheduled_scrape, CronTrigger(hour=20, minute=0))

print("="*50)
print("Scheduler running — 4 daily runs:")
print("  7:30am | 10:00am | 4:00pm | 8:00pm")
print("  Auto-scores new jobs after each run")
print("Press Ctrl+C to stop")
print("="*50)

scheduler.start()
