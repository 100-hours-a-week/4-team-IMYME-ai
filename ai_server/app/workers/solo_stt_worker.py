"""
Solo STT Worker Module.

Consumes audio file URLs from the solo.stt.request queue,
validates the URL format and file extension,
calls the RunPod STT server for speech-to-text conversion,
and publishes the result to the solo.stt.response queue.

[Error Handling Strategy]
On failure, this worker does NOT publish a FAIL response itself.
Instead, it re-raises the exception to let rabbitmq_service.py handle
the 3-retry logic and DLQ routing. The FAIL response is only published
by rabbitmq_service.py on the 3rd (final) failure attempt.
"""

import re
import logging

from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.runpod_client import runpod_client
from app.schemas.solo_mq_schema import SoloSTTRequest, SoloSTTResponse

logger = logging.getLogger(__name__)

# Supported audio file extensions
# 지원 오디오 포맷 목록
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

# URL validation regex
URL_PATTERN = re.compile(
    r"^(?:http|ftp)s?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"
    r"localhost|"
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(?::\d+)?"
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


async def handle_solo_stt_message(body: dict, message: AbstractIncomingMessage) -> None:
    """
    Callback function to process a Solo STT request message.

    1. Parse and validate the message body (URL format + extension)
    2. Call the RunPod STT server to extract text
    3. Publish a SUCCESS SoloSTTResponse to the result queue

    On failure, the exception is re-raised to trigger the RabbitMQ
    retry mechanism (up to 3 attempts with 5s delay between each).

    Args:
        body: Parsed JSON message body
        message: Raw RabbitMQ message (for Ack/Nack)
    """
    # 1. Validate payload with Pydantic
    request = SoloSTTRequest(**body)
    logger.info(
        f"[Solo STT Worker] Processing room={request.room_id}, user={request.user_id}"
    )

    # 2. Validate URL format
    if not URL_PATTERN.match(request.audio_url):
        raise ValueError(f"유효한 URL인지 확인하세요. (input: {request.audio_url})")

    # 3. Validate file extension
    clean_url = request.audio_url.split("?")[0].lower()
    if not any(clean_url.endswith(ext) for ext in SUPPORTED_FORMATS):
        detected_ext = clean_url.split(".")[-1] if "." in clean_url else "unknown"
        raise ValueError(f"지원하지 않는 오디오 포맷입니다. ({detected_ext})")

    # 4. Call RunPod STT (natively async)
    stt_result = await runpod_client.transcribe(
        audio_url=request.audio_url,
        language="ko",
    )

    # 5. Build and publish SUCCESS response
    response = SoloSTTResponse(
        room_id=request.room_id,
        user_id=request.user_id,
        status="SUCCESS",
        stt_text=stt_result.get("text", ""),
    )

    await rabbitmq_service.publish(
        settings.SOLO_STT_RESULT_QUEUE, response.model_dump()
    )

    logger.info(
        f"[Solo STT Worker] Completed room={request.room_id}, user={request.user_id}"
    )


async def start_solo_stt_consumer() -> None:
    """
    Start consuming from the Solo STT request queue.
    Called from main.py's lifespan startup handler.
    """
    logger.info("[Solo STT Worker] Starting consumer...")
    await rabbitmq_service.consume(
        settings.SOLO_STT_REQUEST_QUEUE, handle_solo_stt_message
    )
