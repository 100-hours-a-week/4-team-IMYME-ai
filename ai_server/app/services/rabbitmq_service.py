"""
RabbitMQ Service Module.
RabbitMQ 비동기 통신 서비스 모듈.

aio-pika의 RobustConnection을 사용하여 네트워크 단절 시 자동 재연결을 보장합니다.
QoS(prefetch_count=1) 설정으로 워커당 1건씩 순차 처리하며,
Manual Ack/Nack 패턴을 적용합니다.
"""

import json
import logging
from typing import Callable, Awaitable

import aio_pika
from aio_pika import ExchangeType, Message, DeliveryMode
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

# DLQ 재시도 횟수 상한
MAX_RETRY_COUNT = 3


class RabbitMQService:
    """
    RabbitMQ 연결, 발행(Publish), 소비(Consume)를 관리하는 서비스 클래스.
    RobustConnection을 통해 네트워크 단절 시 자동 재연결을 보장합니다.
    """

    def __init__(self):
        self.connection: aio_pika.RobustConnection | None = None
        self.channel: aio_pika.RobustChannel | None = None
        self.exchange: aio_pika.Exchange | None = None

    async def connect(self) -> None:
        """
        RabbitMQ 서버에 연결하고 채널, Exchange, DLQ를 초기화합니다.
        RobustConnection을 사용하여 연결이 끊겨도 자동으로 재연결됩니다.
        """
        logger.info(f"Connecting to RabbitMQ: {settings.RABBITMQ_URL}")

        # RobustConnection: 네트워크 단절 시 자동 재연결
        self.connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self.channel = await self.connection.channel()

        # QoS 설정: 워커당 동시에 1개의 메시지만 처리 (순차 처리 보장)
        await self.channel.set_qos(prefetch_count=1)

        # Direct Exchange 선언 (durable: 서버 재시작 후에도 유지)
        self.exchange = await self.channel.declare_exchange(
            settings.PVP_EXCHANGE, ExchangeType.DIRECT, durable=True
        )

        # DLQ (Dead Letter Queue) 선언: MAX_RETRY_COUNT 이후 최종 실패 메시지 보관용
        dlq = await self.channel.declare_queue(settings.PVP_DLQ, durable=True)
        await dlq.bind(self.exchange, routing_key=settings.PVP_DLQ)

        logger.info("RabbitMQ connection established successfully.")

    async def declare_and_bind_queue(self, queue_name: str) -> aio_pika.Queue:
        """
        큐를 선언하고 Exchange에 바인딩합니다.

        [Retry 아키텍처]
        실패 시 메시지 흐름:
          원래 큐 → reject → 재시도큐(5초 TTL) → TTL 만료 → 원래 큐로 복귀
          3회 모두 실패 → DLQ로 최종 이동

        이 구조 덕분에 x-death 헤더의 count가 정상적으로 증가하여
        nack(requeue=True)의 무한 루프 문제를 완벽히 방지합니다.
        """
        retry_queue_name = f"{queue_name}.retry"

        # 1) 재시도큐 선언: 5초 TTL 후 메시지가 원래 큐로 자동 복귀
        await self.channel.declare_queue(
            retry_queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.PVP_EXCHANGE,
                "x-dead-letter-routing-key": queue_name,
                "x-message-ttl": 5000,  # 5초 대기 후 원래 큐로 복귀
            },
        )
        # 재시도큐를 Exchange에 바인딩
        retry_queue = await self.channel.get_queue(retry_queue_name)
        await retry_queue.bind(self.exchange, routing_key=retry_queue_name)

        # 2) 원래 큐 선언: reject된 메시지를 재시도큐로 라우팅
        queue = await self.channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.PVP_EXCHANGE,
                "x-dead-letter-routing-key": retry_queue_name,
            },
        )
        await queue.bind(self.exchange, routing_key=queue_name)
        return queue

    async def publish(self, queue_name: str, message_body: dict) -> None:
        """
        특정 큐에 JSON 메시지를 발행합니다.
        delivery_mode=PERSISTENT로 설정하여 디스크에 저장됩니다.

        Args:
            queue_name: 대상 큐의 라우팅 키
            message_body: 발행할 JSON 직렬화 가능한 딕셔너리
        """
        message = Message(
            body=json.dumps(message_body, ensure_ascii=False).encode(),
            delivery_mode=DeliveryMode.PERSISTENT,  # 메시지 영속성 보장
            content_type="application/json",
        )
        await self.exchange.publish(message, routing_key=queue_name)
        logger.info(f"Published message to '{queue_name}'")

    async def consume(
        self,
        queue_name: str,
        callback: Callable[[dict, AbstractIncomingMessage], Awaitable[None]],
    ) -> None:
        """
        특정 큐를 구독하고 메시지가 올 때마다 callback을 실행합니다.
        Manual Ack 모드로 동작하며, callback 완료 후 Ack를 전송합니다.
        3회 재시도 후에도 실패하면 DLQ로 이동됩니다.

        [Bug Fix] nack(requeue=True)는 x-death 헤더를 갱신하지 않으므로
        retry_count가 영원히 0인 무한 루프를 발생시킵니다.
        대신 reject(requeue=False)로 DLQ Exchange를 경유시켜
        x-death count가 정상적으로 증가하도록 수정합니다.

        Args:
            queue_name: 구독할 큐 이름
            callback: 메시지 처리 콜백 (parsed_body, raw_message)
        """
        queue = await self.declare_and_bind_queue(queue_name)

        async def on_message(message: AbstractIncomingMessage) -> None:
            """개별 메시지 수신 핸들러 (Ack/Nack 관리)"""
            # 재시도 횟수 확인 (x-death 헤더 기반)
            retry_count = _get_retry_count(message)

            try:
                body = json.loads(message.body.decode())
                logger.info(
                    f"Consumed from '{queue_name}' (retry: {retry_count}): "
                    f"match_id={body.get('match_id', 'N/A')}"
                )

                # 콜백 실행 (비즈니스 로직)
                await callback(body, message)

                # 모든 처리가 성공한 후에만 Ack 전송
                await message.ack()

            except Exception as e:
                logger.error(
                    f"Error processing message from '{queue_name}' "
                    f"(retry {retry_count}/{MAX_RETRY_COUNT}): {e}"
                )

                if retry_count < MAX_RETRY_COUNT:
                    # 재시도 가능: reject → 재시도큐(TTL) 경유 → 원래 큐로 복귀
                    # (x-death count가 자동 증가하여 무한 루프 방지)
                    await message.reject(requeue=False)
                    logger.warning(
                        f"Message rejected for retry via retry queue "
                        f"(attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
                    )
                else:
                    # 재시도 초과: 원본 Ack 후 DLQ에 수동 발행
                    # (reject하면 retry queue로 빠지므로, 수동으로 DLQ에 전송)
                    await message.ack()
                    try:
                        dlq_body = json.loads(message.body.decode())
                        dlq_body["_dlq_reason"] = str(e)
                        dlq_body["_dlq_retry_count"] = retry_count
                        await self.publish(settings.PVP_DLQ, dlq_body)
                    except Exception as dlq_err:
                        logger.error(f"Failed to publish to DLQ: {dlq_err}")
                    logger.error(
                        f"Message moved to DLQ after {MAX_RETRY_COUNT} retries."
                    )

        # 큐 소비 시작 (no_ack=False → Manual Ack 모드)
        await queue.consume(on_message, no_ack=False)
        logger.info(f"Started consuming from '{queue_name}'")

    async def close(self) -> None:
        """RabbitMQ 연결을 안전하게 종료합니다."""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("RabbitMQ connection closed.")


def _get_retry_count(message: AbstractIncomingMessage) -> int:
    """
    메시지 헤더의 x-death 정보에서 재시도 횟수를 추출합니다.
    RabbitMQ가 Nack/Reject된 메시지에 자동으로 추가하는 메타데이터입니다.
    """
    if message.headers and "x-death" in message.headers:
        x_death = message.headers["x-death"]
        if isinstance(x_death, list) and len(x_death) > 0:
            return x_death[0].get("count", 0)
    return 0


# 싱글톤 인스턴스 (기존 서비스 패턴과 일관성 유지)
rabbitmq_service = RabbitMQService()
