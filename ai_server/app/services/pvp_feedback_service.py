"""
PvP Feedback Service Module.
PvP 모드 비교 피드백 생성 서비스.

RabbitMQ 워커로부터 독립된 비즈니스 로직 모듈로,
Solo 모드의 feedback_service.py + prompt_manager.py와 동일한 패턴으로 설계되었습니다.

주요 기능:
- 랜덤 전략 선택: PVP_PERSONA_PROMPTS 4종 중 1개를 random.choice()로 선택
- 사전 검증: Case A(양측 기권 → 무승부), Case B(편측 기권 → 부전승/LLM 호출)
- 지수 백오프: Gemini API 호출 시 일시적 장애 대비 재시도
- 프롬프트 연동: PVP_SYSTEM_PROMPT + 선택된 전략을 조합하여 피드백 생성
"""

import json
import random
import logging
from typing import List, Dict, Any

import google.generativeai as genai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.core.prompts import PVP_SYSTEM_PROMPT, PVP_PERSONA_PROMPTS

logger = logging.getLogger(__name__)

# 솔로 모드(analysis_service.py)와 동일한 최소 텍스트 길이 기준
MIN_TEXT_LENGTH = 5

# 부전승 시 기권자의 텍스트를 대체할 문구
FORFEIT_PLACEHOLDER = "(답변을 제출하지 않아 기권 처리되었습니다.)"


class PvpFeedbackService:
    """
    PvP 비교 피드백을 생성하는 서비스 클래스.

    Solo 모드의 PromptManager와 동일한 패턴:
    - Solo: BASE_SYSTEM_PROMPT + random.choice(PERSONA_PROMPTS)
    - PvP:  PVP_SYSTEM_PROMPT  + random.choice(PVP_PERSONA_PROMPTS)
    """

    def __init__(self):
        self.model = None
        self.strategies = list(PVP_PERSONA_PROMPTS.keys())
        if settings.GEMINI_API_KEY:
            self.model = genai.GenerativeModel("gemini-3-flash-preview")

    async def generate_pvp_feedback(
        self, criteria: dict, users: List[Dict[str, Any]]
    ) -> dict:
        """
        2명의 사용자 텍스트를 비교 분석하여 PvP 피드백을 생성합니다.

        출력 JSON 구조는 배열 형태입니다:
        [{summary, keywords, facts, understanding, personalized_feedback}, ...] (유저별)

        Args:
            criteria: 채점 기준 (keyword, model_answer)
            users: 2명의 사용자 데이터 리스트 [{user_id, user_text}, ...]

        Returns:
            PvP 비교 피드백 결과 리스트 (유저별 딕셔너리 배열)
        """
        user_a = users[0]
        user_b = users[1]

        a_text = user_a.get("user_text", "").strip()
        b_text = user_b.get("user_text", "").strip()

        a_short = len(a_text) < MIN_TEXT_LENGTH
        b_short = len(b_text) < MIN_TEXT_LENGTH

        # ===== Case A: 양측 모두 기권 (무승부) =====
        if a_short and b_short:
            logger.info(
                f"Both users submitted short text: A={len(a_text)}, B={len(b_text)}. "
                f"Returning mutual forfeit (draw) response."
            )
            draw_msg = "두 분 모두 답변 내용이 부족하여 승부를 가릴 수 없습니다."
            return [
                {
                    "user_id": user_a["user_id"],
                    "score": 0,
                    "summary": draw_msg,
                    "keywords": ["포함된 키워드: 없음", "누락된 키워드: 전체"],
                    "facts": draw_msg,
                    "understanding": draw_msg,
                    "personalized_feedback": draw_msg,
                },
                {
                    "user_id": user_b["user_id"],
                    "score": 0,
                    "summary": draw_msg,
                    "keywords": ["포함된 키워드: 없음", "누락된 키워드: 전체"],
                    "facts": draw_msg,
                    "understanding": draw_msg,
                    "personalized_feedback": draw_msg,
                },
            ]

        # ===== Case B: 한쪽만 기권 (부전승) =====
        if a_short:
            logger.info(
                f"User A submitted short text ({len(a_text)} chars). "
                f"Replacing with forfeit placeholder for Win-by-Default."
            )
            user_a = {**user_a, "user_text": FORFEIT_PLACEHOLDER}

        if b_short:
            logger.info(
                f"User B submitted short text ({len(b_text)} chars). "
                f"Replacing with forfeit placeholder for Win-by-Default."
            )
            user_b = {**user_b, "user_text": FORFEIT_PLACEHOLDER}

        # ===== 정상 흐름: 랜덤 전략 선택 + 프롬프트 조합 =====
        # Solo의 PromptManager.get_system_prompt() 패턴과 동일
        selected_strategy_key = random.choice(self.strategies)
        selected_strategy = PVP_PERSONA_PROMPTS[selected_strategy_key]
        logger.info(f"Selected PvP strategy: {selected_strategy_key}")

        criteria_str = json.dumps(criteria, ensure_ascii=False, indent=2)

        prompt = PVP_SYSTEM_PROMPT.format(
            criteria=criteria_str,
            user_a_id=user_a["user_id"],
            user_a_text=user_a["user_text"],
            user_b_id=user_b["user_id"],
            user_b_text=user_b["user_text"],
            pvp_strategy=selected_strategy,
        )

        raw_response = await self._call_gemini_with_retry(prompt)

        # JSON 파싱: markdown 코드블록 제거 후 파싱
        cleaned_text = (
            raw_response.text.replace("```json", "").replace("```", "").strip()
        )
        result = json.loads(cleaned_text)

        # CoT reasoning 필드는 내부 추론용이므로 최종 응답에서 제거
        result.pop("reasoning", None)

        # Gemini 응답이 {user_A, user_B} 객체 형태로 올 경우 배열로 변환
        if isinstance(result, dict):
            feedbacks = []
            for key in ["user_A", "user_B"]:
                if key in result:
                    feedbacks.append(result[key])
            if feedbacks:
                return feedbacks

        # 이미 배열 형태라면 그대로 반환
        if isinstance(result, list):
            return result

        return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call_gemini_with_retry(self, prompt: str):
        """
        Gemini API 호출을 지수 백오프로 재시도합니다.
        429(Rate Limit)나 500 에러 시 2초, 4초, 8초 간격으로 최대 3회 재시도.
        """
        logger.info("Calling Gemini API for PvP feedback...")
        response = await self.model.generate_content_async(prompt)
        return response


# 싱글톤 인스턴스
pvp_feedback_service = PvpFeedbackService()
