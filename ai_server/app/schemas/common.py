"""
Common Response Schemas for the AI Server.

This module defines the standard response envelope used across all API endpoints.
All responses follow the pattern: { success: bool, data: T | null, error: ErrorDetail | null }
"""

from pydantic import BaseModel, Field
from typing import Optional, Any, Generic, TypeVar
from app.core.errors import ErrorCode


# Generic type for response data
T = TypeVar("T")


class ErrorDetail(BaseModel):
    """
    Standard error detail structure.
    All errors returned by the API will follow this format.
    """

    code: str = Field(..., description="에러 코드 (ErrorCode Enum 값)")
    message: str = Field(..., description="사용자에게 보여줄 안전한 에러 메시지")
    detail: Optional[Any] = Field(
        None, description="추가 디버깅 정보 (선택, 개발 환경에서만 포함)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "code": "VALIDATION_ERROR",
                "message": "입력값이 올바르지 않습니다.",
                "detail": {"field": "email", "reason": "Invalid format"},
            }
        }


class BaseResponse(BaseModel, Generic[T]):
    """
    Standard API response envelope.
    All endpoints should return responses wrapped in this structure.
    """

    success: bool = Field(..., description="요청 성공 여부")
    data: Optional[T] = Field(None, description="성공 시 응답 데이터")
    error: Optional[ErrorDetail] = Field(None, description="실패 시 에러 상세")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {"text": "Hello World"},
                "error": None,
            }
        }


def create_error_response(
    code: ErrorCode,
    message: str,
    detail: Optional[Any] = None,
) -> dict:
    """
    Helper function to create a standardized error response dict.
    Use this when returning JSONResponse directly from endpoints.

    Args:
        code: ErrorCode enum value
        message: User-facing error message
        detail: Optional debugging information

    Returns:
        Dictionary matching the ErrorDetail + BaseResponse structure
    """
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code.value if isinstance(code, ErrorCode) else code,
            "message": message,
            "detail": detail,
        },
    }


def create_success_response(data: Any) -> dict:
    """
    Helper function to create a standardized success response dict.

    Args:
        data: Response data to include

    Returns:
        Dictionary matching the BaseResponse structure
    """
    return {
        "success": True,
        "data": data,
        "error": None,
    }
