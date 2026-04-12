"""
PAIRS Algorithm Service (Phase 2: 설계.md 기반 리팩토링)

지식베이스(Criteria)를 기반으로 두 답변을 비교하여
Logprob + 위치 편향 보정 + Uncertainty-Guided Beam Search 를 수행합니다.
"""

import math
import asyncio
import json
import logging
from typing import List, Tuple, Optional
from google import genai
from google.genai import types
from google.oauth2 import service_account
from tenacity import retry, wait_exponential, stop_after_attempt

from app.core.config import settings
from app.core.prompts import CHALLENGE_PAIRS_SYSTEM_PROMPT, CHALLENGE_PAIRS_USER_PROMPT

logger = logging.getLogger("imyme-pairs-service")

# ── Vertex AI Client 초기화 (Parameter Store JSON 직접 읽기) ──
try:
    gcp_json_str = settings.GCP_SA_JSON_STR
    if gcp_json_str:
        sa_info = json.loads(gcp_json_str)
        credentials = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        client = genai.Client(
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_LOCATION,
            credentials=credentials,
        )
        logger.info(
            "Successfully initialized Vertex AI client using Service Account JSON String."
        )
    else:
        logger.info("GCP_SA_JSON_STR not found. Falling back to default ADC.")
        client = genai.Client(
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_LOCATION,
        )
except Exception as e:
    logger.error(f"Failed to initialize Vertex AI client: {e}")
    client = genai.Client()

RESPONSE_SCHEMA = {"type": "STRING", "enum": ["1", "2"]}
FALLBACK_LOGPROB = -100.0


class PairsService:
    def __init__(self, beam_size: int = 5, u_h: float = 0.6):
        self.beam_size = beam_size
        self.u_h = u_h
        # Rate Limit(429) 보호를 위해 동시성 제한을 매우 타이트하게(2) 조입니다.
        self.api_semaphore = asyncio.Semaphore(2)

    # User prompt
    def _build_pairs_prompt(
        self, text_first: str, text_second: str, criteria: Optional[str] = None
    ) -> str:
        """criteria가 있으면 지식 기반 비교 프롬프트, 없으면 단순 비교 프롬프트를 사용합니다."""
        if criteria:
            return CHALLENGE_PAIRS_USER_PROMPT.format(
                criteria=criteria, text_first=text_first, text_second=text_second
            )
        return f"""Which of the following two answers is better?

                    Answer 1:
                    {text_first}

                    Answer 2:
                    {text_second}

                    Respond with only "1" or "2". Nothing else."""

    # System instruction
    def _get_system_prompt(self, criteria: Optional[str] = None) -> str:
        if criteria:
            return CHALLENGE_PAIRS_SYSTEM_PROMPT
        return (
            "You are an expert technical evaluator. "
            "Respond with ONLY '1' or '2'. No explanation."
        )

    @retry(
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(10),
        reraise=True,
    )
    async def _call_with_logprobs(self, prompt: str, system_prompt: str) -> dict:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.0,
            response_mime_type="text/x.enum",
            response_schema=RESPONSE_SCHEMA,
            response_logprobs=True,
            logprobs=5,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        async with self.api_semaphore:
            # Rate Limit 방어: 최소 1초 대기하여 동시다발적 호출을 인위적으로 지연시킵니다.
            await asyncio.sleep(1.0)
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=settings.PAIRS_MODEL_ID,
                    contents=prompt,
                    config=config,
                ),
                timeout=60.0,
            )

        logprobs_data = []
        if response.candidates and response.candidates[0].logprobs_result:
            logprobs_result = response.candidates[0].logprobs_result
            if logprobs_result.top_candidates:
                top = logprobs_result.top_candidates[0]
                for candidate in top.candidates:
                    logprobs_data.append(
                        {
                            "token": candidate.token,
                            "log_probability": candidate.log_probability,
                        }
                    )

        return {"top_candidates": logprobs_data}

    def _extract_choice_probabilities(self, api_result: dict) -> Tuple[float, float]:
        logprob_1 = FALLBACK_LOGPROB
        logprob_2 = FALLBACK_LOGPROB

        for c in api_result.get("top_candidates", []):
            t = c["token"].strip()
            if t == "1":
                logprob_1 = c["log_probability"]
            elif t == "2":
                logprob_2 = c["log_probability"]

        exp_1 = math.exp(logprob_1)
        exp_2 = math.exp(logprob_2)
        total = exp_1 + exp_2
        if total == 0:
            return 0.5, 0.5
        return exp_1 / total, exp_2 / total

    def _compute_entropy(self, p_a: float, p_b: float) -> float:
        eps = 1e-15
        p_a = max(eps, min(1 - eps, p_a))
        p_b = max(eps, min(1 - eps, p_b))
        return -(p_a * math.log(p_a) + p_b * math.log(p_b))

    async def compare_pair(
        self, item_a: dict, item_b: dict, criteria: Optional[str] = None
    ) -> Tuple[float, float, float]:
        """위치 편향 보정된 쌍방향 비교. criteria가 있으면 지식 기반 비교."""
        text_a = item_a["text"]
        text_b = item_b["text"]

        # ── 짧은 텍스트 / 무발화 즉시 패배 처리 (LLM 호출 없이 기권 패널티 적용) ──
        MIN_TEXT_LENGTH = 5
        NO_ANSWER_MARKER = "[NO_ANSWER]"
        a_short = (
            len(text_a.strip()) < MIN_TEXT_LENGTH or text_a.strip() == NO_ANSWER_MARKER
        )
        b_short = (
            len(text_b.strip()) < MIN_TEXT_LENGTH or text_b.strip() == NO_ANSWER_MARKER
        )

        if a_short and b_short:
            # 둘 다 짧음: A 승리 (임의 타이브레이크)
            logger.info(
                f"⏭️ Both texts too short for PAIRS compare (A={len(text_a.strip())}, B={len(text_b.strip())} chars). A wins by tiebreak."
            )
            return 1.0, 0.0, 0.0
        if a_short:
            # A만 짧음: B 무조건 승리
            logger.info(
                f"⏭️ Text A too short ({len(text_a.strip())} chars). B wins by forfeit in PAIRS."
            )
            return 0.0, 1.0, 0.0
        if b_short:
            # B만 짧음: A 무조건 승리
            logger.info(
                f"⏭️ Text B too short ({len(text_b.strip())} chars). A wins by forfeit in PAIRS."
            )
            return 1.0, 0.0, 0.0

        sys_prompt = self._get_system_prompt(criteria)

        # Prompt 1: A first, B second
        prompt_ab = self._build_pairs_prompt(text_a, text_b, criteria)
        res_ab = await self._call_with_logprobs(prompt_ab, sys_prompt)
        p_1_ab, _ = self._extract_choice_probabilities(res_ab)
        p_A_in_prompt1 = p_1_ab

        # Prompt 2: B first, A second (위치 교환)
        prompt_ba = self._build_pairs_prompt(text_b, text_a, criteria)
        res_ba = await self._call_with_logprobs(prompt_ba, sys_prompt)
        _, p_2_ba = self._extract_choice_probabilities(res_ba)
        p_A_in_prompt2 = p_2_ba

        # Calibrated average
        p_calibrated_A = (p_A_in_prompt1 + p_A_in_prompt2) / 2.0
        p_calibrated_B = 1.0 - p_calibrated_A
        entropy = self._compute_entropy(p_calibrated_A, p_calibrated_B)

        return p_calibrated_A, p_calibrated_B, entropy

    async def merge_beam(
        self, sub_arr1: List[dict], sub_arr2: List[dict], criteria: Optional[str] = None
    ) -> List[dict]:
        """Uncertainty-Guided PAIRS-beam 병합 정렬. criteria가 있으면 지식 기반 비교."""
        initial_trajectory = ([], 0, 0, 1.0)
        beam: List[Tuple] = [initial_trajectory]
        len1, len2 = len(sub_arr1), len(sub_arr2)

        while True:
            beam.sort(key=lambda x: x[3], reverse=True)
            best_list, p1, p2, best_L = beam[0]
            if p1 == len1 and p2 == len2:
                return best_list

            new_beam = []
            for merged_list, ptr1, ptr2, current_L in beam:
                if ptr1 == len1:
                    new_beam.append(
                        (list(merged_list) + sub_arr2[ptr2:], len1, len2, current_L)
                    )
                    continue
                if ptr2 == len2:
                    new_beam.append(
                        (list(merged_list) + sub_arr1[ptr1:], len1, len2, current_L)
                    )
                    continue

                item_a = sub_arr1[ptr1]
                item_b = sub_arr2[ptr2]
                p_a, p_b, entropy = await self.compare_pair(item_a, item_b, criteria)

                if entropy > self.u_h:
                    new_beam.append(
                        (list(merged_list) + [item_a], ptr1 + 1, ptr2, current_L * p_a)
                    )
                    new_beam.append(
                        (list(merged_list) + [item_b], ptr1, ptr2 + 1, current_L * p_b)
                    )
                elif p_a >= 0.5:
                    new_beam.append(
                        (list(merged_list) + [item_a], ptr1 + 1, ptr2, current_L * p_a)
                    )
                else:
                    new_beam.append(
                        (list(merged_list) + [item_b], ptr1, ptr2 + 1, current_L * p_b)
                    )

            new_beam.sort(key=lambda x: x[3], reverse=True)
            beam = new_beam[: self.beam_size]


pairs_service = PairsService(beam_size=3)
