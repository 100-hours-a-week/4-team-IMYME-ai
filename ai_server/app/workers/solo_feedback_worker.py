"""
Solo Feedback Worker Module.

Consumes feedback requests from the solo.feedback.request queue,
delegates the analysis to AnalysisService (Scoring + Feedback via Gemini),
and publishes the result to the solo.feedback.response queue.

The worker focuses solely on RabbitMQ communication;
all business logic is fully delegated to analysis_service.py
(scoring_service + feedback_service in parallel).

[Error Handling Strategy]
On failure, this worker does NOT publish a FAIL response itself.
Instead, it re-raises the exception to let rabbitmq_service.py handle
the 3-retry logic and DLQ routing. The FAIL response is only published
by rabbitmq_service.py on the 3rd (final) failure attempt.
"""

import asyncio
import time
import logging

from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.scoring_service import scoring_service
from app.services.feedback_service import feedback_service
from app.schemas.solo_mq_schema import (
    SoloFeedbackRequest,
    SoloFeedbackResponse,
    SoloFeedbackData,
)

logger = logging.getLogger(__name__)

# 솔로 모드 최소 텍스트 길이 기준 (analysis_service.py 와 동일)
MIN_TEXT_LENGTH = 5


async def handle_solo_feedback_message(
    body: dict, message: AbstractIncomingMessage
) -> None:
    """
    Callback function to process a Solo Feedback request message.

    1. Parse the message body into a SoloFeedbackRequest schema
    2. Validate input (criteria, text length)
    3. Run Scoring + Feedback in parallel (Gemini API)
    4. Publish a SUCCESS SoloFeedbackResponse to the result queue

    On failure, the exception is re-raised to trigger the RabbitMQ
    retry mechanism (up to 3 attempts with 5s delay between each).

    Args:
        body: Parsed JSON message body
        message: Raw RabbitMQ message (for Ack/Nack)
    """
    # 1. Validate payload with Pydantic
    request = SoloFeedbackRequest(**body)
    logger.info(
        f"[Solo Feedback Worker] Processing attempt={request.attempt_id}, user={request.user_id}"
    )

    # 2. Global Deadline Budget Check
    # expires_at이 존재하면 남은 시간을 확인하고, 부족하면 Gemini를 호출하지 않음
    gemini_timeout: float | None = None  # None이면 기존 동작(무제한 대기)
    if request.expires_at is not None:
        remaining_time = request.expires_at - time.time()

        if remaining_time <= 0:
            raise TimeoutError(
                f"[Global Deadline] Feedback 예산 만료. Gemini API를 호출하지 않습니다. "
                f"(remaining={remaining_time:.1f}s)"
            )

        gemini_timeout = remaining_time
        logger.info(
            f"[Solo Feedback Worker] Budget allocated: gemini_timeout={gemini_timeout:.1f}s"
        )

    # 3. Validate criteria
    if not request.criteria:
        raise ValueError("분석 기준(Criteria)이 누락되었습니다.")

    # 4. Handle short text (hardcoded response, not an error)
    if len(request.stt_text.strip()) < MIN_TEXT_LENGTH:
        logger.info(
            f"[Solo Feedback Worker] Text too short (<{MIN_TEXT_LENGTH} chars). "
            f"Returning hardcoded feedback for attempt={request.attempt_id}."
        )
        response = SoloFeedbackResponse(
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            user_id=request.user_id,
            status="SUCCESS",
            feedback=SoloFeedbackData(
                score=0,
                grade=1,
                summary="입력된 내용이 너무 짧거나 인식이 되지 않았습니다.",
                keywords=["음성 인식 실패", "짧은 답변"],
                facts="분석할 텍스트가 부족합니다.",
                understanding="사용자의 의도를 파악하기 어렵습니다.",
                personalized_feedback="조금 더 길게 말씀해주시거나, 다시 시도 부탁드립니다.",
            ),
        )
        await rabbitmq_service.publish(
            settings.SOLO_FEEDBACK_RESULT_QUEUE, response.model_dump()
        )
        logger.info(
            f"[Solo Feedback Worker] Published short-text response for attempt={request.attempt_id}"
        )
        return

    # 5. Run Scoring + Feedback in parallel (same as analysis_service logic)
    score_task = scoring_service.evaluate(request.stt_text, request.criteria)
    feedback_task = feedback_service.generate_feedback(
        request.stt_text, request.criteria, request.history
    )

    # Global Deadline이 설정되어 있으면 asyncio.wait_for로 하드 타임아웃 적용
    if gemini_timeout is not None:
        try:
            score_result, feedback_result = await asyncio.wait_for(
                asyncio.gather(score_task, feedback_task),
                timeout=gemini_timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"[Global Deadline] Gemini 응답이 예산({gemini_timeout:.1f}s) 내에 완료되지 않았습니다."
            )
    else:
        score_result, feedback_result = await asyncio.gather(score_task, feedback_task)

    # 5. Build and publish SUCCESS response
    response = SoloFeedbackResponse(
        request_id=request.request_id,
        attempt_id=request.attempt_id,
        user_id=request.user_id,
        status="SUCCESS",
        feedback=SoloFeedbackData(
            score=score_result["score"],
            grade=score_result["grade"],
            **feedback_result,
        ),
    )

    await rabbitmq_service.publish(
        settings.SOLO_FEEDBACK_RESULT_QUEUE, response.model_dump()
    )

    logger.info(
        f"[Solo Feedback Worker] Completed attempt={request.attempt_id}, user={request.user_id}"
    )


async def start_solo_feedback_consumer() -> None:
    """
    Start consuming from the Solo Feedback request queue.
    Called from main.py's lifespan startup handler.
    """
    logger.info("[Solo Feedback Worker] Starting consumer...")
    await rabbitmq_service.consume(
        settings.SOLO_FEEDBACK_REQUEST_QUEUE, handle_solo_feedback_message
    )
