"""
STT Worker Module.
STT 워커: RabbitMQ에서 음성 URL을 소비하여 RunPod STT 결과를 반환합니다.

pvp.stt.request 큐에서 메시지를 소비하고,
RunPod STT 서버를 호출하여 텍스트를 추출한 뒤,
pvp.stt.response 큐로 결과를 발행합니다.
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
    STT 요청 메시지를 처리하는 콜백 함수.

    1. 메시지를 STTRequest 스키마로 파싱
    2. RunPod STT 서버에 요청하여 텍스트 추출
    3. 성공/실패에 따라 STTResponse를 결과 큐에 발행

    Args:
        body: 파싱된 JSON 메시지 본문
        message: 원본 RabbitMQ 메시지 (Ack/Nack용)
    """
    try:
        # 1. Pydantic으로 페이로드 검증
        request = STTRequest(**body)
        logger.info(
            f"[STT Worker] Processing match={request.match_id}, "
            f"user={request.user_id}"
        )

        # 2. RunPod STT 호출
        # transcribe_sync는 blocking 함수(requests + time.sleep)이므로
        # asyncio.to_thread로 스레드 풀에 위임하여 이벤트 루프 차단 방지
        stt_result = await asyncio.to_thread(
            runpod_client.transcribe_sync,
            audio_url=request.file_url,
        )

        # 3. 성공 응답 생성 및 발행
        response = STTResponse(
            match_id=request.match_id,
            user_id=request.user_id,
            status="SUCCESS",
            stt_text=stt_result.get("text", ""),
        )

        await rabbitmq_service.publish(
            settings.STT_RESULT_QUEUE, response.model_dump()
        )

        logger.info(
            f"[STT Worker] Completed match={request.match_id}, "
            f"user={request.user_id}"
        )

    except Exception as e:
        logger.error(f"[STT Worker] Business error: {e}")

        # Business Error: 실패 응답을 결과 큐에 발행하고 Ack 처리
        # (pvp_spec.md 에러 핸들링 규격 참조)
        error_response = STTResponse(
            match_id=body.get("match_id", "unknown"),
            user_id=body.get("user_id", "unknown"),
            status="FAIL",
            error=str(e),
        )

        await rabbitmq_service.publish(
            settings.STT_RESULT_QUEUE, error_response.model_dump()
        )

        # 비즈니스 에러이므로 예외를 다시 raise하지 않음 → Ack 처리됨
        # (raise하면 rabbitmq_service의 Nack 로직이 트리거됨)


async def start_stt_consumer() -> None:
    """
    STT 요청 큐 소비를 시작합니다.
    main.py의 lifespan에서 호출됩니다.
    """
    logger.info("[STT Worker] Starting consumer...")
    await rabbitmq_service.consume(
        settings.STT_REQUEST_QUEUE, handle_stt_message
    )
