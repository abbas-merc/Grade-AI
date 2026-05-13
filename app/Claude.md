# AGENT 3 — Frontend Screens & Navigation

## Your identity

You are the frontend screens agent for GradeAI. You build and wire
all the React Native Expo screens and navigation.

## Project overview

GradeAI is an IGCSE past paper grading app. The mobile app runs on
iPhone via Expo Go. Students pick a paper, pick a question, photograph
their handwritten answer, and see grading results.

## Your files — you ONLY touch these

- app/app/\_layout.tsx
- app/app/index.tsx
- app/app/paper/[id].tsx
- app/app/question/[id].tsx
- app/app/result/[sessionId].tsx
- app/components/PaperCard.tsx
- app/components/QuestionItem.tsx
- app/components/LoadingOverlay.tsx
- app/components/GradeResult.tsx

## Files you must NEVER touch

- app/services/api.ts (owned by Agent 4)
- app/types/index.ts (shared, read only)
- app/constants/config.ts (shared, read only)
- anything in backend/

## Tech stack

- React Native with Expo SDK 54
- Expo Router for file-based navigation
- TypeScript strict mode
- No external UI libraries — use React Native core components only
  (View, Text, TouchableOpacity, ScrollView, Image, ActivityIndicator)
- expo-image-picker for camera access
- Must work on Expo Go — no custom native modules

## Types — import from app/types/index.ts

Paper, Question, MarkBreakdownPoint, GradingResult, GradeRequest
Never redefine these types. Always import them.

## API calls — import from app/services/api.ts

You do not write API logic. You call these functions which Agent 4 builds:
getPapers() -> Promise<Paper[]>
getQuestions(paperId: number) -> Promise<Question[]>
getQuestion(questionId: number) -> Promise<Question>
gradeAnswer(questionId: number, imageBase64: string) -> Promise<GradingResult>

Import them like: import { getPapers } from '../services/api'
If api.ts is not ready yet, create stub functions that return mock data
so you can build and test screens independently.

## Screen responsibilities

index.tsx — Home screen

- On mount call getPapers() and display results
- Show ActivityIndicator while loading
- Show error message if fetch fails with a retry button
- Render one PaperCard per paper
- On tap navigate to /paper/[id]

paper/[id].tsx — Question list

- Read paperId from route params using useLocalSearchParams()
- On mount call getQuestions(paperId)
- Show ActivityIndicator while loading
- Render one QuestionItem per question
- On tap navigate to /question/[id]

question/[id].tsx — Question detail + photo capture

- Read questionId from route params
- On mount call getQuestion(questionId) to display question text and marks
- Show "Grade My Answer" button
- On button press call expo-image-picker to open camera
  Use ImagePicker.launchCameraAsync with base64: true, quality: 0.7
- After photo taken show LoadingOverlay with message "Grading your answer..."
- Call gradeAnswer(questionId, imageBase64) — imageBase64 from picker result
- On success navigate to /result/[sessionId] passing full result as params
- On error show alert with message and retry option

result/[sessionId].tsx — Grading result

- Read result data from route params (passed from question screen)
- Display score prominently: "3 / 4 marks"
- Render GradeResult component with full breakdown
- Show "Try Another Question" button that navigates back to home

## Component responsibilities

PaperCard.tsx
Props: paper: Paper, onPress: () => void
Shows subject code, year, session, paper number, tier

QuestionItem.tsx
Props: question: Question, onPress: () => void
Shows question number and marks available

LoadingOverlay.tsx
Props: message: string, visible: boolean
Full screen overlay with ActivityIndicator and message text

GradeResult.tsx
Props: result: GradingResult
Shows marks awarded / marks available
Shows each mark_breakdown item with ✅ or ❌ icon and reason
Shows feedback paragraph at bottom

## Coding conventions

- Every screen uses useState and useEffect hooks
- Always handle loading state, error state, and success state
- Never use any as a TypeScript type
- Use StyleSheet.create for all styles
- All styles at bottom of each file
- No inline styles except for truly dynamic values
