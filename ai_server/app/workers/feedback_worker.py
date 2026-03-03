"""
Feedback Worker Module.

Consumes PvP feedback requests from the pvp.feedback.request queue,
delegates the comparison analysis to PvpFeedbackService (Gemini API),
and publishes the result to the pvp.feedback.response queue.

The worker focuses solely on RabbitMQ communication;
all business logic is fully delegated to pvp_feedback_service.py.

[Error Handling Strategy]
On failure, this worker does NOT publish a FAIL response itself.
Instead, it re-raises the exception to let rabbitmq_service.py handle
the 3-retry logic and DLQ routing. The FAIL response is only published
by rabbitmq_service.py on the 3rd (final) failure attempt.

Note: pvp_feedback_service.py has its own internal tenacity-based
retry (3 attempts with exponential backoff) for Gemini API failures.
This operates independently of the queue-level retry mechanism.
"""

import logging

from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.pvp_feedback_service import pvp_feedback_service
from app.schemas.pvp_schema import FeedbackRequest, FeedbackResponse, PvpUserFeedback

logger = logging.getLogger(__name__)


async def handle_feedback_message(body: dict, message: AbstractIncomingMessage) -> None:
    """
    Callback function to process a feedback request message.

    1. Parse the message body into a FeedbackRequest schema
    2. Delegate to PvpFeedbackService (validation + backoff + Gemini call)
    3. Publish a SUCCESS FeedbackResponse to the result queue

    On failure, the exception is re-raised to trigger the RabbitMQ
    retry mechanism (up to 3 attempts with 5s delay between each).

    Args:
        body: Parsed JSON message body
        message: Raw RabbitMQ message (for Ack/Nack)
    """
    # 1. Validate payload with Pydantic
    request = FeedbackRequest(**body)
    logger.info(
        f"[Feedback Worker] Processing room={request.room_id}, "
        f"users={[u.user_id for u in request.users]}"
    )

    # 2. Delegate to business logic (Validation + Backoff + Gemini call)
    users_data = [u.model_dump() for u in request.users]
    feedback_result = await pvp_feedback_service.generate_pvp_feedback(
        criteria=request.criteria.model_dump(),
        users=users_data,
    )

    # 3. Build and publish SUCCESS response
    #    feedback_result is now a list of dicts (one per user)
    response = FeedbackResponse(
        room_id=request.room_id,
        status="SUCCESS",
        feedbacks=[PvpUserFeedback(**fb) for fb in feedback_result],
    )

    await rabbitmq_service.publish(
        settings.FEEDBACK_RESULT_QUEUE, response.model_dump()
    )

    logger.info(f"[Feedback Worker] Completed room={request.room_id}")

    # NOTE: If any exception occurs above, it will propagate to
    # rabbitmq_service.py's on_message handler, which will:
    #   - Retry up to 3 times (via reject → retry queue → main queue)
    #   - On 3rd failure: publish FAIL response + archive to DLQ


async def start_feedback_consumer() -> None:
    """
    Start consuming from the feedback request queue.
    Called from main.py's lifespan startup handler.
    """
    logger.info("[Feedback Worker] Starting consumer...")
    await rabbitmq_service.consume(
        settings.FEEDBACK_REQUEST_QUEUE, handle_feedback_message
    )
