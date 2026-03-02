"""
STT Worker Module.

Consumes audio file URLs from the pvp.stt.request queue,
calls the RunPod STT server for speech-to-text conversion,
and publishes the result to the pvp.stt.response queue.

[Error Handling Strategy]
On failure, this worker does NOT publish a FAIL response itself.
Instead, it re-raises the exception to let rabbitmq_service.py handle
the 3-retry logic and DLQ routing. The FAIL response is only published
by rabbitmq_service.py on the 3rd (final) failure attempt.
"""

import logging
import asyncio

from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.runpod_client import runpod_client
from app.schemas.pvp_schema import STTRequest, STTResponse

logger = logging.getLogger(__name__)


async def handle_stt_message(body: dict, message: AbstractIncomingMessage) -> None:
    """
    Callback function to process an STT request message.

    1. Parse the message body into an STTRequest schema
    2. Call the RunPod STT server to extract text
    3. Publish a SUCCESS STTResponse to the result queue

    On failure, the exception is re-raised to trigger the RabbitMQ
    retry mechanism (up to 3 attempts with 5s delay between each).

    Args:
        body: Parsed JSON message body
        message: Raw RabbitMQ message (for Ack/Nack)
    """
    # 1. Validate payload with Pydantic
    request = STTRequest(**body)
    logger.info(
        f"[STT Worker] Processing room={request.room_id}, user={request.user_id}"
    )

    # 2. Call RunPod STT (now natively async, no thread pool needed)
    stt_result = await runpod_client.transcribe(
        audio_url=request.audio_url,
    )

    # 3. Build and publish SUCCESS response
    response = STTResponse(
        room_id=request.room_id,
        user_id=request.user_id,
        status="SUCCESS",
        stt_text=stt_result.get("text", ""),
    )

    await rabbitmq_service.publish(settings.STT_RESULT_QUEUE, response.model_dump())

    logger.info(
        f"[STT Worker] Completed room={request.room_id}, user={request.user_id}"
    )

    # NOTE: If any exception occurs above, it will propagate to
    # rabbitmq_service.py's on_message handler, which will:
    #   - Retry up to 3 times (via reject → retry queue → main queue)
    #   - On 3rd failure: publish FAIL response + archive to DLQ


async def start_stt_consumer() -> None:
    """
    Start consuming from the STT request queue.
    Called from main.py's lifespan startup handler.
    """
    logger.info("[STT Worker] Starting consumer...")
    await rabbitmq_service.consume(settings.STT_REQUEST_QUEUE, handle_stt_message)
