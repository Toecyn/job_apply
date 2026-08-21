import json
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv
from db import get_db

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def get_new_high_scoring_jobs():
    conn = get_db()
    jobs = conn.execute("""
        SELECT * FROM jobs
        WHERE score >= 70
        AND is_stale = 0
        AND status = 'new'
        ORDER BY score DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return [dict(j) for j in jobs]


def get_unscored_jobs_count():
    conn = get_db()
    count = conn.execute("""
        SELECT COUNT(*) FROM jobs
        WHERE score IS NULL AND is_stale = 0
    """).fetchone()[0]
    conn.close()
    return count


def get_stats():
    conn = get_db()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM jobs WHERE is_stale = 0").fetchone()[0],
        "new": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'new' AND is_stale = 0").fetchone()[0],
        "high_match": conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 70 AND is_stale = 0").fetchone()[0],
        "applied": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'").fetchone()[0],
    }
    conn.close()
    return stats


def build_email_html(jobs, stats, unscored_count):
    date_str = datetime.now().strftime("%A, %B %d %Y")

    job_rows = ""
    if jobs:
        for job in jobs:
            score = job.get("score", 0)
            if score >= 85:
                score_color = "#1e7e34"
                score_bg = "#e6f4ea"
            elif score >= 70:
                score_color = "#856404"
                score_bg = "#fff3cd"
            else:
                score_color = "#666"
                score_bg = "#f0f0f0"

            reasons = ""
            if job.get("score_reasons"):
                try:
                    reason_list = json.loads(job["score_reasons"])
                    if reason_list:
                        reasons = "<br><small style='color:#666'>" + " &nbsp;·&nbsp; ".join(reason_list[:2]) + "</small>"
                except Exception:
                    pass

            job_rows += f"""
            <tr>
                <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0">
                    <strong style="font-size:14px">{job['title']}</strong><br>
                    <span style="color:#444;font-size:13px">{job['company']}</span>
                    <span style="color:#888;font-size:12px"> &nbsp;·&nbsp; {job['location']}</span>
                    {reasons}
                </td>
                <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;text-align:center;white-space:nowrap">
                    <span style="background:{score_bg};color:{score_color};padding:4px 10px;border-radius:20px;font-size:13px;font-weight:600">
                        {score}/100
                    </span>
                </td>
                <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;text-align:center">
                    <span style="color:#888;font-size:12px">{job['source']}</span>
                </td>
                <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;text-align:center">
                    <a href="{job['job_url']}" style="background:#1F4E79;color:white;padding:6px 14px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:500">
                        View
                    </a>
                </td>
            </tr>
            """
    else:
        job_rows = """
        <tr>
            <td colspan="4" style="padding:24px;text-align:center;color:#888">
                No high-scoring jobs yet. Add your Anthropic API key to start scoring.
            </td>
        </tr>
        """

    unscored_note = ""
    if unscored_count > 0:
        unscored_note = f"""
        <p style="margin:16px 0 0;padding:12px 16px;background:#fff3cd;border-radius:6px;font-size:13px;color:#856404">
            {unscored_count} jobs in your database have not been scored yet.
            Add your Anthropic API key to score them automatically.
        </p>
        """

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:680px;margin:24px auto;background:white;border-radius:10px;overflow:hidden;border:1px solid #e5e5e5">
    <div style="background:#1F4E79;padding:24px 28px">
        <h1 style="color:white;font-size:20px;margin:0">Job Apply - Daily Digest</h1>
        <p style="color:#b8d4f0;margin:6px 0 0;font-size:13px">{date_str}</p>
    </div>
    <div style="padding:20px 28px">
        <table style="width:100%;border-collapse:collapse">
            <tr>
                <td style="text-align:center;padding:12px;background:#f8f9fa;border-radius:8px">
                    <div style="font-size:24px;font-weight:600;color:#1F4E79">{stats['total']}</div>
                    <div style="font-size:11px;color:#666;margin-top:2px">Total jobs</div>
                </td>
                <td style="width:12px"></td>
                <td style="text-align:center;padding:12px;background:#f8f9fa;border-radius:8px">
                    <div style="font-size:24px;font-weight:600;color:#1F4E79">{stats['new']}</div>
                    <div style="font-size:11px;color:#666;margin-top:2px">New</div>
                </td>
                <td style="width:12px"></td>
                <td style="text-align:center;padding:12px;background:#f8f9fa;border-radius:8px">
                    <div style="font-size:24px;font-weight:600;color:#1e7e34">{stats['high_match']}</div>
                    <div style="font-size:11px;color:#666;margin-top:2px">Strong matches</div>
                </td>
                <td style="width:12px"></td>
                <td style="text-align:center;padding:12px;background:#f8f9fa;border-radius:8px">
                    <div style="font-size:24px;font-weight:600;color:#1F4E79">{stats['applied']}</div>
                    <div style="font-size:11px;color:#666;margin-top:2px">Applied</div>
                </td>
            </tr>
        </table>
    </div>
    <div style="padding:0 28px 24px">
        <h2 style="font-size:15px;font-weight:600;color:#1a1a1a;margin:0 0 12px">Top matches (score 70+)</h2>
        <table style="width:100%;border-collapse:collapse">
            <thead>
                <tr style="background:#f8f9fa">
                    <th style="padding:10px 8px;text-align:left;font-size:12px;color:#666;font-weight:500">Role</th>
                    <th style="padding:10px 8px;text-align:center;font-size:12px;color:#666;font-weight:500">Score</th>
                    <th style="padding:10px 8px;text-align:center;font-size:12px;color:#666;font-weight:500">Source</th>
                    <th style="padding:10px 8px;text-align:center;font-size:12px;color:#666;font-weight:500">Link</th>
                </tr>
            </thead>
            <tbody>{job_rows}</tbody>
        </table>
        {unscored_note}
    </div>
    <div style="padding:16px 28px;background:#f8f9fa;border-top:1px solid #e5e5e5">
        <p style="margin:0;font-size:12px;color:#888">
            Open your dashboard at
            <a href="http://127.0.0.1:5000" style="color:#1F4E79">http://127.0.0.1:5000</a>
            to review jobs, update statuses, and tailor your resume.
        </p>
    </div>
</div>
</body>
</html>"""
    return html


def send_digest():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("Gmail credentials not set in .env - skipping email")
        return False

    if GMAIL_APP_PASSWORD == "your_app_password_here":
        print("Gmail app password not configured - skipping email")
        return False

    jobs = get_new_high_scoring_jobs()
    stats = get_stats()
    unscored_count = get_unscored_jobs_count()

    html = build_email_html(jobs, stats, unscored_count)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Digest - {stats['high_match']} strong matches, {stats['new']} new jobs"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        print(f"Digest sent to {GMAIL_ADDRESS}")
        print(f"  Stats: {stats['total']} total, {stats['high_match']} strong matches, {stats['new']} new")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


if __name__ == "__main__":
    print("Sending job digest...")
    send_digest()
