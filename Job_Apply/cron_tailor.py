"""Entry point for the GitHub Actions tailor workflow (see
.github/workflows/tailor.yml). Generates one tailored resume and writes the
result to the jobs.tailor_result column, then exits.

Tailoring involves a large Claude call (max_tokens=16000), a Node.js
subprocess to build the .docx, and a Blob storage upload — comfortably over
Vercel's serverless function timeout on the Hobby plan (confirmed in
production: it timed out at 60s every time). Running it here instead means
/api/jobs/<id>/tailor only has to dispatch this workflow and return, while
the dashboard polls /api/jobs/<id>/tailor-status for the result.
"""
import json
import os

from db import get_db
from tailor import tailor_for_job, build_tailored_docx


def _save_result(conn, job_id, result):
    conn.execute(
        "UPDATE jobs SET tailor_result = %s WHERE id = %s",
        (json.dumps(result), job_id),
    )
    conn.commit()


def main():
    job_id = os.environ["TAILOR_JOB_ID"]
    intake_answers = json.loads(os.environ.get("TAILOR_INTAKE_ANSWERS") or "{}") or None

    conn = get_db()
    try:
        result = tailor_for_job(job_id, intake_answers=intake_answers)
        if "error" in result:
            _save_result(conn, job_id, {"status": "error", "error": result["error"]})
            print(f"Tailor failed: {result['error']}")
            return

        docx_result = build_tailored_docx(result)
        if not docx_result.get("success"):
            error = docx_result.get("error") or "Failed to generate docx"
            _save_result(conn, job_id, {"status": "error", "error": error})
            print(f"Docx build failed: {error}")
            return

        conn.execute(
            "UPDATE jobs SET resume_path = %s, tailor_result = %s WHERE id = %s",
            (
                docx_result["path"],
                json.dumps({
                    "status": "done",
                    "jd_narrative": result.get("jd_narrative"),
                    "gate_scores": result.get("gate_scores"),
                    "gaps": result.get("gaps"),
                    "filename": docx_result.get("filename"),
                    "resume_path": docx_result["path"],
                }),
                job_id,
            ),
        )
        conn.commit()
        print(f"Tailor complete for {job_id}: {docx_result['filename']}")
    except Exception as e:
        _save_result(conn, job_id, {"status": "error", "error": str(e)})
        print(f"Tailor crashed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
