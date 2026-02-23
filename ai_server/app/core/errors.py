"""
AI Server Error Code Definitions

This module centralizes all error codes and custom exceptions for the AI server.
All endpoints and services should use these definitions for consistent error handling.
"""

from enum import Enum
from typing import Optional, Any


class ErrorCode(str, Enum):
    """
    Enumeration of all error codes used in the AI Server.
    Each code maps to a specific error scenario.

    Naming Convention: [DOMAIN]_[ACTION]_[ISSUE] or [GENERAL_ISSUE]
    """

    # ============================================================
    # Transcription API Errors (400-level client, 500-level server)
    # ============================================================
    INVALID_URL = "INVALID_URL"
    """URL 형식이 잘못되었거나 접근 불가능한 URL"""

    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    """지원하지 않는 오디오 파일 형식 (.mp3, .wav 등만 지원)"""

    STT_FAILURE = "STT_FAILURE"
    """RunPod STT 서비스 호출 실패 (Timeout, 서버 오류 등)"""

    DOWNLOAD_FAILURE = "DOWNLOAD_FAILURE"
    """오디오 파일 다운로드 실패 (403, 404, 네트워크 오류 등)"""

    # ============================================================
    # Solo / Task API Errors
    # ============================================================
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    """요청된 작업(Task)을 찾을 수 없음 (만료 또는 미존재)"""

    MISSING_CONTEXT = "MISSING_CONTEXT"
    """필수 파라미터(userText, criteria 등) 누락"""

    INVALID_JSON = "INVALID_JSON"
    """JSON 형식이 올바르지 않음"""

    # ============================================================
    # Knowledge API Errors
    # ============================================================
    EMPTY_BATCH_DATA = "EMPTY_BATCH_DATA"
    """배치 처리 요청에 데이터가 비어있음"""

    TEXT_TOO_LONG = "TEXT_TOO_LONG"
    """입력 텍스트가 허용 길이를 초과함"""

    INVALID_LLM_RESPONSE = "INVALID_LLM_RESPONSE"
    """LLM 응답을 파싱할 수 없음 (예상치 못한 형식)"""

    # ============================================================
    # General / System Errors
    # ============================================================
    VALIDATION_ERROR = "VALIDATION_ERROR"
    """요청 데이터 유효성 검사 실패 (Pydantic 등)"""

    AUTH_ERROR = "AUTH_ERROR"
    """인증 실패 (x-internal-secret 헤더 오류)"""

    INTERNAL_ERROR = "INTERNAL_ERROR"
    """서버 내부 오류 (예상치 못한 예외)"""

    # ============================================================
    # External Service / Infrastructure Errors
    # ============================================================
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    """LLM (Gemini 등) API 호출 실패 (Timeout, 5xx 등)"""

    EMBEDDING_FAILURE = "EMBEDDING_FAILURE"
    """텍스트 벡터 변환(Embedding) 실패"""

    VECTOR_DIM_MISMATCH = "VECTOR_DIM_MISMATCH"
    """벡터 차원 불일치 (DB 설정 vs 모델 출력)"""

    STT_TIMEOUT = "STT_TIMEOUT"
    """STT 작업 타임아웃 (Polling 제한 시간 초과)"""

    GPU_FAIL = "GPU_FAIL"
    """GPU 워밍업 또는 상태 조회 실패"""


class AppException(Exception):
    """
    Base custom exception for the AI Server.
    All business logic exceptions should inherit from this class.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: Optional[Any] = None,
        status_code: int = 500,
    ):
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(self.message)


# Convenience exception subclasses for common scenarios
class ValidationException(AppException):
    """Raised for request validation errors."""

    def __init__(self, message: str, detail: Optional[Any] = None):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            detail=detail,
            status_code=400,
        )


class AuthException(AppException):
    """Raised for authentication/authorization errors."""

    def __init__(self, message: str = "인증에 실패했습니다."):
        super().__init__(
            code=ErrorCode.AUTH_ERROR,
            message=message,
            status_code=403,
        )


class NotFoundException(AppException):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str = "요청한 리소스를 찾을 수 없습니다."):
        super().__init__(
            code=ErrorCode.TASK_NOT_FOUND,
            message=message,
            status_code=404,
        )
