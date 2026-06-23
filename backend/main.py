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
app.include_router(paper_generator.router, prefix="/api")
app.include_router(results.router, prefix="/api")

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
    """Create all DB tables on first run (idempotent)."""
    import models  # noqa: F401 — ensure models are registered on Base before create_all
    Base.metadata.create_all(bind=engine)
    # Start the Firestore-driven grading queue listener on a daemon thread. It
    # replaces FastAPI BackgroundTasks (which Railway kills for long jobs) and
    # runs for the lifetime of the process without blocking the server.
    start_marking_listener()
    print("GradeAI backend started — DB tables ready, marking queue listening.")


@app.get("/health")
def health():
    """Liveness check used by Railway and the mobile app. Includes a UTC
    timestamp and the deployed git SHA (set by Railway as
    RAILWAY_GIT_COMMIT_SHA) so we can confirm the expected commit is live."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12],
    }
