"""
models.py — SQLAlchemy ORM models for GradeAI.

Tables:
  papers           — An exam paper (e.g. IGCSE 0580 Paper 2 May/June 2023)
  questions        — Individual questions within a paper
  mark_schemes     — One row per mark point for a question
  grading_sessions — A student's submission + AI grading result
"""

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Paper(Base):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    subject_code = Column(String(50), nullable=False)      # e.g. "0580"
    year = Column(Integer, nullable=False)                  # e.g. 2023
    session = Column(String(20), nullable=False)            # e.g. "May/June"
    paper_number = Column(Integer, nullable=False)          # e.g. 2
    tier = Column(String(50), nullable=False)               # e.g. "Extended"
    total_marks = Column(Integer, nullable=False)

    questions = relationship("Question", back_populates="paper", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    question_number = Column(String(10), nullable=False)    # e.g. "1", "2a", "3b(i)"
    question_text = Column(Text, nullable=False)
    marks_available = Column(Integer, nullable=False)

    paper = relationship("Paper", back_populates="questions")
    mark_scheme = relationship(
        "MarkScheme", back_populates="question", cascade="all, delete-orphan"
    )
    grading_sessions = relationship(
        "GradingSession", back_populates="question", cascade="all, delete-orphan"
    )


class MarkScheme(Base):
    __tablename__ = "mark_schemes"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    description = Column(Text, nullable=False)              # What earns this mark
    marks_for_point = Column(Integer, nullable=False, default=1)
    acceptable_alternatives = Column(Text, nullable=True, default="")

    question = relationship("Question", back_populates="mark_scheme")


class GradingSession(Base):
    __tablename__ = "grading_sessions"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    extracted_text = Column(Text, nullable=True)            # Transcript from vision agent
    marks_awarded = Column(Float, nullable=True)
    feedback_json = Column(Text, nullable=True)             # JSON from feedback agent
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    question = relationship("Question", back_populates="grading_sessions")
