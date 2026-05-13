"""
main.py — FastAPI application entry point for GradeAI backend.

Startup sequence:
  1. Creates all database tables via SQLAlchemy (idempotent)
  2. Mounts the three routers: /papers, /questions, /grade

Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

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
    """Liveness check used by the frontend to verify the server is reachable."""
    return {"status": "ok"}
