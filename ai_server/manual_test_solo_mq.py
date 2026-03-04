import asyncio
import json
import aio_pika
from app.core.config import settings


async def main():
    print(f"🔗 RabbitMQ 연결 중... ({settings.RABBITMQ_URL})")
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await connection.channel()

    # Exchange 선언
    exchange = await channel.declare_exchange(
        settings.SOLO_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )

    # 응답을 받을 Response 큐 선언 및 바인딩 (AI 워커가 여기로 결과를 줍니다)
    stt_res_queue = await channel.declare_queue(
        settings.SOLO_STT_RESULT_QUEUE, durable=True
    )
    await stt_res_queue.bind(exchange, routing_key=settings.SOLO_STT_RESULT_QUEUE)

    fb_res_queue = await channel.declare_queue(
        settings.SOLO_FEEDBACK_RESULT_QUEUE, durable=True
    )
    await fb_res_queue.bind(exchange, routing_key=settings.SOLO_FEEDBACK_RESULT_QUEUE)

    # 이전 테스트에서 남아있는 메시지 싹 비우기 (Purge)
    await stt_res_queue.purge()
    await fb_res_queue.purge()

    import random

    stt_room_id = random.randint(10000, 90000)
    fb_room_id = random.randint(10000, 90000)

    # 1. STT 테스트 요청 생성
    stt_request = {
        "room_id": stt_room_id,
        "user_id": 100,
        "audio_url": "https://www.w3schools.com/html/horse.txt",  # 정상적인 테스트용 오디오
        "timestamp": 1700000000,
    }

    print("\n[1] Solo STT 큐에 메시지 발행 중...")
    await exchange.publish(
        aio_pika.Message(body=json.dumps(stt_request).encode()),
        routing_key=settings.SOLO_STT_REQUEST_QUEUE,
    )

    # 2. Feedback 테스트 요청 생성
    fb_request = {
        "room_id": fb_room_id,
        "user_id": 100,
        "user_text": "프로세스는 실행 중인 프로그램입니다.",
        "criteria": {"keyword": "Process"},
        "history": [],
        "timestamp": 1700000000,
    }

    print("[2] Solo Feedback 큐에 메시지 발행 중...")
    await exchange.publish(
        aio_pika.Message(body=json.dumps(fb_request).encode()),
        routing_key=settings.SOLO_FEEDBACK_REQUEST_QUEUE,
    )

    print(
        "\n⏳ AI 서버의 응답을 기다리는 중... (최대 60초 대기 - 에러 재시도 로직으로 인해 20~30초 소요 가능)"
    )

    try:
        # STT 응답 대기
        async with asyncio.timeout(60.0):
            async with stt_res_queue.iterator() as queue_iter:
                async for stt_msg in queue_iter:
                    async with stt_msg.process():
                        print("\n✅ [STT 응답 도착!]")
                        print(
                            json.dumps(
                                json.loads(stt_msg.body.decode()),
                                indent=2,
                                ensure_ascii=False,
                            )
                        )
                        break

        # Feedback 응답 대기
        async with asyncio.timeout(60.0):
            async with fb_res_queue.iterator() as queue_iter:
                async for fb_msg in queue_iter:
                    async with fb_msg.process():
                        print("\n✅ [Feedback 응답 도착!]")
                        print(
                            json.dumps(
                                json.loads(fb_msg.body.decode()),
                                indent=2,
                                ensure_ascii=False,
                            )
                        )
                        break

    except TimeoutError:
        print(
            "\n❌ 응답 타임아웃! AI 서버가 켜져있는지, 에러 로그가 없는지 확인하세요."
        )
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")

    await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
