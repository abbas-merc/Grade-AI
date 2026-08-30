"""
main.py — FastAPI application entry point for GradeAI backend.

Startup sequence:
  1. Creates all database tables via SQLAlchemy (idempotent)
  2. Mounts the three routers: /papers, /questions, /grade

Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import traceback
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from database import Base, engine
from routers import papers, questions, grading, paper_generator, results
from marking_worker import start_marking_listener

# Expose the interactive API docs (/docs, /redoc, /openapi.json) only outside
# production, or when ENABLE_DOCS=true is set explicitly. In production they add
# nothing for end users (native app) and only hand an attacker a full map of the
# API surface, so default to off. "Production" == auth is required.
_auth_required = os.getenv("AUTH_REQUIRED", "true").strip().lower() not in (
    "false", "0", "no", "off",
)
_enable_docs = os.getenv("ENABLE_DOCS", "").strip().lower() in ("true", "1", "yes", "on")
_docs_on = _enable_docs or not _auth_required

app = FastAPI(
    title="GradeAI API",
    description="AI-powered IGCSE answer grading using Claude",
    version="0.1.0",
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)

# CORS. The clients are native mobile apps that authenticate with a Firebase
# Bearer token (never cookies), so credentialed cross-site requests are not a
# thing we need — and `allow_credentials=True` alongside a "*" origin is an
# invalid, contradictory combination browsers reject anyway. We therefore keep
# credentials OFF, which makes a permissive origin list safe: a browser page on
# another origin still cannot read a victim's data because it has no way to
# obtain their Bearer token. CORS_ALLOW_ORIGINS (comma-separated) can pin this to
# specific web origins if a web client is ever added.
_cors_env = (os.getenv("CORS_ALLOW_ORIGINS") or "*").strip()
_allowed_origins = ["*"] if _cors_env == "*" else [
    o.strip() for o in _cors_env.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Each router is mounted defensively. An exception while wiring one of these
# propagates out of module scope, uvicorn never binds, and the platform reports
# only "healthcheck failed" — it keeps the previous container and the deploy
# silently does nothing, which is how a missing module went unnoticed through two
# releases. Degrading one feature is recoverable and visible; a service that
# refuses to boot is neither. Failures are surfaced by /health, not swallowed.
_DEGRADED: list[str] = []


def _mount(router_module, name: str, **kwargs) -> None:
    try:
        app.include_router(router_module.router, **kwargs)
    except Exception as exc:  # noqa: BLE001
        _DEGRADED.append(f"{name}: {exc.__class__.__name__}: {exc}")
        print(f"[startup] router {name!r} FAILED to mount — {exc!r}")
        traceback.print_exc()


_mount(papers, "papers")
_mount(questions, "questions")
_mount(grading, "grading")
_mount(paper_generator, "paper_generator", prefix="/api")
_mount(results, "results", prefix="/api")

# Serve the extracted question diagrams (committed under static/question_diagrams)
# at /diagrams/<questionId>.png. These back the `imageUrl` ("/diagrams/<id>.png")
# stored on each diagram question — the app prepends its own BASE_URL, and the
# PDF generator reads the same files off disk. (Firebase Storage was unavailable:
# the project has no billing account, so a bucket cannot be provisioned.)
_DIAGRAMS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "question_diagrams")
os.makedirs(_DIAGRAMS_DIR, exist_ok=True)
app.mount("/diagrams", StaticFiles(directory=_DIAGRAMS_DIR), name="diagrams")

# Serve the cropped question-snippet images (committed under
# static/question_snippets) at /question_snippets/<id>.png. These back the
# `questionImageUrl` ("/question_snippets/<id>.png") stored on every question in
# the image-snippet bank — the app prepends its BASE_URL and the question-paper
# PDF generator reads the same files off disk. (Firebase Storage is unavailable:
# the project has no billing account, so a bucket cannot be provisioned.)
_SNIPPETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "question_snippets")
os.makedirs(_SNIPPETS_DIR, exist_ok=True)
app.mount("/question_snippets", StaticFiles(directory=_SNIPPETS_DIR), name="question_snippets")

# Serve the diagram-only crops the LaTeX typesetting pipeline anchors inside each
# sub-part (and inside a question stem or a letter part's introduction). Produced
# by scripts/build_part_figures.py, copied here by scripts/publish_latex_assets.py,
# and read straight off disk by the typesetter. The stem *text* crops live only
# under scripts/ — they are input to the offline extraction, never rendered.
_FIGURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "question_figures")
os.makedirs(_FIGURES_DIR, exist_ok=True)
app.mount("/question_figures", StaticFiles(directory=_FIGURES_DIR), name="question_figures")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return a clean JSON 500 for any unhandled error instead of FastAPI's
    default plain-text/HTML 500 page, so the mobile client always parses a
    `detail` field. HTTPExceptions are handled by FastAPI's own handler and do
    not reach here, so deliberate 4xx responses keep their specific messages."""
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end. Please try again."},
    )


@app.on_event("startup")
def startup_event():
    """Prepare the DB and start the marking queue — without ever blocking boot.

    Neither of these is required to answer /health, and an exception raised here
    aborts startup so the server never binds: Railway's healthcheck then fails,
    it keeps the PREVIOUS container, and the deploy silently does nothing. That
    is a bad trade for optional work, so each step is guarded and its failure is
    logged and carried rather than taking the whole service down. A broken
    marking queue is a degraded feature; a container that never boots is an
    outage that also hides itself.
    """
    try:
        import models  # noqa: F401 — register models on Base before create_all
        Base.metadata.create_all(bind=engine)
    except Exception:
        print("[startup] DB table creation FAILED — continuing so /health can bind")
        traceback.print_exc()

    # Firestore-driven grading queue listener, on a daemon thread. It replaces
    # FastAPI BackgroundTasks (which Railway kills for long jobs) and runs for
    # the lifetime of the process without blocking the server.
    try:
        start_marking_listener()
    except Exception:
        print("[startup] marking-queue listener FAILED to start — continuing")
        traceback.print_exc()

    # Printed so a deploy log answers, on its own, the questions that otherwise
    # need a debugging session: which commit is running, which port it bound, and
    # whether anything failed to wire up.
    print(
        "GradeAI backend started"
        f" | commit={(os.getenv('RAILWAY_GIT_COMMIT_SHA') or 'unknown')[:12]}"
        f" | PORT={os.getenv('PORT') or '(unset, defaulted)'}"
        f" | degraded={_DEGRADED or 'none'}"
    )


@app.get("/health")
def health():
    """Liveness check used by Railway and the mobile app. Includes a UTC
    timestamp and the deployed git SHA (set by Railway as
    RAILWAY_GIT_COMMIT_SHA) so we can confirm the expected commit is live."""
    body = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12],
    }
    # Anything that failed to wire up at import. Reported rather than hidden, and
    # deliberately still a 200: the deploy should land and tell the truth about
    # what is broken, not be rolled back into a version that says nothing.
    if _DEGRADED:
        body["status"] = "degraded"
        body["degraded"] = _DEGRADED
    return body
