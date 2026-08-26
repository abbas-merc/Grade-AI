# Shared Pydantic schemas used by all backend agents
# DO NOT MODIFY without updating all agents

from pydantic import BaseModel, field_validator
from typing import List, Optional

# Upper bound on an inbound base64 image string (~11 MB decoded). A single
# handwritten page compresses to well under 1 MB; this only exists to stop a
# malicious client exhausting server memory with a giant payload before any
# processing happens. Enforced by Pydantic, so an oversized body is a clean 422.
_MAX_IMAGE_B64_CHARS = 15_000_000


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

    @field_validator("image_base64")
    @classmethod
    def _cap_image_size(cls, v: str) -> str:
        if len(v) > _MAX_IMAGE_B64_CHARS:
            raise ValueError("Image is too large. Please retake the photo.")
        return v


class QuestionResponse(BaseModel):
    id: int
    question_number: str
    question_text: str
    marks_available: int
    # Host-agnostic snippet path ("/question_snippets/<id>.png") for papers whose
    # questions are image snippets; empty for legacy text-only questions.
    question_image_url: str = ""


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
    # True when the transcript contains an [illegible] token — the model could
    # not read part of this answer, so the teacher should check it manually.
    has_illegible: bool = False


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
    # True when the sum of the per-question maximum marks does not equal the
    # paper's stored total_marks — individual question totals may be wrong.
    marks_total_mismatch: bool = False
    # Firestore document ID of the saved marking (teachers/{uid}/markings/{id}).
    # Lets the client delete the exact history document later. Optional because
    # the result is fully valid even if the Firestore save failed.
    marking_id: Optional[str] = None


# --- Async paper-grading job schemas ---

class StartGradingResponse(BaseModel):
    job_id: str


class GradingStatusResponse(BaseModel):
    status: str  # "pending" | "running" | "done" | "error"
    result: Optional[PaperGradingResponse] = None
    error: Optional[str] = None
