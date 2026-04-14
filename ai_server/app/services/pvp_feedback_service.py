"""
PvP Feedback Service Module.
PvP 모드 비교 피드백 생성 서비스.

RabbitMQ 워커로부터 독립된 비즈니스 로직 모듈로,
Solo 모드의 feedback_service.py + prompt_manager.py와 동일한 패턴으로 설계되었습니다.

주요 기능:
- PAIRS 사전 판정: pairs_service.compare_pair()를 이용한 양방향 위치 편향 보정 검증
  * 엔트로피 > u_h(0.6): 무승부(Draw) → 동점 지시 주입
  * 엔트로피 ≤ u_h(0.6): 단독 승자 → 승자 ID 기반 지시 주입
- 랜덤 전략 선택: PVP_PERSONA_PROMPTS 4종 중 1개를 random.choice()로 선택
- 사전 검증: Case A(양측 기권 → 무승부), Case B(편측 기권 → 부전승/LLM 호출)
- 지수 백오프: Gemini API 호출 시 일시적 장애 대비 재시도
- 프롬프트 연동: PVP_SYSTEM_PROMPT + 선택된 전략을 조합하여 피드백 생성
"""

import asyncio
import json
import random
import logging
from typing import List, Dict, Any, Optional

import google.generativeai as genai

from app.core.config import settings
from app.core.prompts import PVP_SYSTEM_PROMPT, PVP_PERSONA_PROMPTS

logger = logging.getLogger(__name__)

# 솔로 모드(analysis_service.py)와 동일한 최소 텍스트 길이 기준
MIN_TEXT_LENGTH = 5

# 부전승 시 기권자의 텍스트를 대체할 문구
FORFEIT_PLACEHOLDER = "(답변을 제출하지 않아 기권 처리되었습니다.)"

# PAIRS 엔트로피 임계값: pairs_service와 동일한 값으로 고정
ENTROPY_THRESHOLD = 0.6

# ── evaluation_directive 템플릿 ──────────────────────────────────────────────
# 무승부 지시: 엔트로피 초과로 두 답변의 우열을 판별하기 어려울 때 사용.
_DRAW_DIRECTIVE = (
    "🚨 [무승부 판정 (Draw)] 🚨\n"
    "이 대결은 사전 정밀 비교 검증(PAIRS 양방향 보정) 결과 "
    "두 답변의 품질 차이가 통계적으로 유의미하지 않아 "
    "**무승부(DRAW)** 로 판정되었습니다.\n"
    "- 두 사용자에게 **반드시 동일한 점수(Tie)**를 부여하세요.\n"
    "- 피드백은 어느 한쪽의 일방적 우위보다는, "
    "양측이 공통으로 잘한 점과 함께 보완해야 할 공통 약점에 집중하세요."
)

# 단독 승자 지시: 특정 유저가 통계적으로 우세할 때 사용.
_WINNER_DIRECTIVE_TEMPLATE = (
    "🚨 [승자 판정 (Winner)] 🚨\n"
    "이 대결은 사전 정밀 비교 검증(PAIRS 양방향 보정) 결과 "
    "사용자 {winner_id}의 답변이 통계적으로 더 우수하다고 판정되었습니다.\n"
    "- **반드시 사용자 {winner_id}에게 더 높은 점수**를 부여하고, "
    "상대방에게는 낮은 점수를 부여하세요.\n"
    "- 피드백에서 승패를 가른 결정적인 차이점을 명확히 강조하세요."
)


def _build_evaluation_directive(
    is_draw: bool,
    winner_id: Optional[int] = None,
) -> str:
    """PAIRS 판정 결과를 자연어 지시로 변환합니다."""
    if is_draw:
        return _DRAW_DIRECTIVE
    return _WINNER_DIRECTIVE_TEMPLATE.format(winner_id=winner_id)


class PvpFeedbackService:
    """
    PvP 비교 피드백을 생성하는 서비스 클래스.

    Solo 모드의 PromptManager와 동일한 패턴:
    - Solo: BASE_SYSTEM_PROMPT + random.choice(PERSONA_PROMPTS)
    - PvP:  PVP_SYSTEM_PROMPT  + random.choice(PVP_PERSONA_PROMPTS)

    PAIRS 검증 단계 추가:
    - pairs_service.compare_pair()로 엔트로피 계산
    - 엔트로피 > 0.6: 무승부 directive 주입
    - 엔트로피 ≤ 0.6: 승자 directive 주입
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

        # ===== Case A: 양측 모두 기권 (무승부 — 텍스트 부재) =====
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

        # ===== PAIRS 사전 판정 (양방향 위치 편향 보정) =====
        evaluation_directive = await self._determine_directive_via_pairs(
            user_a=user_a,
            user_b=user_b,
            criteria=criteria,
            a_short=a_short,
            b_short=b_short,
        )

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
            evaluation_directive=evaluation_directive,
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

    async def _determine_directive_via_pairs(
        self,
        user_a: dict,
        user_b: dict,
        criteria: dict,
        a_short: bool,
        b_short: bool,
    ) -> str:
        """
        PairsService를 이용한 양방향 위치 편향 보정 사전 판정.

        한쪽이 기권(short)인 경우에는 PAIRS 호출 없이 기권자를 패자로 처리합니다.
        정상 텍스트 쌍에 대해서는 pairs_service.compare_pair()를 호출하여
        엔트로피를 계산하고 무승부/승자를 결정합니다.

        Args:
            user_a: User A 데이터 (user_id, user_text)
            user_b: User B 데이터 (user_id, user_text)
            criteria: 채점 기준 (keyword, model_answer)
            a_short: User A 기권 여부
            b_short: User B 기권 여부

        Returns:
            LLM에게 주입할 evaluation_directive 문자열
        """
        # 한쪽 기권 시 PAIRS 생략 — 기권자는 자동 패
        if a_short and not b_short:
            logger.info(
                "[PAIRS-PvP] User A forfeited. Skipping PAIRS, B wins by default."
            )
            return _build_evaluation_directive(
                is_draw=False, winner_id=user_b["user_id"]
            )
        if b_short and not a_short:
            logger.info(
                "[PAIRS-PvP] User B forfeited. Skipping PAIRS, A wins by default."
            )
            return _build_evaluation_directive(
                is_draw=False, winner_id=user_a["user_id"]
            )

        # 정상 텍스트 쌍: pairs_service로 양방향 보정 판정
        try:
            # import는 순환 참조 방지를 위해 지연(lazy) import 사용
            from app.services.pairs_service import pairs_service

            item_a = {"text": user_a["user_text"]}
            item_b = {"text": user_b["user_text"]}
            criteria_str = criteria.get("model_answer", "")

            p_a, p_b, entropy = await pairs_service.compare_pair(
                item_a, item_b, criteria_str
            )
            logger.info(
                f"[PAIRS-PvP] p_A={p_a:.3f}, p_B={p_b:.3f}, entropy={entropy:.3f} "
                f"(threshold={ENTROPY_THRESHOLD})"
            )

            if entropy > ENTROPY_THRESHOLD:
                logger.info("[PAIRS-PvP] Entropy exceeded threshold → DRAW")
                return _build_evaluation_directive(is_draw=True)
            else:
                winner_id = user_a["user_id"] if p_a >= p_b else user_b["user_id"]
                logger.info(f"[PAIRS-PvP] Clear winner → user_id={winner_id}")
                return _build_evaluation_directive(is_draw=False, winner_id=winner_id)

        except Exception as e:
            # PAIRS 호출 실패 시 안전하게 무승부로 폴백 (LLM 계속 진행)
            logger.warning(
                f"[PAIRS-PvP] compare_pair failed ({e}). Falling back to DRAW directive."
            )
            return _build_evaluation_directive(is_draw=True)

    async def _call_gemini_with_retry(self, prompt: str):
        """Gemini API 호출. 재시도는 RabbitMQ retry에 위임합니다."""
        logger.info("Calling Gemini API for PvP feedback...")
        response = await asyncio.wait_for(
            self.model.generate_content_async(prompt),
            timeout=60.0,
        )
        return response


# 싱글톤 인스턴스
pvp_feedback_service = PvpFeedbackService()
