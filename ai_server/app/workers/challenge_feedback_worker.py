"""
Challenge Mode Feedback Worker (Phase 4: 설계.md 기반)

AI_FEEDBACK_QUEUE 에서 개별 피드백 생성 작업을 소비합니다.
- Rank 1: 솔로 모드 프롬프트로 단독 코칭 피드백 생성
- Rank 2~N: PvP 모드 프롬프트로 1등과 비교 코칭 피드백 생성
- 생성된 결과를 challenge:{id}:feedbacks Hash에 HSET으로 저장
"""

import json
import random
import logging
from typing import Optional
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.core.prompts import (
    BASE_SYSTEM_PROMPT,
    PERSONA_PROMPTS,
    PVP_SYSTEM_PROMPT,
    PVP_PERSONA_PROMPTS,
)
from app.services.rabbitmq_service import rabbitmq_service
import redis.asyncio as aioredis

import google.generativeai as genai_standard

logger = logging.getLogger("imyme-challenge-feedback-worker")

# ── 짧은 텍스트(기권) 방어 상수 (pvp_feedback_service.py와 동일) ──
MIN_TEXT_LENGTH = 5
FORFEIT_PLACEHOLDER = "(답변을 제출하지 않아 기권 처리되었습니다.)"
DRAW_MSG = "모든 유저의 내용이 부족하여 피드백을 할 수 없습니다."

# ── Global State ──
redis_client: Optional[aioredis.Redis] = None

# ── Rubric 로컬 메모리 캐시 (재사용) ──
_rubric_cache: dict[str, str] = {}


async def init_redis_for_feedback_worker():
    global redis_client
    if redis_client is None:
        redis_client = await aioredis.from_url(settings.REDIS_URL)


async def _get_rubric(knowledge_id: str) -> str:
    """기준표를 로컬 캐시에서 읽고, 없으면 Redis에서 1회 조회 후 캐싱합니다."""
    if knowledge_id in _rubric_cache:
        return _rubric_cache[knowledge_id]

    redis_key = f"knowledge:{knowledge_id}:rubric"
    data = await redis_client.get(redis_key)
    if data is None:
        _rubric_cache[knowledge_id] = ""
        return ""

    rubric_text = data.decode("utf-8") if isinstance(data, bytes) else data
    _rubric_cache[knowledge_id] = rubric_text
    return rubric_text


async def _get_participant_data(job_id: str, attempt_id: str) -> dict:
    """Redis Hash에서 특정 참가자의 전체 데이터(userId, sttText)를 조회합니다."""
    hash_key = f"challenge:{job_id}:participants"
    raw = await redis_client.hget(hash_key, attempt_id)
    if raw is None:
        return {"userId": None, "sttText": ""}
    decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        parsed = json.loads(decoded)
        return {"userId": parsed.get("userId"), "sttText": parsed.get("sttText", "")}
    except json.JSONDecodeError:
        return {"userId": None, "sttText": decoded}


def _hardcoded_feedback(msg: str) -> dict:
    """LLM 호출 없이 즉시 반환할 하드코딩 피드백을 생성합니다."""
    return {
        "summary": msg,
        "keywords": [],
        "facts": msg,
        "understanding": msg,
        "personalized_feedback": msg,
    }


async def _generate_solo_feedback(criteria: str, user_text: str) -> dict:
    """Solo 모드 프롬프트로 피드백을 생성합니다 (Rank 1 전용)."""
    persona_key = random.choice(list(PERSONA_PROMPTS.keys()))
    persona_instruction = PERSONA_PROMPTS[persona_key]

    full_prompt = (
        BASE_SYSTEM_PROMPT.format(
            criteria=criteria,
            user_text=user_text,
            history="",  # 챌린지 모드에서는 학습 이력 없음
        )
        + persona_instruction
    )

    model = genai_standard.GenerativeModel("gemini-3-flash-preview")
    response = await model.generate_content_async(full_prompt)

    try:
        text = response.text.strip()
        # JSON 코드 블록 제거
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse solo feedback JSON: {e}")
        return {
            "summary": "피드백 생성 중 오류가 발생했습니다.",
            "keywords": [],
            "facts": "",
            "understanding": "",
            "personalized_feedback": "",
        }


async def _generate_pvp_feedback(
    criteria: str, top1_text: str, my_text: str, top1_id: str, my_id: str
) -> dict:
    """PvP 모드 프롬프트로 1등과 비교하는 피드백을 생성합니다 (Rank 2~N 전용)."""
    strategy_key = random.choice(list(PVP_PERSONA_PROMPTS.keys()))
    pvp_strategy = PVP_PERSONA_PROMPTS[strategy_key]

    full_prompt = PVP_SYSTEM_PROMPT.format(
        criteria=criteria,
        user_a_id=top1_id,
        user_a_text=top1_text,
        user_b_id=my_id,
        user_b_text=my_text,
        pvp_strategy=pvp_strategy,
    )

    model = genai_standard.GenerativeModel("gemini-3-flash-preview")
    response = await model.generate_content_async(full_prompt)

    try:
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        parsed = json.loads(text)
        # user_B 부분만 추출하여 반환 (현재 유저 = user_B)
        return parsed.get("user_B", parsed)
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse PvP feedback JSON: {e}")
        return {
            "summary": "피드백 생성 중 오류가 발생했습니다.",
            "keywords": [],
            "facts": "",
            "understanding": "",
            "personalized_feedback": "",
        }


async def process_challenge_feedback(
    body: dict, message: AbstractIncomingMessage
) -> None:
    """
    AI_FEEDBACK_QUEUE 의 메시지를 처리하는 피드백 워커.

    Payload:
    {
        "job_id": "uuid-...",
        "knowledgeBase_id": "123",
        "attemptId": "456",
        "rank": 3,
        "top1_id": "789",
        "target_count": 100
    }
    """
    job_id = body.get("job_id")
    knowledge_id = body.get("knowledgeBase_id", "")
    attempt_id = body.get("attemptId")
    rank = body.get("rank", 0)
    top1_id = body.get("top1_id", "")

    if not all([job_id, attempt_id]):
        logger.error(f"Invalid feedback payload: {body}")
        return

    logger.info(
        f"Feedback Worker started for {job_id}, attemptId={attempt_id}, rank={rank}"
    )

    try:
        # 1. 기준표 (Rubric) 캐시 로드
        criteria = await _get_rubric(knowledge_id) if knowledge_id else ""

        # 2. 내 참가자 데이터 조회 (userId + sttText)
        my_data = await _get_participant_data(job_id, attempt_id)
        my_text = my_data["sttText"]
        my_user_id = my_data["userId"]

        # 3. 짧은 텍스트 검사 (PvP와 동일한 기권 방어 로직)
        my_short = len(my_text.strip()) < MIN_TEXT_LENGTH

        if rank == 1:
            # ── 1등: Solo 모드 피드백 ──
            if my_short:
                logger.info(
                    f"⏭️ Rank 1 short text ({len(my_text.strip())} chars). "
                    f"Returning hardcoded feedback for {attempt_id}"
                )
                feedback = _hardcoded_feedback(DRAW_MSG)
            else:
                logger.info(f"🥇 Generating SOLO feedback for rank 1 ({attempt_id})")
                feedback = await _generate_solo_feedback(criteria, my_text)
        else:
            # ── 2등 이하: PvP 모드 (1등과 비교) ──
            top1_data = await _get_participant_data(job_id, top1_id)
            top1_text = top1_data["sttText"]
            top1_short = len(top1_text.strip()) < MIN_TEXT_LENGTH

            if top1_short:
                # Case 1/3: 1등이 짧으면 비교 자체가 불가능 → 하드코딩
                logger.info(
                    f"⏭️ Top1 ({top1_id}) text too short ({len(top1_text.strip())} chars). "
                    f"Cannot compare. Hardcoded feedback for {attempt_id}"
                )
                feedback = _hardcoded_feedback(DRAW_MSG)
            elif my_short:
                # Case 2: 나만 짧음 → 기권 처리 문구로 치환 후 LLM 비교
                logger.info(
                    f"⏭️ My text too short ({len(my_text.strip())} chars). "
                    f"Replacing with forfeit placeholder for {attempt_id}"
                )
                my_text = FORFEIT_PLACEHOLDER
                feedback = await _generate_pvp_feedback(
                    criteria, top1_text, my_text, top1_id, attempt_id
                )
            else:
                # Case 4: 둘 다 정상 길이 → 정상 PvP 비교
                logger.info(
                    f"🏅 Generating PvP feedback for rank {rank} ({attempt_id}) vs top1 ({top1_id})"
                )
                feedback = await _generate_pvp_feedback(
                    criteria, top1_text, my_text, top1_id, attempt_id
                )

        # 4. 결과 조립 및 Redis 저장 (BE 명세에 맞는 구조)
        result = {
            "user_id": my_user_id,
            "rank": rank,
            "feedback_json": json.dumps(feedback, ensure_ascii=False),
        }
        feedback_hash_key = f"challenge:{job_id}:feedbacks"
        await redis_client.hset(
            feedback_hash_key, attempt_id, json.dumps(result, ensure_ascii=False)
        )
        # TTL 설정 (4시간)
        await redis_client.expire(feedback_hash_key, 14400)

        logger.info(
            f"✅ Feedback saved for {attempt_id} (rank {rank}) -> {feedback_hash_key}"
        )

        # 5. 모든 피드백이 생성되었는지 확인 후 BE에 최종 알림
        target_count = body.get("target_count")
        if target_count:
            fb_count = await redis_client.hlen(feedback_hash_key)
            if fb_count >= target_count:
                completed_msg = {"job_id": job_id, "status": "RANKING_COMPLETED"}
                await rabbitmq_service.publish(
                    settings.CHALLENGE_COMPLETED_QUEUE, completed_msg
                )
                logger.info(
                    f"🎉 All {fb_count} feedbacks completed! Published to {settings.CHALLENGE_COMPLETED_QUEUE}"
                )

    except Exception as e:
        logger.error(f"Error generating feedback for {attempt_id}: {e}")
        raise


async def start_challenge_feedback_consumer() -> None:
    """main.py lifespan에서 호출되는 진입점."""
    await init_redis_for_feedback_worker()
    logger.info(
        f"Starting Challenge Feedback Consumer on {settings.CHALLENGE_FEEDBACK_QUEUE}..."
    )
    await rabbitmq_service.consume(
        queue_name=settings.CHALLENGE_FEEDBACK_QUEUE,
        callback=process_challenge_feedback,
    )
