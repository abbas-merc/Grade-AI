GradeAI — Project Context
What this app does
GradeAI is an AI-powered past paper grading app for IGCSE students. A student selects a past paper, picks a question, photographs their handwritten answer, and instantly receives a mark out of the available marks with a point-by-point breakdown of exactly which marking criteria they hit and missed — mirroring how a real Cambridge examiner grades it. The app stores grading history so students can track their progress over time. Future versions will expand to IBDP and add support for custom questions where students can upload their own mark schemes.
Tech stack

Mobile Frontend: React Native with Expo SDK 54, Expo Router (file-based navigation), TypeScript, Axios for HTTP
Backend: Python FastAPI, SQLAlchemy ORM, SQLite (MVP) → PostgreSQL (production)
AI: Anthropic API using claude-sonnet-4-20250514, 2 API calls per grading session (vision+grading combined, then feedback)
Image Handling: expo-image-picker for camera/gallery, base64 encoding sent directly to backend
Environment: python-dotenv for API key management
PDF Parsing: PyMuPDF (fitz) for extracting questions and mark schemes from Cambridge PDFs

Folder structure
C:\Dev\Grade AI\
├── app/ ← React Native Expo frontend
│ ├── app/ ← Expo Router screens
│ │ ├── \_layout.tsx ← Root navigation layout
│ │ ├── index.tsx ← Home screen, lists available papers
│ │ ├── paper/[id].tsx ← Question list for a selected paper
│ │ ├── question/[id].tsx ← Question detail + photo capture + submit
│ │ └── result/[sessionId].tsx← Grading result, score, breakdown, feedback
│ ├── components/ ← Reusable UI components
│ ├── constants/config.ts ← API base URL and app constants
│ ├── services/api.ts ← All Axios API call functions
│ ├── types/index.ts ← TypeScript interfaces
│ ├── app.json ← Expo config
│ └── package.json
│
└── backend/ ← Python FastAPI backend
├── agents/
│ ├── vision_extractor.py ← Agent 1: image → extracted text + grading (1 API call)
│ └── feedback_generator.py ← Agent 2: grading result → student feedback (1 API call)
├── routers/
│ ├── papers.py ← GET /papers, GET /papers/{id}/questions
│ ├── questions.py ← GET /questions/{id} with mark scheme
│ └── grading.py ← POST /grade
├── papers/
│ ├── solved/ ← Solved paper PDFs
│ └── markschemes/ ← Official Cambridge mark scheme PDFs
├── pipeline.py ← Orchestrates 2-agent grading pipeline
├── pdf_parser.py ← Extracts questions + mark schemes from PDFs
├── main.py ← FastAPI entry point
├── models.py ← ORM models: Paper, Question, MarkScheme, GradingSession
├── database.py ← SQLAlchemy engine and session
├── seed.py ← Seeds DB from PDF files
└── requirements.txt
What is already built and working

Full project scaffolding, both frontend and backend folders created
FastAPI server starts and runs without errors
SQLAlchemy database with all 4 ORM models: Paper, Question, MarkScheme, GradingSession
All backend API routes registered: /papers, /questions, /grading
PDF parser that extracts text from Cambridge past paper and mark scheme PDFs
Database seeder that reads PDFs and populates questions and mark schemes
One real paper seeded: IGCSE Mathematics 0580 Extended Paper 2 May/June 2023
2-agent grading pipeline (vision+grade in one call, feedback in second call)
Hard cost cap at $0.20 per question with terminal cost logging
POST /grade endpoint accepts base64 image + question_id and returns grading result
Expo app runs on iPhone via Expo Go with static screens

What is broken or half finished

Frontend screens are scaffolded but not wired to the real backend API
Paper list screen shows static/placeholder data, not real DB data
Question list screen not fetching real questions
Photo capture screen exists but does not submit to the grading endpoint
Result screen exists but displays no real data
No error handling on the frontend for failed API calls
No loading states while grading is in progress (grading takes 5-10 seconds)
PDF parser may produce messy text for questions with mathematical notation, diagrams, or tables — not yet tested end to end
Mark scheme parsing accuracy for complex multi-part questions not verified
No user authentication — app is currently open with no accounts
Grading history screen not built
Only 1 paper in the database, no ability to browse multiple papers yet

What to build next

Wire all Expo frontend screens to the live FastAPI backend
End-to-end test: photograph a real handwritten answer on iPhone, receive real grading result
Fix any PDF parsing issues discovered during real testing
Add loading states and error handling to frontend
Add grading history screen so students can review past attempts
Expand database with more past papers (2019–2023 May/June and Oct/Nov sessions)
Add support for IGCSE Mathematics Paper 4 (Extended, long answer)
Add remaining IGCSE subjects: Physics 0625, Chemistry 0620, Biology 0610
Add user authentication (Expo + backend JWT or Supabase Auth)
Migrate database from SQLite to PostgreSQL for production
Deploy backend to a cloud server (Railway or Render) so the app works without a local server
Add IBDP subjects: Maths AA, Maths AI, Physics, Chemistry, Biology with IB-specific mark scheme format
Custom question feature: student uploads their own mark scheme for questions not in the database
Analytics dashboard showing student performance trends per topic

Key decisions already made

2 API calls per grading, not 4: Vision extraction and grading are combined into one API call to minimize cost. Feedback is a second cheap text-only call. This keeps cost under $0.05 per question.
Hard cost cap at $0.20 per question: Enforced in pipeline.py with token cost calculation logged to terminal on every grading call.
max_tokens=800 for grading call, max_tokens=300 for feedback call: Strictly enforced to prevent runaway costs.
SQLite for MVP: Zero setup, runs locally, sufficient for prototype and hackathon demo. Will migrate to PostgreSQL before production.
Base64 image transfer: Images are base64 encoded on the mobile client and sent in the POST body. No S3 or file storage needed for prototype.
Expo Go compatibility: App must run on Expo Go, no custom native modules allowed in MVP.
One paper to start: IGCSE 0580/22/M/J/23 Extended Paper 2 is the single seeded paper that proves the pipeline works before scaling.
Mark schemes live in the database: Students never upload mark schemes. All mark schemes are pre-seeded by the developer from official Cambridge PDFs. Custom mark scheme upload is a future feature only.
Subject scope for MVP: IGCSE Mathematics 0580 Extended only, Papers 2 and 4.
No auth in prototype: Authentication is explicitly deferred until after the core grading pipeline is proven working.

Important notes for the AI

The grading accuracy is the most critical part of the entire app. The mark scheme comparison logic must follow Cambridge mark scheme conventions exactly: M marks are for method, A marks are for accuracy and depend on correct method, B marks are independent. Never award an A mark if the corresponding M mark was not earned.
Cambridge mark schemes use specific notation: M1 = method mark 1 mark, A1 = accuracy mark 1 mark, B1 = independent mark 1 mark, ft = follow through, cao = correct answer only, oe = or equivalent. The grading agent must understand all of these.
Mathematical notation in images is difficult to extract — the vision agent must handle fractions, square roots, indices, and algebra written by hand.
Target users are students aged 14–17, not teachers. Feedback must be encouraging, clear, and jargon-free.
Always write clean modular code. Never delete existing working functionality when adding new features.
The backend must always be running locally for Expo Go to connect to it during development. The iPhone and the Windows PC must be on the same WiFi network.
When expanding to more subjects, each subject has its own mark scheme format. IGCSE and IB mark schemes are structured differently and the grading agent prompts will need subject-specific versions.
For the hackathon demo, the single paper pipeline working end to end on a real iPhone is the proof of concept. Everything else is secondary.
