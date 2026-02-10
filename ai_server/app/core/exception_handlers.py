"""
Global Exception Handlers for the AI Server.

This module provides centralized exception handling to ensure all errors
are returned in a consistent JSON format matching the BaseResponse schema.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import ErrorCode, AppException
from app.schemas.common import create_error_response
import logging

logger = logging.getLogger(__name__)


def add_exception_handlers(app: FastAPI) -> None:
    """
    Register all global exception handlers to the FastAPI app.
    Call this function after creating the app instance.
    """

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """
        Handle custom AppException and its subclasses.
        These are business logic errors raised intentionally.
        """
        logger.warning(f"AppException: {exc.code} - {exc.message}")
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                code=exc.code,
                message=exc.message,
                detail=exc.detail,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """
        Handle Pydantic validation errors (422 Unprocessable Entity).
        Converts to standard error format with field-level details.
        """
        field_errors = []
        error_code = ErrorCode.VALIDATION_ERROR
        message = "입력값이 올바르지 않습니다."

        for error in exc.errors():
            # Check for JSON decode error
            if error["type"] == "json_invalid":
                error_code = ErrorCode.INVALID_JSON
                message = "JSON 형식이 올바르지 않습니다."

            # Check for missing field error
            if error["type"] == "missing":
                error_code = ErrorCode.MISSING_CONTEXT
                message = "필수 파라미터가 누락되었습니다."

            field_errors.append(
                {
                    "field": ".".join(str(loc) for loc in error["loc"]),
                    "reason": error["msg"],
                    "type": error["type"],
                }
            )

        logger.warning(f"Validation Error ({error_code}): {field_errors}")
        return JSONResponse(
            status_code=400,
            content=create_error_response(
                code=error_code,
                message=message,
                detail=field_errors,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """
        Handle generic HTTP exceptions (404, 403, etc.) from FastAPI/Starlette.
        Converts to standard error format.
        """
        # Map status codes to ErrorCode
        code_map = {
            403: ErrorCode.AUTH_ERROR,
            404: ErrorCode.TASK_NOT_FOUND,
            405: ErrorCode.VALIDATION_ERROR,
        }
        error_code = code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR)

        # Default messages per status
        message_map = {
            403: "접근이 거부되었습니다.",
            404: "요청한 리소스를 찾을 수 없습니다.",
            405: "허용되지 않는 HTTP 메소드입니다.",
        }
        message = message_map.get(exc.status_code, str(exc.detail))

        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                code=error_code,
                message=message,
            ),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """
        Catch-all handler for uncaught exceptions.
        Logs the full error but returns a safe message to the client.
        """
        logger.exception(f"Unhandled Exception: {exc}")
        return JSONResponse(
            status_code=500,
            content=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="서버 내부 오류가 발생했습니다.",
                # In production, do NOT include exc details
                # detail=str(exc),  # Enable only for debugging
            ),
        )
