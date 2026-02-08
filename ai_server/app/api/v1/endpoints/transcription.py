from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.schemas.transcription import TranscriptionRequest, TranscriptionResponse
from app.core.errors import ErrorCode
from app.schemas.common import create_error_response, create_success_response

# Use RunPod Client
from app.services.runpod_client import runpod_client
import re

router = APIRouter()


# POST endpoint for transcribing audio
# 오디오 전사를 위한 POST 엔드포인트
@router.post("/transcriptions", response_model=TranscriptionResponse)
async def transcribe_audio(request: TranscriptionRequest):
    """
    Transcribe audio from a given URL (audioUrl).
    Returns nested response: { "data": { "text": "..." } }
    """

    # 1. Validate URL Format (INVALID_URL - 400)
    # URL 형식 검증
    url_pattern = re.compile(
        r"^(?:http|ftp)s?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
        r"localhost|"  # localhost...
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    if not url_pattern.match(request.audio_url):
        return JSONResponse(
            status_code=400,
            content=create_error_response(
                code=ErrorCode.INVALID_URL,
                message="유효한 URL인지 확인하세요.",
                detail={"input": request.audio_url},
            ),
        )

    # 2. Validate File Extension (UNSUPPORTED_FORMAT - 400)
    # 파일 확장자 검증
    supported_formats = [
        ".mp3",
        ".wav",
        ".m4a",
        ".flac",
        ".ogg",
        ".aac",
        ".wma",
        ".webm",
        ".mp4",
    ]
    # Check if URL ends with supported extension (ignoring query params)
    clean_url = request.audio_url.split("?")[0].lower()
    detected_ext = clean_url.split(".")[-1] if "." in clean_url else "unknown"
    if not any(clean_url.endswith(ext) for ext in supported_formats):
        return JSONResponse(
            status_code=400,
            content=create_error_response(
                code=ErrorCode.UNSUPPORTED_FORMAT,
                message=f"지원하지 않는 오디오 포맷입니다. ({detected_ext})",
                detail={"detected": detected_ext, "supported": supported_formats},
            ),
        )

    try:
        # Call the RunPod client
        # RunPod 클라이언트 호출
        result = runpod_client.transcribe_sync(
            audio_url=str(request.audio_url),
            language="ko",  # Force Korean for backend
        )

        # Map flat result from RunPod to standard envelope structure
        # RunPod의 플랫한 결과를 표준 응답 구조(success, data, error)로 매핑
        return create_success_response(data={"text": result.get("text", "")})

    except Exception as e:
        # Handle unexpected errors with Custom Error Codes
        error_msg = str(e)
        error_code = ErrorCode.STT_FAILURE

        # Analyze error message to determine specific code
        # 에러 메시지 분석
        if (
            "download" in error_msg.lower()
            or "403" in error_msg
            or "404" in error_msg
        ):
            # Download failure (S3 permission, etc)
            error_code = ErrorCode.DOWNLOAD_FAILURE

        return JSONResponse(
            status_code=500,
            content=create_error_response(
                code=error_code,
                message="음성 전사 처리 중 오류가 발생했습니다.",
                detail={"raw_error": error_msg},
            ),
        )

