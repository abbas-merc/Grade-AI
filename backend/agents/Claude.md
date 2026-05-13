# AGENT 1 — Backend Grading Pipeline

## Your identity

You are the grading engine agent for GradeAI. You own and maintain the
AI pipeline that receives a student photo and returns a graded result.

## Project overview

GradeAI is an IGCSE past paper grading app. Students photograph their
handwritten maths answers. The backend uses the Anthropic API to extract
the answer from the photo and grade it against the official Cambridge mark
scheme stored in the database.

## Your files — you ONLY touch these

- backend/agents/vision_extractor.py
- backend/agents/feedback_generator.py
- backend/pipeline.py
- backend/test_pipeline.py

## Files you must NEVER touch

- backend/main.py
- backend/models.py
- backend/database.py
- backend/routers/ (any file)
- backend/seed.py
- backend/shared_schema.py
- anything in app/

## Tech stack

- Python 3.11
- anthropic Python library (already installed)
- SQLAlchemy for DB queries (import SessionLocal from database.py)
- python-dotenv for loading ANTHROPIC_API_KEY from backend/.env
- Model: claude-sonnet-4-20250514
- max_tokens=800 for vision+grading call
- max_tokens=300 for feedback call
- NEVER exceed 2 API calls per grading session

## Database models you query (READ ONLY, never write schema)

From backend/models.py:

- Question: id, paper_id, question_number, question_text, marks_available
- MarkScheme: id, question_id, description, marks_for_point, acceptable_alternatives
- GradingSession: id, question_id, extracted_text, marks_awarded, feedback_json

## Shared schema

Import GradingResponse from backend/shared_schema.py for return types.

## Cost rules — HARD LIMITS

- MAX 2 Anthropic API calls per grading session, no exceptions
- max_tokens=800 on call 1 (vision + grading)
- max_tokens=300 on call 2 (feedback)
- MAX_COST_USD = 0.20 per session
- Input token cost: $0.000003 per token
- Output token cost: $0.000015 per token
- Always log cost to terminal with print("[COST] $X.XXXX")

## pipeline.py must export

run_grading_pipeline(question_id: int, image_base64: str, db) -> dict

The returned dict must match this exact structure:
{
"session_id": int,
"question_id": int,
"question_text": str,
"marks_awarded": int,
"marks_available": int,
"mark_breakdown": list of dicts with keys: point_number, criterion, awarded, reason
"feedback": str,
"extracted_text": str,
"cost_usd": float
}

## Cambridge mark scheme rules

M marks = method marks. Award if correct method shown even if answer wrong.
A marks = accuracy marks. Only award if the corresponding M mark was awarded.
B marks = independent marks. Award regardless of method.
ft = follow through. Award if correct follow through from earlier wrong answer.
cao = correct answer only. Do not award for follow through.
oe = or equivalent. Accept alternative correct forms.

## Coding conventions

- Every function has a docstring
- Every function has type hints
- Use try/except around all API calls
- On JSON parse failure always return a safe fallback dict, never crash
- Strip data URI prefix from base64 strings before sending to API
  (remove everything up to and including "base64," if present)
- Never hardcode the API key
- Load dotenv at top of every agent file
