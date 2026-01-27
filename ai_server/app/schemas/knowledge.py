from pydantic import BaseModel, Field
from typing import List, Optional, Any
from enum import Enum


class KnowledgeAction(str, Enum):
    UPDATE = "UPDATE"
    IGNORE = "IGNORE"


# --- 7.1 Refine Candidates (Batch) ---

class RawFeedbackItem(BaseModel):
    id: str = Field(..., description="Main Server History ID")
    keyword: str
    rawFeedback: str

class KnowledgeCandidate(BaseModel):
    id: str
    keyword: str
    refinedText: str
    embedding: List[float]

class RefineCandidatesRequest(BaseModel):
    items: List[RawFeedbackItem]

class RefineCandidatesResponseData(BaseModel):
    processedCount: int
    candidates: List[KnowledgeCandidate]

class RefineCandidatesResponse(BaseModel):
    success: bool = True
    data: RefineCandidatesResponseData
    error: Optional[Any] = None

# --- 7.2 Evaluate Knowledge ---

class EvaluateCandidateInput(BaseModel):
    text: str
    sourceId: str

class EvaluateSimilarInput(BaseModel):
    id: str
    text: str
    similarity: float

class KnowledgeEvaluationRequest(BaseModel):
    candidate: EvaluateCandidateInput
    similars: List[EvaluateSimilarInput]

class KnowledgeEvaluationResult(BaseModel):
    decision: KnowledgeAction
    targetId: Optional[str] = None
    finalContent: Optional[str] = None
    finalVector: Optional[List[float]] = None
    reasoning: str

class KnowledgeEvaluationResponse(BaseModel):
    success: bool = True
    data: KnowledgeEvaluationResult
    error: Optional[Any] = None
