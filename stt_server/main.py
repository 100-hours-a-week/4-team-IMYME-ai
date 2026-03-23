from fastapi import FastAPI
from pydantic import BaseModel
from contextlib import asynccontextmanager
from services.inference_service import InferenceService
import logging
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt-api")

# Initialize Service early (ModelService singleton loads model in __new__)
inference_service = InferenceService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for model initialization and cleanup.
    모델 초기화 및 정리를 위한 Lifespan 컨텍스트 매니저.
    """
    logger.info(
        "STT API Server started. Model already loaded via ModelService singleton."
    )
    yield
    logger.info("STT API Server shutting down.")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="RunPod STT Pod API",
    description="API for Speech-to-Text inference running as a persistent Pod",
    version="1.0.0",
    lifespan=lifespan,
)


class TranscriptionRequest(BaseModel):
    audio_url: str
    language: str | None = None
    warmup: bool | None = False


@app.get("/health")
async def health_check():
    """Health check endpoint for the container."""
    return {"status": "healthy"}


@app.post("/transcribe")
async def transcribe_audio(request: TranscriptionRequest):
    """
    Transcribe audio from a given URL.
    This replaces the handler.py logic from RunPod Serverless.
    """
    from fastapi import HTTPException

    if request.warmup:
        logger.info("Warmup signal received. Returning immediately.")
        return {"status": "success", "message": "Warmed up"}

    if not request.audio_url:
        raise HTTPException(status_code=400, detail="Missing 'audio_url' in request")

    try:
        logger.info(f"Processing transcription request for URL: {request.audio_url}")

        # Call the transcription service (synchronously blocking)
        result = inference_service.transcribe(request.audio_url, request.language)

        return result

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    # When run directly, start standard HTTP server on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")
