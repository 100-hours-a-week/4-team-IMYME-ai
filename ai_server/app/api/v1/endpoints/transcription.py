from fastapi import APIRouter, HTTPException
from app.schemas.transcription import TranscriptionRequest, TranscriptionResponse
# Use RunPod Client
from app.services.runpod_client import runpod_client

router = APIRouter()

# POST endpoint for transcribing audio
# 오디오 전사를 위한 POST 엔드포인트
@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(request: TranscriptionRequest):
    """
    Transcribe audio from a given URL using RunPod Serverless Whisper.
    RunPod Serverless Whisper를 사용하여 주어진 URL의 오디오를 전사합니다.
    """
    try:
        # Call the RunPod client
        # RunPod 클라이언트 호출
        result = runpod_client.transcribe_sync(
            audio_url=str(request.audio_url),
            language=request.language
        )
        return result
    except Exception as e:
        # Handle unexpected errors
        # 예기치 않은 오류 처리
        raise HTTPException(status_code=500, detail=str(e))
