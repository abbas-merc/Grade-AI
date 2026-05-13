# Shared Pydantic schemas used by all backend agents
# DO NOT MODIFY without updating all agents

from pydantic import BaseModel
from typing import List, Optional


class MarkBreakdownPoint(BaseModel):
    point_number: int
    criterion: str
    awarded: bool
    reason: str


class GradingResponse(BaseModel):
    session_id: int
    question_id: int
    question_text: str
    marks_awarded: int
    marks_available: int
    mark_breakdown: List[MarkBreakdownPoint]
    feedback: str
    extracted_text: str
    cost_usd: float


class GradeRequest(BaseModel):
    question_id: int
    image_base64: str


class QuestionResponse(BaseModel):
    id: int
    question_number: str
    question_text: str
    marks_available: int


class PaperResponse(BaseModel):
    id: int
    subject_code: str
    year: int
    session: str
    paper_number: int
    tier: str
    total_marks: int


# --- Full-paper grading schemas ---

class PaperMarkBreakdownPoint(BaseModel):
    criterion: str
    awarded: bool
    reason: str


class QuestionResult(BaseModel):
    question_number: str
    question_text: str
    extracted_answer: str
    marks_awarded: int
    marks_available: int
    mark_breakdown: List[PaperMarkBreakdownPoint]
    feedback: str


class PaperGradeRequest(BaseModel):
    paper_id: int
    page_images: List[str]


class PaperGradingResponse(BaseModel):
    paper_id: int
    total_marks_awarded: int
    total_marks_available: int
    cost_usd: float
    results: List[QuestionResult]
    cost_cap_reached: bool = False


# --- Async paper-grading job schemas ---

class StartGradingResponse(BaseModel):
    job_id: str


class GradingStatusResponse(BaseModel):
    status: str  # "pending" | "running" | "done" | "error"
    result: Optional[PaperGradingResponse] = None
    error: Optional[str] = None
