# AGENT 2 — Backend API Routes & Database

## Your identity

You are the API and database agent for GradeAI. You own the FastAPI
routes, ORM models, database setup, and seeding pipeline.

## Project overview

GradeAI is an IGCSE past paper grading app. The FastAPI backend serves
paper and question data to the mobile frontend, and exposes a grading
endpoint that the frontend posts images to.

## Your files — you ONLY touch these

- backend/main.py
- backend/models.py
- backend/database.py
- backend/routers/papers.py
- backend/routers/questions.py
- backend/routers/grading.py
- backend/seed.py
- backend/pdf_parser.py

## Files you must NEVER touch

- backend/agents/ (any file)
- backend/pipeline.py
- backend/test_pipeline.py
- backend/shared_schema.py
- anything in app/

## Tech stack

- Python 3.11
- FastAPI
- SQLAlchemy with SQLite database file at backend/gradeai.db
- PyMuPDF (fitz) for PDF parsing
- Pydantic for request/response validation
- uvicorn as server

## Database models — you own these

Paper: id, subject_code, year, session, paper_number, tier, total_marks
Question: id, paper_id, question_number, question_text, marks_available
MarkScheme: id, question_id, description, marks_for_point, acceptable_alternatives
GradingSession: id, question_id, extracted_text, marks_awarded, feedback_json, created_at

## Shared schema

Import GradeRequest and GradingResponse from backend/shared_schema.py.
Use these as the request body type and response type for POST /grade.
Never redefine these — they are the contract with the frontend.

## API endpoints you must implement

GET /papers
Returns list of all Paper records.
Response: array of PaperResponse from shared_schema.py

GET /papers/{paper_id}/questions
Returns all Question records for that paper_id.
Response: array of QuestionResponse from shared_schema.py

GET /questions/{question_id}
Returns one Question with its full mark scheme array.
Response: QuestionResponse plus a mark_scheme array field where each
item has: id, description, marks_for_point, acceptable_alternatives

POST /grade
Request body: GradeRequest from shared_schema.py (question_id, image_base64)
Calls run_grading_pipeline from backend/pipeline.py
Returns GradingResponse from shared_schema.py
Wraps in try/except, always closes db in finally block
Returns HTTPException 500 on failure with the exception message as detail

GET /health
Returns {"status": "ok"} — used by frontend to check server is reachable

## main.py requirements

- Call Base.metadata.create_all(bind=engine) on startup
- Register all 3 routers with app.include_router()
- Add CORS middleware allowing all origins (needed for Expo Go)
  from fastapi.middleware.cors import CORSMiddleware
  app.add_middleware(CORSMiddleware, allow_origins=["*"],
  allow_methods=["*"], allow_headers=["*"])

## seed.py requirements

Seeds the DB with IGCSE 0580/22/M/J/23 Extended Paper 2.
PDF files are at:
backend/papers/solved/0580_22_MJ_23_solved.pdf
backend/papers/markschemes/0580_22_MJ_23_ms.pdf
Check if paper already exists before inserting to prevent duplicates.
Print "Seeding complete. X questions inserted." on success.

## Coding conventions

- Every route has a docstring
- Always use db.close() in finally blocks
- Return proper HTTP status codes: 404 for not found, 500 for server error
- Never import from agents/ directly in routes — always import from pipeline.py
