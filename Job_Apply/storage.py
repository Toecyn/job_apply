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

NOTE: Vercel only documents the @vercel/blob JS SDK — there is no official
raw-HTTP spec for other languages. This implements the SDK's actual wire
protocol (pathname as a query param, x-api-version/access headers), cross-
checked against community reimplementations (e.g.
github.com/SuryaSekhar14/vercel_blob) after an earlier version of this file
guessed a plausible-looking but wrong shape (path as a URL segment, no
x-api-version/access headers) and every upload silently failed and fell
back to a useless local /tmp path with no one noticing until a resume
"finished" with a dead download link. If uploads start failing again after
a Vercel Blob API change, check that project's source for the current
x-api-version value first.
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

    Verified against the @vercel/blob SDK's actual wire protocol (not
    documented for raw HTTP use — Vercel only publishes the JS SDK — so
    cross-checked against community reimplementations, e.g.
    github.com/SuryaSekhar14/vercel_blob): the pathname is a query param,
    not a URL path segment, and x-api-version/access are both required
    headers. The original version of this function got both wrong and
    every upload was silently failing and falling back to the local /tmp
    path (see build_tailored_docx()), which doesn't survive past one
    request/one CI job — so every "successful" tailor never actually
    produced a working download link.
    """
    resp = requests.put(
        f"{BLOB_API}/",
        params={"pathname": path.lstrip("/")},
        data=data,
        headers={
            "authorization": f"Bearer {_token()}",
            "x-api-version": "10",
            "access": "public",
            "x-content-type": content_type,
            "x-add-random-suffix": "1",
        },
        timeout=30,
    )
    # raise_for_status() alone only reports "400 Client Error: Bad Request"
    # with no indication of *why* — Vercel's actual JSON error body has that,
    # and losing it is exactly what made the previous wrong-shape request
    # (see the NOTE above) take multiple round-trips to actually diagnose.
    if not resp.ok:
        raise RuntimeError(f"Vercel Blob upload failed: {resp.status_code} {resp.text}")
    return resp.json()["url"]


def delete(url: str):
    """Best-effort delete — swallow failures so a cleanup call never blocks
    the request that triggered it (e.g. replacing an old resume)."""
    try:
        resp = requests.post(
            f"{BLOB_API}/delete",
            json={"urls": [url]},
            headers={
                "authorization": f"Bearer {_token()}",
                "x-api-version": "10",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"storage.delete: failed to delete {url}: {e}")
