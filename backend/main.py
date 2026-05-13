"""
main.py — FastAPI application entry point for GradeAI backend.

Startup sequence:
  1. Creates all database tables via SQLAlchemy (idempotent)
  2. Mounts the three routers: /papers, /questions, /grade

Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import time
import traceback

import anthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers import papers, questions, grading

app = FastAPI(
    title="GradeAI API",
    description="AI-powered IGCSE answer grading using Claude",
    version="0.1.0",
)

# Allow all origins — required for Expo Go on a local network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(papers.router)
app.include_router(questions.router)
app.include_router(grading.router)


@app.on_event("startup")
def startup_event():
    """Create all DB tables on first run (idempotent)."""
    import models  # noqa: F401 — ensure models are registered on Base before create_all
    Base.metadata.create_all(bind=engine)
    print("GradeAI backend started — DB tables ready.")


@app.get("/health")
def health():
    """Liveness check. Includes the deployed git SHA so we can verify
    that Railway is running the expected commit (set by Railway as
    RAILWAY_GIT_COMMIT_SHA)."""
    return {
        "status": "ok",
        "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12],
        "async_grading": True,  # marker: present only on async-job code paths
    }


@app.get("/debug/anthropic-test")
def debug_anthropic_test():
    """Diagnostic endpoint — verifies the Railway → Anthropic connection.

    Returns whether ANTHROPIC_API_KEY is set, a redacted prefix to confirm
    the right key is deployed, and the result of a tiny live test call
    (with the real exception details on failure). Does NOT leak the key.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY") or ""
    result: dict = {
        "key_set": bool(api_key),
        "key_length": len(api_key),
        "key_prefix": (api_key[:15] + "...") if len(api_key) > 18 else "TOO SHORT",
    }

    if not api_key:
        result["test_call"] = "skipped (no key)"
        return result

    try:
        client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=20.0)
        t0 = time.time()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'ok' and nothing else."}],
        )
        result["test_call"] = "ok"
        result["test_duration_ms"] = int((time.time() - t0) * 1000)
        result["test_response"] = (msg.content[0].text if msg.content else "")[:80]
    except Exception as exc:
        result["test_call"] = "failed"
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
        cause = getattr(exc, "__cause__", None)
        result["error_cause"] = f"{type(cause).__name__}: {cause}" if cause else None
        result["traceback_tail"] = traceback.format_exc().splitlines()[-6:]
    return result
