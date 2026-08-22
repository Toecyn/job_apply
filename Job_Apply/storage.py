"""
Thin wrapper around Vercel Blob's HTTP API for the two binary artifacts
this app produces: uploaded resumes (Settings) and tailored resume .docx
files (tailor.py). Serverless functions on Vercel have no writable or
persistent filesystem outside /tmp, so anything meant to survive past one
request — and be downloadable afterwards — has to live in real storage
instead of the local `output/` directory tailor.py wrote to before.

Requires BLOB_READ_WRITE_TOKEN in the environment. Vercel sets this
automatically once Blob storage is attached to the project (Storage tab
in the Vercel dashboard → Create Database → Blob); it's also picked up
locally via .env for `vercel env pull`.

NOTE: this implements Vercel Blob's documented raw-HTTP upload contract
(no @vercel/blob JS SDK dependency, since this is a Python codebase).
Outbound network access to vercel.com was blocked in the environment this
was written in, so the exact header/response shape below could not be
verified live against current docs — smoke-test upload()/delete() against
a real BLOB_READ_WRITE_TOKEN before relying on this in production, and
check https://vercel.com/docs/vercel-blob if it doesn't work first try.
"""
import os
import requests

BLOB_API = "https://blob.vercel-storage.com"


def _token():
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN is not set — attach Vercel Blob storage "
            "to this project (Storage tab in the Vercel dashboard) and "
            "redeploy before uploading files."
        )
    return token


def upload(path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to Vercel Blob at `path` and return the public URL.

    A random suffix is added to the path so re-uploading a resume with the
    same filename never collides with or silently overwrites a prior one.
    """
    resp = requests.put(
        f"{BLOB_API}/{path.lstrip('/')}",
        data=data,
        headers={
            "authorization": f"Bearer {_token()}",
            "x-content-type": content_type,
            "x-add-random-suffix": "1",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["url"]


def delete(url: str):
    """Best-effort delete — swallow failures so a cleanup call never blocks
    the request that triggered it (e.g. replacing an old resume)."""
    try:
        resp = requests.post(
            f"{BLOB_API}/delete",
            json={"urls": [url]},
            headers={"authorization": f"Bearer {_token()}"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"storage.delete: failed to delete {url}: {e}")
