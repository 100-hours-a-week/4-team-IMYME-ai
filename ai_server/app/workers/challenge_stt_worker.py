"""
Challenge STT Worker Module.

Consumes audio file URLs from the challenge.stt.request queue,
validates the format, calls the RunPod STT server,
and publishes the result to the challenge.stt.response queue.

This dedicated queue ensures that heavy Challenge Mode traffic
does not block or affect the real-time processing of Solo/PvP queues.
"""

import re
import logging
from pydantic import BaseModel
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.runpod_client import runpod_client

logger = logging.getLogger("imyme-challenge-stt-worker")

SUPPORTED_FORMATS = [
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

URL_PATTERN = re.compile(
    r"^(?:http|ftp)s?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"
    r"localhost|"
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(?::\d+)?"
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


class ChallengeSTTRequest(BaseModel):
    attemptId: int
    challengeId: int
    audioUrl: str


class ChallengeSTTResponse(BaseModel):
    attemptId: int
    challengeId: int
    status: str
    sttText: str | None = None


async def handle_challenge_stt_message(
    body: dict, message: AbstractIncomingMessage
) -> None:
    try:
        request = ChallengeSTTRequest(**body)
    except Exception as e:
        logger.error(f"Invalid STT request format: {e}")
        raise ValueError(f"Invalid request format: {e}")

    logger.info(
        f"🎤 [Challenge STT] Processing attempt={request.attemptId}, challenge={request.challengeId}"
    )

    if not URL_PATTERN.match(request.audioUrl):
        raise ValueError(f"Invalid URL: {request.audioUrl}")

    clean_url = request.audioUrl.split("?")[0].lower()
    if not any(clean_url.endswith(ext) for ext in SUPPORTED_FORMATS):
        ext = clean_url.split(".")[-1] if "." in clean_url else "unknown"
        raise ValueError(f"Unsupported audio format: {ext}")

    # Call RunPod STT
    stt_result = await runpod_client.transcribe(
        audio_url=request.audioUrl,
        language="ko",
    )

    response = ChallengeSTTResponse(
        attemptId=request.attemptId,
        challengeId=request.challengeId,
        status="SUCCESS",
        sttText=stt_result.get("text", ""),
    )

    await rabbitmq_service.publish(
        settings.CHALLENGE_STT_RESULT_QUEUE, response.model_dump()
    )

    logger.info(
        f"✅ [Challenge STT] Completed attempt={request.attemptId}. Published to {settings.CHALLENGE_STT_RESULT_QUEUE}"
    )


async def start_challenge_stt_consumer() -> None:
    logger.info(
        f"Starting Challenge STT Consumer on {settings.CHALLENGE_STT_REQUEST_QUEUE}..."
    )
    await rabbitmq_service.consume(
        settings.CHALLENGE_STT_REQUEST_QUEUE, handle_challenge_stt_message
    )
