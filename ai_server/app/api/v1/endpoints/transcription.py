from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.schemas.transcription import TranscriptionRequest, TranscriptionResponse

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
            content={
                "success": False,
                "data": None,
                "error": "INVALID_URL: 유효한 URL인지 확인하세요.",
            },
        )

    # 2. Validate File Extension (UNSUPPORTED_FORMAT - 400)
    # 파일 확장자 검증
    supported_formats = [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"]
    # Check if URL ends with supported extension (ignoring query params)
    clean_url = request.audio_url.split("?")[0].lower()
    if not any(clean_url.endswith(ext) for ext in supported_formats):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "data": None,
                "error": f"UNSUPPORTED_FORMAT: 지원하지 않는 오디오 포맷 ({clean_url.split('.')[-1]})",
            },
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
        return {
            "success": True,
            "data": {"text": result.get("text", "")},
            "error": None,
        }
    except Exception as e:
        # Handle unexpected errors with Custom Error Codes
        error_msg = str(e)
        status_code = 500
        error_code = "STT_FAILURE"

        # Analyze error message to determine specific code
        # 에러 메시지 분석
        if "timeout" in error_msg.lower():
            # RunPod Timeout
            error_code = "STT_FAILURE"  # Still server error
        elif (
            "download" in error_msg.lower() or "403" in error_msg or "404" in error_msg
        ):
            # Download failure (S3 permission, etc) - Guessing from typical error strings
            error_code = "DOWNLOAD_FAILURE"

        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "data": None,
                "error": f"{error_code}: {error_msg}",
            },
        )
