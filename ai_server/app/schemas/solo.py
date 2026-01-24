from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

# --- Request Schemas ---


class SoloSubmissionRequest(BaseModel):
    """
    SOLO-001: 심층 분석 요청 Body 스키마
    """

    user_text: str = Field(
        ...,
        alias="userText",
        min_length=1,
        description="Step 1에서 변환된 사용자 발화 텍스트",
    )
    criteria: Dict[str, Any] = Field(..., description="정답지 및 모델 가이드 (JSON)")
    history: List[Dict[str, Any]] = Field(..., description="이전 피드백 기록 리스트")

    class Config:
        populate_by_name = True


# --- Response Data Schemas (Inside 'data' field) ---


class SoloSubmissionData(BaseModel):
    """
    SOLO-001: 접수 성공 시 data 필드
    """

    task_id: str = Field(..., alias="taskId")
    status: str = Field(..., description="PENDING")

    class Config:
        populate_by_name = True


class FeedbackDetail(BaseModel):
    """
    SOLO-002: 피드백 상세 내용
    """

    summarize: str
    keyword: List[str]
    facts: str
    understanding: str
    personalized: str

    # 추가적인 필드가 들어올 수 있으므로 유연하게 처리하려면 extra='allow'를 쓸 수 있으나,
    # 명세서에 있는 필드는 명시하는 것이 좋음.


class SoloResultDetail(BaseModel):
    """
    SOLO-002: 분석 결과 상세 (점수 및 피드백)
    """

    score: int
    level: str
    feedback: FeedbackDetail


class SoloResultData(BaseModel):
    """
    SOLO-002: 조회 결과 data 필드
    """

    task_id: str = Field(..., alias="taskId")
    status: str = Field(..., description="PROCESSING | COMPLETED | FAILED")
    result: Optional[SoloResultDetail] = None

    class Config:
        populate_by_name = True


# --- Standard Response Envelopes ---


class SoloSubmissionResponse(BaseModel):
    """
    SOLO-001: 접수 응답 (202 Accepted)
    """

    success: bool
    data: Optional[SoloSubmissionData] = None
    error: Optional[Any] = None


class SoloResultResponse(BaseModel):
    """
    SOLO-002: 조회 응답 (200 OK)
    """

    success: bool
    data: Optional[SoloResultData] = None
    error: Optional[Any] = None
