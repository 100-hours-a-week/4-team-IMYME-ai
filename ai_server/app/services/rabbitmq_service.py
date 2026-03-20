"""
RabbitMQ Service Module.

Provides asynchronous message queue communication using aio-pika's RobustConnection
for automatic reconnection on network failures.

Key features:
- QoS (prefetch_count=1): Sequential processing, one message at a time per worker.
- Manual Ack/Nack: Messages are acknowledged only after successful processing.
- 3-Retry with DLQ: Failed messages are retried up to 3 times via a TTL-based
  retry queue. On the 3rd failure, a FAIL response is published to the result
  queue and the original message is moved to the DLQ for manual inspection.
"""

import json
import logging
from typing import Callable, Awaitable

import aio_pika
from aio_pika import ExchangeType, Message, DeliveryMode
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum number of retry attempts before moving to DLQ
MAX_RETRY_COUNT = 3

# Mapping: request queue name → response queue name
# Used by the retry handler to publish FAIL responses on final failure.
REQUEST_TO_RESPONSE_QUEUE = {
    # PvP Mode
    settings.STT_REQUEST_QUEUE: settings.STT_RESULT_QUEUE,
    settings.FEEDBACK_REQUEST_QUEUE: settings.FEEDBACK_RESULT_QUEUE,
    # Solo Mode
    settings.SOLO_STT_REQUEST_QUEUE: settings.SOLO_STT_RESULT_QUEUE,
    settings.SOLO_FEEDBACK_REQUEST_QUEUE: settings.SOLO_FEEDBACK_RESULT_QUEUE,
    # Challenge STT
    settings.CHALLENGE_STT_REQUEST_QUEUE: settings.CHALLENGE_STT_RESULT_QUEUE,
}


class RabbitMQService:
    """
    RabbitMQ 연결, 발행(Publish), 소비(Consume)를 관리하는 서비스 클래스.
    RobustConnection을 통해 네트워크 단절 시 자동 재연결을 보장합니다.
    """

    def __init__(self):
        self.connection: aio_pika.RobustConnection | None = None
        self.channel: aio_pika.RobustChannel | None = None
        self.pvp_exchange: aio_pika.Exchange | None = None
        self.solo_exchange: aio_pika.Exchange | None = None
        self.challenge_exchange: aio_pika.Exchange | None = None

    def _get_exchange(self, queue_name: str) -> aio_pika.Exchange:
        """Return the correct exchange based on queue name prefix or contained sub-string."""
        if "solo" in queue_name:
            return self.solo_exchange
        if "pairs" in queue_name or "ranking" in queue_name:
            return self.challenge_exchange
        return self.pvp_exchange

    def _get_dlq(self, queue_name: str) -> str:
        """Return the correct DLQ name based on queue name prefix."""
        if queue_name.startswith("solo."):
            return settings.SOLO_DLQ
        if "pairs" in queue_name or "ranking" in queue_name:
            return settings.CHALLENGE_DLQ
        return settings.PVP_DLQ

    async def connect(self) -> None:
        """
        Connect to RabbitMQ and initialize channel, exchange, and DLQ.
        Uses RobustConnection for automatic reconnection on network failure.
        """
        logger.info(f"Connecting to RabbitMQ: {settings.RABBITMQ_URL}")

        # RobustConnection: automatic reconnection on network disruption
        self.connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self.channel = await self.connection.channel()

        # QoS: process one message at a time per worker (sequential guarantee)
        await self.channel.set_qos(prefetch_count=1)

        # Declare Direct Exchange (durable: survives server restart)
        self.pvp_exchange = await self.channel.declare_exchange(
            settings.PVP_EXCHANGE, ExchangeType.DIRECT, durable=True
        )

        # Declare DLQ: permanent storage for messages that exceeded MAX_RETRY_COUNT
        dlq = await self.channel.declare_queue(settings.PVP_DLQ, durable=True)
        await dlq.bind(self.pvp_exchange, routing_key=settings.PVP_DLQ)

        # Solo Mode Exchange & DLQ
        self.solo_exchange = await self.channel.declare_exchange(
            settings.SOLO_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        solo_dlq = await self.channel.declare_queue(settings.SOLO_DLQ, durable=True)
        await solo_dlq.bind(self.solo_exchange, routing_key=settings.SOLO_DLQ)

        # Challenge Mode Exchange & DLQ
        self.challenge_exchange = await self.channel.declare_exchange(
            settings.CHALLENGE_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        challenge_dlq = await self.channel.declare_queue(
            settings.CHALLENGE_DLQ, durable=True
        )
        await challenge_dlq.bind(
            self.challenge_exchange, routing_key=settings.CHALLENGE_DLQ
        )

        logger.info("RabbitMQ connection established successfully.")

    async def declare_and_bind_queue(self, queue_name: str) -> aio_pika.Queue:
        """
        Declare a queue and bind it to the exchange.

        [Retry Architecture]
        Message flow on failure:
          Main Queue → reject → Retry Queue (5s TTL) → TTL expires → Main Queue
          After 3 total failures → DLQ (permanent storage)

        Using reject(requeue=False) instead of nack(requeue=True) ensures that
        x-death header count increments correctly, preventing infinite retry loops.
        """
        retry_queue_name = f"{queue_name}.retry"
        exchange = self._get_exchange(queue_name)
        exchange_name = exchange.name

        # 1) Retry Queue: messages wait here for 5s TTL, then auto-route back
        await self.channel.declare_queue(
            retry_queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": exchange_name,
                "x-dead-letter-routing-key": queue_name,
                "x-message-ttl": 5000,  # 5 second delay before retry
            },
        )
        retry_queue = await self.channel.get_queue(retry_queue_name)
        await retry_queue.bind(exchange, routing_key=retry_queue_name)

        # 2) Main Queue: rejected messages route to the retry queue above
        queue = await self.channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": exchange_name,
                "x-dead-letter-routing-key": retry_queue_name,
            },
        )
        await queue.bind(exchange, routing_key=queue_name)
        return queue

    async def publish(self, queue_name: str, message_body: dict) -> None:
        """
        Publish a JSON message to the specified queue.
        delivery_mode=PERSISTENT ensures the message survives server restarts.

        Args:
            queue_name: Target queue's routing key
            message_body: JSON-serializable dictionary to publish
        """
        message = Message(
            body=json.dumps(message_body, ensure_ascii=False).encode(),
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        exchange = self._get_exchange(queue_name)
        await exchange.publish(message, routing_key=queue_name)
        logger.info(f"Published message to '{queue_name}'")

    async def consume(
        self,
        queue_name: str,
        callback: Callable[[dict, AbstractIncomingMessage], Awaitable[None]],
    ) -> None:
        """
        Subscribe to a queue and execute a callback for each incoming message.
        Operates in Manual Ack mode; Ack is sent only after successful processing.

        [Retry Flow]
        1. Worker raises Exception → message is reject(requeue=False)
        2. Rejected message routes to retry queue (5s TTL delay)
        3. After TTL expires, message returns to the main queue for retry
        4. After MAX_RETRY_COUNT (3) failures:
           - A FAIL response is published to the result queue
             (so the main server can stop waiting and close the match)
           - The original message is archived in DLQ for manual inspection

        Args:
            queue_name: Queue name to subscribe to
            callback: Message processing callback (parsed_body, raw_message)
        """
        queue = await self.declare_and_bind_queue(queue_name)

        # Determine the response queue for publishing FAIL on final failure
        response_queue = REQUEST_TO_RESPONSE_QUEUE.get(queue_name)

        async def on_message(message: AbstractIncomingMessage) -> None:
            """Per-message handler with Ack/Reject management."""
            retry_count = _get_retry_count(message)

            try:
                body = json.loads(message.body.decode())
                # Determine the primary identifier for logging
                id_key = "attempt_id"
                if "challenge" in queue_name:
                    id_key = "attemptId"
                elif "pvp" in queue_name:
                    id_key = "room_id"
                logger.info(
                    f"Consumed from '{queue_name}' (retry: {retry_count}): "
                    f"{id_key}={body.get(id_key, 'N/A')}"
                )

                # Execute business logic callback (worker handler)
                await callback(body, message)

                # Ack only after all processing succeeds
                await message.ack()

            except Exception as e:
                logger.error(
                    f"Error processing message from '{queue_name}' "
                    f"(retry {retry_count + 1}/{MAX_RETRY_COUNT}): {e}"
                )

                if retry_count < MAX_RETRY_COUNT - 1:
                    # ──────────────────────────────────────────────────
                    # RETRYABLE: reject → retry queue (5s TTL) → back to main queue
                    # x-death count auto-increments to prevent infinite loops
                    # ──────────────────────────────────────────────────
                    await message.reject(requeue=False)
                    logger.warning(
                        f"Message rejected for retry via retry queue "
                        f"(attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
                    )
                else:
                    # ──────────────────────────────────────────────────
                    # FINAL FAILURE (3rd attempt): Ack + DLQ + FAIL response
                    # ──────────────────────────────────────────────────
                    await message.ack()

                    # 1) Archive the original message to DLQ for debugging/replay
                    try:
                        dlq_body = json.loads(message.body.decode())
                        dlq_body["_dlq_reason"] = str(e)
                        dlq_body["_dlq_retry_count"] = retry_count + 1
                        await self.publish(self._get_dlq(queue_name), dlq_body)
                    except Exception as dlq_err:
                        logger.error(f"Failed to publish to DLQ: {dlq_err}")

                    # 2) Publish FAIL response to the result queue
                    #    so the main server can terminate the match gracefully
                    if response_queue:
                        try:
                            original_body = json.loads(message.body.decode())
                            fail_response = {
                                "status": "FAIL",
                                "error": (
                                    f"Message failed after {MAX_RETRY_COUNT} "
                                    f"retry attempts: {str(e)}"
                                ),
                            }
                            # Preserve all known identifiers from the original body
                            for key in [
                                "room_id",
                                "attempt_id",
                                "attemptId",
                                "challengeId",
                                "request_id",
                                "user_id",
                            ]:
                                if key in original_body:
                                    fail_response[key] = original_body[key]

                            # Schema-specific Null fields for final failure
                            if (
                                "challenge" in queue_name
                                and "feedback.request" in queue_name
                            ):
                                fail_response["sttText"] = None
                            elif "users" in original_body:
                                fail_response["feedbacks"] = None

                            await self.publish(response_queue, fail_response)
                            logger.info(
                                f"Published FAIL response to '{response_queue}' "
                                f"for {id_key}={fail_response[id_key]}"
                            )
                        except Exception as fail_err:
                            logger.error(f"Failed to publish FAIL response: {fail_err}")

                    logger.error(
                        f"Message moved to DLQ after {MAX_RETRY_COUNT} retries."
                    )

        # Start consuming (no_ack=False → Manual Ack mode)
        await queue.consume(on_message, no_ack=False)
        logger.info(f"Started consuming from '{queue_name}'")

    async def close(self) -> None:
        """Safely close the RabbitMQ connection."""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("RabbitMQ connection closed.")


def _get_retry_count(message: AbstractIncomingMessage) -> int:
    """
    Extract retry count from the x-death header.
    RabbitMQ automatically adds this metadata when a message is rejected.
    """
    if message.headers and "x-death" in message.headers:
        x_death = message.headers["x-death"]
        if isinstance(x_death, list) and len(x_death) > 0:
            return x_death[0].get("count", 0)
    return 0


# Singleton instance (consistent with existing service patterns)
rabbitmq_service = RabbitMQService()
