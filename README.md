# GradeAI

GradeAI is an AI-powered past paper grading app for IGCSE students. A student selects a past paper, picks a question, and photographs their handwritten answer. The app runs the image through a multi-agent pipeline built on the Anthropic API, returning a mark out of the available marks alongside a point-by-point breakdown of exactly which marking criteria were met and missed — mirroring how a real Cambridge examiner grades it. Every mark scheme is pre-loaded from official Cambridge PDFs, so students get accurate, examiner-style feedback instantly rather than waiting for a teacher to mark their work.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Mobile frontend | React Native, Expo SDK 54, Expo Router, TypeScript |
| HTTP client | Axios |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLAlchemy ORM — SQLite (development), PostgreSQL (production) |
| AI | Anthropic API — `claude-sonnet-4-6` |
| PDF parsing | PyMuPDF (`fitz`) |
| Image handling | expo-image-picker — base64 encoded and sent directly in the request body |
| Deployment | Railway — Procfile + `railway.toml` |

---

## Running the Backend Locally

**Prerequisites:** Python 3.12, a virtual environment tool, and an Anthropic API key.

```bash
# 1. Move into the backend directory
cd backend

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Open .env and paste your Anthropic API key

# 5. Seed the database with the included past paper
python seed.py

# 6. Start the server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://10.0.2.2:8000`. Interactive docs are at `http://10.0.2.2:8000/docs`.

> **Mobile testing:** Your iPhone and PC must be on the same Wi-Fi network. The Expo app auto-detects the server IP from the Metro bundler host — no manual IP configuration needed.

---

## Architecture

### Grading Pipeline

Each student submission flows through a two-call AI pipeline. Cost is hard-capped at **$0.20 per question** and logged to the terminal on every run.

```
Student photo (base64)
        │
        ▼
┌───────────────────┐
│  Vision Extractor │  ← API call 1  (vision + grading combined)
│  + Grader         │
└───────────────────┘
        │  extracted text, marks awarded, mark breakdown
        ▼
┌───────────────────┐
│ Feedback Generator│  ← API call 2  (text-only, cheap)
└───────────────────┘
        │  feedback paragraph
        ▼
   GradingSession saved to DB → JSON response to app
```

### Agents

#### `vision_extractor.py`
Receives the base64 image, the question text, and the mark scheme. In a single API call it transcribes the student's handwritten work and grades it criterion-by-criterion against the mark scheme, returning a structured JSON result with `marks_awarded`, `mark_breakdown`, and token usage. Combines what would otherwise be two calls (OCR + grading) into one to halve cost. Never raises — returns a safe fallback dict with `marks_awarded: 0` on any API or parse failure.

#### `feedback_generator.py`
Receives the grading result as plain text (no image) and generates one short, encouraging feedback paragraph for a student aged 14–17. Jargon-free, 3–5 sentences, text-only so the call is minimal cost (`max_tokens=300`). Never raises — returns a user-friendly fallback message if the call fails so the grading result is still shown to the student.

#### `grader.py`
Standalone grading agent that takes a pre-transcribed student answer and a parsed list of mark scheme criteria and decides which marks to award. Used independently of the vision step when the answer text is already known. Returns `marks_awarded`, `max_marks`, and a per-criterion `breakdown` array.

#### `markscheme_parser.py`
Parses raw mark scheme text extracted from Cambridge PDFs into structured criterion objects. Handles Cambridge notation — M marks (method), A marks (accuracy, dependent on M), B marks (independent), and qualifiers such as `ft` (follow through), `cao` (correct answer only), and `oe` (or equivalent).

### Cambridge Marking Rules

The grading agents apply Cambridge IGCSE conventions exactly:

- **M marks** — awarded for correct method, even if the final answer is wrong
- **A marks** — only awarded if the corresponding M mark was also awarded
- **B marks** — awarded independently of method
- **ft** — follow-through: award if the student correctly applied an earlier wrong result
- **cao** — correct answer only: no follow-through accepted
- **oe** — or equivalent: any mathematically equivalent form is accepted

### API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — returns `{"status": "ok"}` |
| `GET` | `/papers` | List all available exam papers |
| `GET` | `/papers/{id}/questions` | List all questions for a paper |
| `GET` | `/questions/{id}` | Question detail with full mark scheme |
| `POST` | `/grade` | Grade a single question from a photo |
| `POST` | `/grade/paper` | Grade an entire paper from page photos |

---

## Environment Variables

Create a `.env` file in the `backend/` directory based on `.env.example`:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | API key from [console.anthropic.com](https://console.anthropic.com) |
| `DATABASE_URL` | No | SQLAlchemy connection string. Defaults to `sqlite:///./gradeai.db` |

On Railway, both variables are set in the service's **Variables** tab. `PORT` is injected automatically by Railway and does not need to be set manually.

---

## Project Structure

```
Grade-AI/
├── Procfile                  # Railway / Heroku process definition
├── railway.toml              # Railway build and deploy config
├── app/                      # React Native Expo frontend
│   ├── app/                  # Expo Router screens
│   ├── components/           # Reusable UI components
│   ├── constants/config.ts   # API base URL (auto-detected from Metro host)
│   ├── services/api.ts       # Typed Axios API client
│   └── types/index.ts        # Shared TypeScript interfaces
└── backend/                  # FastAPI backend
    ├── agents/               # AI pipeline agents
    │   ├── vision_extractor.py
    │   ├── feedback_generator.py
    │   ├── grader.py
    │   └── markscheme_parser.py
    ├── routers/              # FastAPI route handlers
    ├── papers/               # Cambridge PDF source files
    ├── main.py               # App entry point
    ├── pipeline.py           # Orchestrates the grading pipeline
    ├── models.py             # SQLAlchemy ORM models
    ├── database.py           # Engine and session factory
    ├── seed.py               # Populates DB from PDFs
    ├── pdf_parser.py         # Extracts questions from Cambridge PDFs
    ├── shared_schema.py      # Pydantic request/response schemas
    ├── requirements.txt      # Pinned Python dependencies
    └── .env.example          # Environment variable template
```
