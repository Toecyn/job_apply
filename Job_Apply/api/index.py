"""Vercel entrypoint.

Vercel's Python runtime (functions/rewrites config, not the legacy `builds`
format) discovers serverless functions under /api. This file just re-exports
the real Flask app from app.py at the project root so the whole app can live
in one place instead of being restructured into api/*.py per-route files.

This split exists for one reason: `maxDuration` cannot be set in vercel.json
while using the legacy `builds`/`routes` config (Vercel rejects the two
together). Moving to functions/rewrites is what makes the timeout override
possible for the long-running /refresh scrape.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app  # noqa: E402,F401
