"""
Challenge Mode Merge Worker (Phase 2: 설계.md 기반 리팩토링)

AI_MERGE_QUEUE 에서 병합 작업을 소비합니다.
1. Redis HMGET으로 텍스트 벌크 로드
2. 기준표(Rubric) 로컬 캐싱 조회
3. PAIRS-beam 정렬
4. 스마트 Lua 스크립트로 결과 라우팅 (PAIR / PROMOTE / WAIT)
5. 최종 랭킹 도달 시 Fan-out 피드백 발행
"""

import json
import math
import logging
from typing import Optional
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.pairs_service import pairs_service
from app.services.redis_lua_script import RedisLuaScripts
import redis.asyncio as aioredis

logger = logging.getLogger("imyme-challenge-worker")

# ── Global State ──
redis_client: Optional[aioredis.Redis] = None
redis_lua: Optional[RedisLuaScripts] = None

# ── Rubric 로컬 메모리 캐시 (knowledge_id -> rubric text) ──
_rubric_cache: dict[str, str] = {}


async def init_redis_for_worker():
    global redis_client, redis_lua
    if redis_client is None:
        redis_client = await aioredis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=10,
            socket_timeout=10,
        )
        redis_lua = RedisLuaScripts(redis_client)
        await redis_lua.init_scripts()


async def _get_rubric(knowledge_id: str) -> str:
    """기준표를 로컬 캐시에서 읽고, 없으면 Redis에서 1회 조회 후 캐싱합니다."""
    if knowledge_id in _rubric_cache:
        return _rubric_cache[knowledge_id]

    redis_key = f"knowledge:{knowledge_id}:rubric"
    data = await redis_client.get(redis_key)
    if data is None:
        logger.warning(f"Rubric not found in Redis for key: {redis_key}")
        _rubric_cache[knowledge_id] = ""
        return ""

    rubric_text = data.decode("utf-8") if isinstance(data, bytes) else data
    _rubric_cache[knowledge_id] = rubric_text
    logger.info(f"Rubric cached for knowledge:{knowledge_id} (len={len(rubric_text)})")
    return rubric_text


async def _bulk_load_texts(job_id: str, id_list: list[str]) -> dict[str, str]:
    """
    Redis Hash에서 attemptId 리스트에 해당하는 텍스트를 한 번에 조회합니다.
    Returns: {attemptId: sttText, ...}
    """
    hash_key = f"challenge:{job_id}:participants"
    raw_list = await redis_client.hmget(hash_key, *id_list)
    result = {}
    for attempt_id, raw in zip(id_list, raw_list):
        if raw:
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                parsed = json.loads(decoded)
                result[attempt_id] = parsed.get("sttText", "")
            except json.JSONDecodeError:
                result[attempt_id] = decoded
        else:
            logger.warning(f"No data for attemptId={attempt_id} in {hash_key}")
            result[attempt_id] = ""
    return result


def _ids_to_items(id_list: list[str], text_map: dict[str, str]) -> list[dict]:
    """attemptId 리스트를 PAIRS 서비스가 요구하는 {id, text} 딕셔너리 리스트로 변환."""
    return [{"id": aid, "text": text_map.get(aid, "")} for aid in id_list]


def _calc_expected_count(n: int) -> int:
    """n개의 노드가 만드는 다음 레벨의 기대 노드 수. ceil(n/2)"""
    return math.ceil(n / 2)


async def process_challenge_merge(body: dict, message: AbstractIncomingMessage) -> None:
    """
    AI_MERGE_QUEUE 의 메시지를 처리하는 핵심 워커.

    Payload:
    {
        "job_id": "uuid-...",
        "knowledgeBase_id": "123",
        "level": 0,
        "array_a": ["attemptId_1"],
        "array_b": ["attemptId_2"],
        "target_count": 100,
        "expected_count": 50      # 이 레벨에서 생겨야 할 노드 수
    }
    """
    job_id = body.get("job_id")
    knowledge_id = body.get("knowledgeBase_id", "")
    level = body.get("level")
    arr_a_ids = body.get("array_a", [])
    arr_b_ids = body.get("array_b", [])
    target_count = body.get("target_count", 100)

    if not all(
        [
            job_id is not None,
            level is not None,
            isinstance(arr_a_ids, list),
            isinstance(arr_b_ids, list),
        ]
    ):
        logger.error(f"Invalid challenge merge payload: {body}")
        return

    logger.info(
        f"Merge Worker started for {job_id} at Level {level}. "
        f"Merging {len(arr_a_ids)} vs {len(arr_b_ids)} (target={target_count})"
    )

    try:
        # 1. 기준표 로컬 캐시 조회
        criteria = await _get_rubric(knowledge_id) if knowledge_id else None

        # 2. Redis Bulk Load: 모든 관련 ID의 텍스트를 한 번에 가져옴
        all_ids = list(set(arr_a_ids + arr_b_ids))
        text_map = await _bulk_load_texts(job_id, all_ids)

        # 3. PAIRS-beam merge
        items_a = _ids_to_items(arr_a_ids, text_map)
        items_b = _ids_to_items(arr_b_ids, text_map)
        merged_items = await pairs_service.merge_beam(items_a, items_b, criteria)

        # 병합 결과는 ID 배열로 변환
        merged_ids = [item["id"] for item in merged_items]

        # 4. 최종 랭킹 체크 (루트 노드 도달?)
        if len(merged_ids) >= target_count:
            await _handle_ranking_complete(
                job_id, knowledge_id, merged_ids, target_count
            )
            return

        # 5. Lua 스크립트로 다음 레벨에 Push & Route
        # expected_count는 BE 값에 의존하지 않고 target_count와 level로 직접 계산한다.
        # 공식: ceil(target_count / 2^next_level)
        # 이유: BE가 잘못된 expected_count를 보내도 정확한 값을 보장하기 위함
        next_level = level + 1
        next_expected = math.ceil(target_count / (2**next_level))
        list_key = f"pairs:{job_id}:level:{next_level}"
        arrived_key = f"pairs:{job_id}:level:{next_level}:arrived"
        serialized = json.dumps(merged_ids, ensure_ascii=False)

        action, data = await redis_lua.push_and_route(
            list_key=list_key,
            arrived_key=arrived_key,
            serialized_array=serialized,
            expected_count=next_expected,
        )

        if action == "PAIR":
            new_arr_a = json.loads(data[0])
            new_arr_b = json.loads(data[1])
            next_mission = {
                "job_id": job_id,
                "knowledgeBase_id": knowledge_id,
                "level": next_level,
                "array_a": new_arr_a,
                "array_b": new_arr_b,
                "target_count": target_count,
                "expected_count": next_expected,
            }
            logger.info(f"Level UP ⬆️ PAIR at Level {next_level} for {job_id}")
            await rabbitmq_service.publish(settings.CHALLENGE_MERGE_QUEUE, next_mission)

        elif action == "PROMOTE":
            promoted_ids = json.loads(data[0])
            logger.info(
                f"🏅 PROMOTE (부전승) at Level {next_level} for {job_id}, "
                f"promoting {len(promoted_ids)} IDs to next level"
            )
            # 부전승: 병합 없이 그대로 한 레벨 더 위로 올림
            await _handle_promote(
                job_id,
                knowledge_id,
                promoted_ids,
                next_level,
                target_count,
            )

        else:  # WAIT
            logger.info(
                f"⏳ WAIT at Level {next_level} for {job_id}. Waiting for pair."
            )

    except Exception as e:
        logger.error(f"Error in challenge merge for {job_id}: {e}")
        raise


async def _handle_promote(
    job_id: str,
    knowledge_id: str,
    promoted_ids: list[str],
    current_level: int,
    target_count: int,
):
    """
    부전승 노드를 상위 레벨로 올립니다. 재귀 대신 이터레이션으로 구현하여

    무한 루프를 방지합니다.

    expected_count는 BE 값에 의존하지 않고 ceil(target_count / 2^level)로 직접 계산합니다.
    max_level = ceil(log2(N)): 이 레벨을 초과하면 토너먼트 루트에 도달한 것으로 완료 처리합니다.

    """
    max_level = math.ceil(math.log2(max(target_count, 2)))

    level = current_level
    ids = promoted_ids

    while True:
        if len(ids) >= target_count:
            await _handle_ranking_complete(job_id, knowledge_id, ids, target_count)
            return

        upper_level = level + 1
        if upper_level > max_level:
            logger.info(
                f"[{job_id}] PROMOTE reached tournament root "
                f"(level {upper_level} > max_level {max_level} = ceil(log2({target_count}))). "
                f"Ranking complete."
            )
            await _handle_ranking_complete(job_id, knowledge_id, ids, target_count)
            return


        upper_expected = math.ceil(target_count / (2**upper_level))

        list_key = f"pairs:{job_id}:level:{upper_level}"
        arrived_key = f"pairs:{job_id}:level:{upper_level}:arrived"
        serialized = json.dumps(ids, ensure_ascii=False)

        action, data = await redis_lua.push_and_route(
            list_key=list_key,
            arrived_key=arrived_key,
            serialized_array=serialized,
            expected_count=upper_expected,
        )

        if action == "PAIR":
            new_arr_a = json.loads(data[0])
            new_arr_b = json.loads(data[1])
            next_mission = {
                "job_id": job_id,
                "knowledgeBase_id": knowledge_id,
                "level": upper_level,
                "array_a": new_arr_a,
                "array_b": new_arr_b,
                "target_count": target_count,
                "expected_count": upper_expected,
            }
            logger.info(f"Level UP PAIR after PROMOTE at Level {upper_level}")
            await rabbitmq_service.publish(settings.CHALLENGE_MERGE_QUEUE, next_mission)
            return

        elif action == "PROMOTE":
            ids = json.loads(data[0])
            level = upper_level
            logger.info(f"Cascading PROMOTE at Level {upper_level}")
            # continue loop

        else:  # WAIT
            logger.info(f"WAIT after PROMOTE at Level {upper_level}")
            return


async def _handle_ranking_complete(
    job_id: str, knowledge_id: str, final_ranking: list[str], target_count: int
):
    """
    최종 랭킹이 완성되었을 때:
    1. Redis에 최종 순위 저장
    2. BE에 랭킹 완료 알림
    3. Fan-out: 각 유저별 피드백 생성 메시지 발행
    """
    logger.info(f"🏆 {job_id} ranking completed! {len(final_ranking)} users ranked.")

    # 1. Redis에 최종 순위 저장  (RPUSH challenge:{id}:final_ranking)
    ranking_key = f"challenge:{job_id}:final_ranking"
    pipe = redis_client.pipeline()
    pipe.delete(ranking_key)
    pipe.rpush(ranking_key, *final_ranking)
    pipe.expire(ranking_key, 14400)  # 4시간 TTL
    await pipe.execute()

    # 2. Fan-out: 100(N)개의 피드백 생성 작업을 개별 MQ 메시지로 퍼블리시
    top1_id = final_ranking[0]
    for rank_idx, attempt_id in enumerate(final_ranking):
        feedback_task = {
            "job_id": job_id,
            "knowledgeBase_id": knowledge_id,
            "attemptId": attempt_id,
            "rank": rank_idx + 1,  # 1-indexed
            "top1_id": top1_id,
            "target_count": target_count,
        }
        await rabbitmq_service.publish(settings.CHALLENGE_FEEDBACK_QUEUE, feedback_task)

    logger.info(
        f"📤 Published {len(final_ranking)} feedback tasks to {settings.CHALLENGE_FEEDBACK_QUEUE}"
    )


async def start_challenge_consumer() -> None:
    """main.py lifespan에서 호출되는 진입점."""
    await init_redis_for_worker()
    logger.info(
        f"Starting Challenge Merge Consumer on {settings.CHALLENGE_MERGE_QUEUE}..."
    )
    await rabbitmq_service.consume(
        queue_name=settings.CHALLENGE_MERGE_QUEUE,
        callback=process_challenge_merge,
    )
