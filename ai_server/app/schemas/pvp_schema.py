"""
PvP Mode Message Payload Schemas.
PvP 모드 RabbitMQ 메시지 페이로드 스키마 정의.

pvp_spec.md 문서의 큐 규격에 맞춰 Request/Response 모델을 정의합니다.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict


# =============================================================
# STT Worker Schemas (pvp.stt.request / pvp.stt.response)
# STT 워커 메시지 스키마
# =============================================================


class STTRequest(BaseModel):
    """
    STT Request Payload: 메인 서버 → AI 서버
    S3 음성 파일 URL을 받아 텍스트로 변환을 요청합니다.
    """

    match_id: str = Field(..., description="매치 ID (Pass-through)")
    user_id: str = Field(..., description="사용자 ID (Pass-through)")
    file_url: str = Field(..., description="S3 오디오 파일 URL")
    timestamp: int = Field(..., description="요청 시간 (Unix timestamp)")


class STTResponse(BaseModel):
    """
    STT Response Payload: AI 서버 → 메인 서버
    STT 변환 결과를 반환합니다.
    """

    match_id: str = Field(..., description="매치 ID (Pass-through)")
    user_id: str = Field(..., description="사용자 ID (Pass-through)")
    status: str = Field(..., description="처리 상태 (SUCCESS / FAIL)")
    stt_text: Optional[str] = Field(None, description="변환된 텍스트")
    error: Optional[str] = Field(None, description="실패 시 에러 메시지")


# =============================================================
# Feedback Worker Schemas (pvp.feedback.request / pvp.feedback.response)
# 피드백 워커 메시지 스키마
# =============================================================


class PvpUserData(BaseModel):
    """
    PvP 대결에 참여하는 개별 사용자 데이터.
    """

    user_id: str = Field(..., description="사용자 ID")
    user_text: str = Field(..., description="사용자의 STT 변환 텍스트")


class FeedbackCriteria(BaseModel):
    """
    피드백 생성을 위한 채점 기준 정보.
    """

    keyword: str = Field(..., description="핵심 키워드")
    modelAnswer: str = Field(..., description="모범 답안")


class FeedbackRequest(BaseModel):
    """
    Feedback Request Payload: 메인 서버 → AI 서버
    2명의 사용자 STT 결과를 취합하여 비교 피드백을 요청합니다.
    """

    match_id: str = Field(..., description="매치 ID")
    criteria: FeedbackCriteria = Field(..., description="채점 기준")
    users: List[PvpUserData] = Field(
        ..., min_length=2, max_length=2, description="2명의 사용자 데이터"
    )
    timestamp: int = Field(..., description="요청 시간 (Unix timestamp)")


class PvpUserFeedback(BaseModel):
    """
    개별 사용자에 대한 PvP 비교 피드백 상세.
    Solo 모드와 동일한 JSON 구조 + score 필드.
    """

    user_id: str = Field(..., description="사용자 ID")
    score: int = Field(..., ge=0, le=100, description="종합 점수 (0-100)")
    summarize: str = Field(..., description="이해도 요약 (한 문장)")
    keyword: List[str] = Field(..., description="포함/누락 키워드 리스트")
    facts: str = Field(..., description="사실 관계 확인")
    understanding: str = Field(..., description="이해 깊이 평가")
    personalized: str = Field(..., description="PvP 전략 기반 비교 피드백")


class PvpFeedbackResult(BaseModel):
    """
    PvP 비교 피드백 전체 결과.
    각 사용자별 피드백과 공통 피드백을 포함합니다.
    """

    user_A: PvpUserFeedback = Field(..., description="사용자 A 피드백")
    user_B: PvpUserFeedback = Field(..., description="사용자 B 피드백")


class FeedbackResponse(BaseModel):
    """
    Feedback Response Payload: AI 서버 → 메인 서버
    PvP 비교 분석 피드백 결과를 반환합니다.
    """

    match_id: str = Field(..., description="매치 ID")
    status: str = Field(..., description="처리 상태 (SUCCESS / FAIL)")
    feedback: Optional[PvpFeedbackResult] = Field(
        None, description="비교 피드백 결과"
    )
    error: Optional[str] = Field(None, description="실패 시 에러 메시지")
