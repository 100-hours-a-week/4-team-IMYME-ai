"""
Solo Mode MQ Message Payload Schemas.
Solo 모드 RabbitMQ 메시지 페이로드 스키마 정의.

solo_mq_schema.md 문서의 큐 규격에 맞춰 Request/Response 모델을 정의합니다.
PvP 모드(pvp_schema.py)와 동일한 Flat 구조를 사용합니다.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict


# =============================================================
# STT Worker Schemas (solo.stt.request / solo.stt.response)
# Solo STT 워커 메시지 스키마
# =============================================================


class SoloSTTRequest(BaseModel):
    """
    Solo STT Request Payload: 메인 서버 → AI 서버
    S3 음성 파일 URL을 받아 텍스트로 변환을 요청합니다.
    """

    room_id: int = Field(..., description="방 ID (Pass-through)")
    user_id: int = Field(..., description="사용자 ID (Pass-through)")
    audio_url: str = Field(..., description="S3 오디오 파일 URL")
    timestamp: int = Field(..., description="요청 시간 (Unix timestamp)")


class SoloSTTResponse(BaseModel):
    """
    Solo STT Response Payload: AI 서버 → 메인 서버
    STT 변환 결과를 반환합니다.
    """

    room_id: int = Field(..., description="방 ID (Pass-through)")
    user_id: int = Field(..., description="사용자 ID (Pass-through)")
    status: str = Field(..., description="처리 상태 (SUCCESS / FAIL)")
    stt_text: Optional[str] = Field(None, description="변환된 텍스트")
    error: Optional[str] = Field(None, description="실패 시 에러 메시지")


# =============================================================
# Feedback Worker Schemas (solo.feedback.request / solo.feedback.response)
# Solo 피드백 워커 메시지 스키마
# =============================================================


class SoloFeedbackRequest(BaseModel):
    """
    Solo Feedback Request Payload: 메인 서버 → AI 서버
    STT 텍스트와 채점 기준, 피드백 이력으로 심층 분석을 요청합니다.
    """

    room_id: int = Field(..., description="방 ID (Pass-through)")
    user_id: int = Field(..., description="사용자 ID (Pass-through)")
    user_text: str = Field(..., description="사용자의 STT 변환 텍스트")
    criteria: Dict[str, Any] = Field(
        ..., description="채점 기준 (keyword, model_answer)"
    )
    history: List[Dict[str, Any]] = Field(
        default_factory=list, description="이전 피드백 기록 리스트"
    )
    timestamp: int = Field(..., description="요청 시간 (Unix timestamp)")


class SoloFeedbackDetail(BaseModel):
    """
    Solo 피드백 분석 상세 결과.
    """

    summarize: str
    keyword: List[Any]
    facts: str
    understanding: str
    personalized: str


class SoloFeedbackResult(BaseModel):
    """
    Solo 피드백 분석 결과 (점수 + 피드백 상세).
    """

    overall_score: int = Field(..., description="종합 점수 (0-100)")
    level: int = Field(..., ge=1, le=5, description="레벨 (1-5)")
    feedback_detail: SoloFeedbackDetail


class SoloFeedbackResponse(BaseModel):
    """
    Solo Feedback Response Payload: AI 서버 → 메인 서버
    심층 분석 피드백 결과를 반환합니다.
    """

    room_id: int = Field(..., description="방 ID (Pass-through)")
    user_id: int = Field(..., description="사용자 ID (Pass-through)")
    status: str = Field(..., description="처리 상태 (SUCCESS / FAIL)")
    feedback: Optional[SoloFeedbackResult] = Field(
        None, description="분석 결과 (성공 시)"
    )
    error: Optional[str] = Field(None, description="실패 시 에러 메시지")
