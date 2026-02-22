"""
Feedback Worker Module.
피드백 워커: RabbitMQ에서 2명의 STT 결과를 소비하여 비교 피드백을 반환합니다.

pvp.feedback.request 큐에서 메시지를 소비하고,
PvpFeedbackService를 통해 Gemini API로 비교 분석 피드백을 생성한 뒤,
pvp.feedback.response 큐로 결과를 발행합니다.

워커 자체는 RabbitMQ 통신에만 집중하며,
비즈니스 로직은 pvp_feedback_service.py에 완전히 위임합니다.
"""

import logging

from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.pvp_feedback_service import pvp_feedback_service
from app.schemas.pvp_schema import FeedbackRequest, FeedbackResponse, PvpFeedbackResult

logger = logging.getLogger(__name__)


async def handle_feedback_message(
    body: dict, message: AbstractIncomingMessage
) -> None:
    """
    피드백 요청 메시지를 처리하는 콜백 함수.

    1. 메시지를 FeedbackRequest 스키마로 파싱
    2. PvpFeedbackService에 비즈니스 로직 위임
    3. 성공/실패에 따라 FeedbackResponse를 결과 큐에 발행

    Args:
        body: 파싱된 JSON 메시지 본문
        message: 원본 RabbitMQ 메시지 (Ack/Nack용)
    """
    try:
        # 1. Pydantic으로 페이로드 검증
        request = FeedbackRequest(**body)
        logger.info(
            f"[Feedback Worker] Processing match={request.match_id}, "
            f"users={[u.user_id for u in request.users]}"
        )

        # 2. 비즈니스 로직 위임 (Validation + Backoff + Gemini 호출)
        users_data = [u.model_dump() for u in request.users]
        feedback_result = await pvp_feedback_service.generate_pvp_feedback(
            criteria=request.criteria.model_dump(),
            users=users_data,
        )

        # 3. 성공 응답 생성 및 발행
        response = FeedbackResponse(
            match_id=request.match_id,
            status="SUCCESS",
            feedback=PvpFeedbackResult(**feedback_result),
        )

        await rabbitmq_service.publish(
            settings.FEEDBACK_RESULT_QUEUE, response.model_dump()
        )

        logger.info(f"[Feedback Worker] Completed match={request.match_id}")

    except Exception as e:
        logger.error(f"[Feedback Worker] Business error: {e}")

        # Business Error: 실패 응답을 결과 큐에 발행하고 Ack 처리
        error_response = FeedbackResponse(
            match_id=body.get("match_id", "unknown"),
            status="FAIL",
            error=str(e),
        )

        await rabbitmq_service.publish(
            settings.FEEDBACK_RESULT_QUEUE, error_response.model_dump()
        )


async def start_feedback_consumer() -> None:
    """
    피드백 요청 큐 소비를 시작합니다.
    main.py의 lifespan에서 호출됩니다.
    """
    logger.info("[Feedback Worker] Starting consumer...")
    await rabbitmq_service.consume(
        settings.FEEDBACK_REQUEST_QUEUE, handle_feedback_message
    )
