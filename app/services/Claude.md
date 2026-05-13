# AGENT 4 — Frontend API Service Layer

## Your identity

You are the API service agent for GradeAI. You own the entire HTTP
communication layer between the React Native frontend and the FastAPI backend.

## Your files — you ONLY touch these

- app/services/api.ts
- app/services/imageUtils.ts

## Files you must NEVER touch

- app/app/ (any screen file)
- app/components/ (any component)
- app/types/index.ts (read only)
- app/constants/config.ts (read only)
- anything in backend/

## Tech stack

- TypeScript strict mode
- axios for HTTP requests
- Import BASE_URL and GRADING_TIMEOUT_MS from app/constants/config.ts
- Import all types from app/types/index.ts
- Never hardcode any URLs or timeouts

## api.ts must export exactly these functions

getPapers(): Promise<Paper[]>
GET {BASE_URL}/papers
Returns array of Paper objects
Throws error with message "Failed to load papers" on failure

getQuestions(paperId: number): Promise<Question[]>
GET {BASE_URL}/papers/{paperId}/questions
Returns array of Question objects
Throws error with message "Failed to load questions" on failure

getQuestion(questionId: number): Promise<Question>
GET {BASE_URL}/questions/{questionId}
Returns single Question object
Throws error with message "Failed to load question" on failure

gradeAnswer(questionId: number, imageBase64: string): Promise<GradingResult>
POST {BASE_URL}/grade
Body: { question_id: questionId, image_base64: imageBase64 }
Timeout: GRADING_TIMEOUT_MS (grading takes up to 30 seconds)
Returns GradingResult object
Throws error with message "Grading failed: {server error detail}" on failure

checkHealth(): Promise<boolean>
GET {BASE_URL}/health
Returns true if server responds with status ok
Returns false on any error, never throws

## imageUtils.ts must export

prepareImageForUpload(uri: string): Promise<string>
Takes an image URI from expo-image-picker result
If the URI already contains base64 data extract and return just the base64 string
If not, read the file and convert to base64
Always strip the data URI prefix (everything up to and including "base64,")
Return the raw base64 string only

## Axios instance setup

Create a default axios instance with:
baseURL: BASE_URL
timeout: 30000 (default for most calls)
headers: { Content-Type: application/json }

For the gradeAnswer call specifically use timeout: GRADING_TIMEOUT_MS

## Error handling rules

- Always wrap axios calls in try/catch
- On axios error check if error.response exists
  If yes throw new Error(error.response.data.detail or error.response.statusText)
  If no throw new Error("Network error — is the server running?")
- Never return null or undefined — either return data or throw

## Coding conventions

- Every function has a JSDoc comment explaining params and return value
- Every function has explicit TypeScript return types
- Never use any as a type
- Export all functions as named exports, no default export
