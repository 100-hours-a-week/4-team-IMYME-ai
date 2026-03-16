import os
import math
import asyncio
import logging
from typing import List, Dict, Any, Tuple
from google import genai
from google.genai import types
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from app.core.config import settings

# Configure logging
logger = logging.getLogger("imyme-pairs-service")

# GCP settings - typically loaded from environment/config
# Init Vertex AI Client
try:
    client = genai.Client(
        vertexai=True, 
        project=settings.GCP_PROJECT, 
        location=settings.GCP_LOCATION
    )
except Exception as e:
    logger.warning(f"Failed to initialize Vertex AI client, fallback to standard GenAI might be needed: {e}")
    # Fallback to standard client if vertex isn't properly configured in the environment
    client = genai.Client()

RESPONSE_SCHEMA = {"type": "STRING", "enum": ["1", "2"]}

SYSTEM_PROMPT = """You are an expert technical evaluator. You will be given two answers to compare.
CRITICAL INSTRUCTION: You must respond with ONLY a single character: either "1" or "2".
Do NOT write any explanation, reasoning, or additional text.
Your entire response must be exactly one character."""

FALLBACK_LOGPROB = -100.0

class PairsService:
    def __init__(self, beam_size: int = 5, u_h: float = 0.6):
        """
        Initialize PAIRS Service with uncertainty guided pruning limits.
        :param beam_size: Maximum number of trajectories to keep during beam search.
        :param u_h: Uncertainty threshold. If $U(A, B) > U_h$, we branch.
        """
        self.beam_size = beam_size
        self.u_h = u_h
        # Semaphore as requested in "Proactive Warning" for Concurrency Throttling
        self.api_semaphore = asyncio.Semaphore(10)

    def _build_pairs_prompt(self, text_first: str, text_second: str) -> str:
        return f"""Which of the following two answers is better?

Answer 1:
{text_first}

Answer 2:
{text_second}

Respond with only "1" or "2". Nothing else."""

    # Exponential backoff via tenacity as per "Proactive Warning"
    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        reraise=True
    )
    async def _call_with_logprobs(self, prompt: str) -> dict:
        """
        Calls Gemini API asynchronously via asyncio.to_thread
        and extracts log probabilities for '1' and '2'.
        """
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.0,
            response_mime_type="text/x.enum",
            response_schema=RESPONSE_SCHEMA,
            response_logprobs=True,
            logprobs=5,
        )

        async with self.api_semaphore:
            # use to_thread because google.genai sdk might be synchronous for some calls
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=settings.PAIRS_MODEL_ID,
                contents=prompt,
                config=config,
            )

        logprobs_data = []
        if response.candidates and response.candidates[0].logprobs_result:
            logprobs_result = response.candidates[0].logprobs_result
            if logprobs_result.top_candidates:
                top = logprobs_result.top_candidates[0]
                for candidate in top.candidates:
                    logprobs_data.append({
                        "token": candidate.token,
                        "log_probability": candidate.log_probability
                    })

        return {
            "top_candidates": logprobs_data,
        }

    def _extract_choice_probabilities(self, api_result: dict) -> Tuple[float, float]:
        """Softmax normalization of logprobs. Returns (P(1), P(2))"""
        logprob_1 = FALLBACK_LOGPROB
        logprob_2 = FALLBACK_LOGPROB

        for candidate in api_result.get("top_candidates", []):
            token_stripped = candidate["token"].strip()
            if token_stripped == "1":
                logprob_1 = candidate["log_probability"]
            elif token_stripped == "2":
                logprob_2 = candidate["log_probability"]

        exp_1 = math.exp(logprob_1)
        exp_2 = math.exp(logprob_2)
        total = exp_1 + exp_2

        # Prevent division by zero if both are deeply negative
        if total == 0:
            return 0.5, 0.5

        return exp_1 / total, exp_2 / total

    def _compute_entropy(self, p_a: float, p_b: float) -> float:
        """Compute the information entropy U(A, B)."""
        eps = 1e-15
        p_a = max(eps, min(1 - eps, p_a))
        p_b = max(eps, min(1 - eps, p_b))
        return -(p_a * math.log(p_a) + p_b * math.log(p_b))

    async def compare_pair(self, item_a: dict, item_b: dict) -> Tuple[float, float, float]:
        """
        Phase 3: Calibration (위치 편향 제거)
        item_a, item_b = {"id": str, "text": str}
        Returns: P(A > B), P(B > A), Entropy U
        """
        text_a = item_a["text"]
        text_b = item_b["text"]

        # Prompt 1: A first, B second
        prompt_ab = self._build_pairs_prompt(text_a, text_b)
        res_ab = await self._call_with_logprobs(prompt_ab)
        p_1_ab, p_2_ab = self._extract_choice_probabilities(res_ab)
        p_A_in_prompt1 = p_1_ab

        # Prompt 2: B first, A second
        prompt_ba = self._build_pairs_prompt(text_b, text_a)
        res_ba = await self._call_with_logprobs(prompt_ba)
        p_1_ba, p_2_ba = self._extract_choice_probabilities(res_ba)
        # B is first(1), A is second(2)
        p_A_in_prompt2 = p_2_ba

        # Calibrated Average
        p_calibrated_A = (p_A_in_prompt1 + p_A_in_prompt2) / 2.0
        p_calibrated_B = 1.0 - p_calibrated_A

        # Entropy calculation based on calibrated probabilities
        entropy = self._compute_entropy(p_calibrated_A, p_calibrated_B)

        return p_calibrated_A, p_calibrated_B, entropy

    # === Phase 4: PAIRS-beam Merge Sort Logics ===
    
    async def merge_beam(self, sub_arr1: List[dict], sub_arr2: List[dict]) -> List[dict]:
        """
        Merges two sorted subarrays using Uncertainty-Guided PAIRS-beam algorithm.
        This represents Algorithm 1 from the paper.
        Returns the single most likely merged list.
        """
        # A trajectory is a Tuple: (merged_list, pointer1, pointer2, likelihood)
        initial_trajectory = ([], 0, 0, 1.0)
        beam: List[Tuple[List[dict], int, int, float]] = [initial_trajectory]

        len1 = len(sub_arr1)
        len2 = len(sub_arr2)
        
        # We continue until all elements are merged
        # In a real beam search, the loop condition is slightly tricky when tracking index pointers
        # For simplicity, we loop until the best candidate is fully merged.
        while True:
            new_beam = []
            
            # If the top trajectory is done, we can just return it.
            # Sort beam by likelihood (descending)
            beam.sort(key=lambda x: x[3], reverse=True)
            
            # Check if best is done
            best_list, p1, p2, best_L = beam[0]
            if p1 == len1 and p2 == len2:
                return best_list

            # Expand each trajectory in the current beam
            for merged_list, ptr1, ptr2, current_L in beam:
                # If one array is fully consumed, automatically append the rest from the other
                if ptr1 == len1:
                    new_merged = list(merged_list) + sub_arr2[ptr2:]
                    new_beam.append((new_merged, len1, len2, current_L))
                    continue
                if ptr2 == len2:
                    new_merged = list(merged_list) + sub_arr1[ptr1:]
                    new_beam.append((new_merged, len1, len2, current_L))
                    continue

                # Both have elements left, need to compare
                item_a = sub_arr1[ptr1]
                item_b = sub_arr2[ptr2]
                
                # Fetch comparison results
                p_a, p_b, entropy = await self.compare_pair(item_a, item_b)

                # Core Branching Logic (Algorithm 1: lines 10-17)
                if entropy > self.u_h:
                    # Branch 1: High uncertainty -> Fork
                    new_l_a = list(merged_list) + [item_a]
                    new_beam.append((new_l_a, ptr1 + 1, ptr2, current_L * p_a))
                    
                    new_l_b = list(merged_list) + [item_b]
                    new_beam.append((new_l_b, ptr1, ptr2 + 1, current_L * p_b))
                
                elif p_a >= 0.5:
                    # Branch 2: Definite win for A -> Prune B route
                    new_l_a = list(merged_list) + [item_a]
                    new_beam.append((new_l_a, ptr1 + 1, ptr2, current_L * p_a))
                
                else:
                    # Branch 3: Definite win for B -> Prune A route
                    new_l_b = list(merged_list) + [item_b]
                    new_beam.append((new_l_b, ptr1, ptr2 + 1, current_L * p_b))

            # Maintain beam size
            new_beam.sort(key=lambda x: x[3], reverse=True)
            beam = new_beam[:self.beam_size]

pairs_service = PairsService()
