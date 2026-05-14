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
    raw_key = os.getenv("ANTHROPIC_API_KEY") or ""
    api_key = raw_key.strip()
    result: dict = {
        "key_set": bool(api_key),
        "key_length_raw": len(raw_key),
        "key_length_stripped": len(api_key),
        "had_trailing_whitespace": raw_key != api_key,
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
            temperature=0,
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


@app.get("/debug/vision-test")
def debug_vision_test():
    """Test a multimodal (image + text) call — the exact type grading uses.

    /debug/model-access only sends text. Real grading sends base64 images.
    This endpoint sends a tiny 1x1 white JPEG alongside a text prompt so we
    can confirm the key/account supports vision requests, not just text.
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return {"error": "no key"}

    # Minimal 1×1 white JPEG, base64-encoded
    tiny_jpeg_b64 = (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
        "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDB"
        "gNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/E"
        "ABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAA"
        "AAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AJQAB/9k="
    )

    try:
        client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=20.0)
        t0 = time.time()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": tiny_jpeg_b64,
                        },
                    },
                    {"type": "text", "text": "Say 'ok' and nothing else."},
                ],
            }],
        )
        return {
            "status": "ok",
            "duration_ms": int((time.time() - t0) * 1000),
            "response": (msg.content[0].text if msg.content else "")[:40],
        }
    except Exception as exc:
        cause = getattr(exc, "__cause__", None)
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],
            "error_cause": f"{type(cause).__name__}: {cause}" if cause else None,
        }


@app.get("/debug/model-access")
def debug_model_access():
    """Test the same API key against every model the codebase uses.

    /debug/anthropic-test passed but real grading fails with 'Invalid API key'.
    The only meaningful difference between the two paths is the model name.
    This endpoint pings each model with the same client config as grading
    so we can pinpoint exactly which model the key is being rejected for.
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return {"error": "no key"}

    models = [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
    ]

    results: dict = {}
    for model in models:
        try:
            client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=20.0)
            msg = client.messages.create(
                model=model,
                max_tokens=10,
                temperature=0,
                messages=[{"role": "user", "content": "ok"}],
            )
            results[model] = {
                "status": "ok",
                "response": (msg.content[0].text if msg.content else "")[:40],
            }
        except Exception as exc:
            results[model] = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:300],
            }

    return {"key_prefix": api_key[:15] + "...", "tests": results}
