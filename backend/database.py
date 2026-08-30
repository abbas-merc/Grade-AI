"""
database.py — SQLAlchemy engine + session factory for GradeAI.
All models import Base from here; main.py calls init_db() on startup.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

_SQLITE_URL = "sqlite:///./gradeai.db"

# os.getenv returns "" — not the default — when the variable is present but
# empty, which is exactly what a blank line in .env or an empty Railway variable
# produces. create_engine("") then raises, and because this module is imported by
# main.py at module scope the process dies before uvicorn binds: the platform
# reports a healthcheck failure with no application log to explain it.
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip() or _SQLITE_URL


def _make_engine(url: str):
    """Build the engine, falling back to SQLite rather than killing the process.

    A URL whose driver is not installed (DATABASE_URL pointing at Postgres with
    no psycopg2 in requirements.txt, say) raises at import for the same reason.
    Refusing to start is the wrong response to a misconfigured optional database:
    the app's real data lives in Firestore, so degrading to the local SQLite file
    keeps the service — and its healthcheck — alive while making the problem
    loud instead of silent.
    """
    try:
        return create_engine(
            url,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
    except Exception as exc:  # noqa: BLE001 — bad URL, or a driver that is not installed
        if url == _SQLITE_URL:
            raise
        print(f"[database] DATABASE_URL unusable ({exc.__class__.__name__}: {exc}); "
              f"falling back to {_SQLITE_URL}")
        return create_engine(_SQLITE_URL, connect_args={"check_same_thread": False})


engine = _make_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and closes it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once at app startup."""
    from models import Paper, Question, MarkScheme, GradingSession  # noqa: F401
    Base.metadata.create_all(bind=engine)
