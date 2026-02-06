import google.generativeai as genai
from app.core.config import settings
from app.core.metrics import record_llm_request, record_evaluation_result
import json
import logging
import time

logger = logging.getLogger(__name__)


class ScoringService:
    """
    Evaluates user text to produce quantitative metrics (Score, Level).
    """

    def __init__(self):
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel("gemini-3-flash-preview")
        else:
            logger.warning("GEMINI_API_KEY is not set. ScoringService will fail.")

    async def evaluate(self, user_text: str, criteria: dict) -> dict:
        """
        Evaluates the text and returns {"score": int, "level": str}
        """
        start_time = time.time()

        try:
            prompt = self._build_prompt(user_text, criteria)
            response = await self.model.generate_content_async(prompt)

            # Simple cleanup for JSON parsing (remove markdown code blocks if present)
            cleaned_text = (
                response.text.replace("```json", "").replace("```", "").strip()
            )
            result = json.loads(cleaned_text)

            overall_score = result.get("overall_score", 0)
            level = result.get("level", 1)

            # Record successful LLM request and evaluation metrics
            duration = time.time() - start_time
            record_llm_request(
                service="scoring",
                model="gemini-3-flash",
                status="success",
                duration=duration,
            )
            record_evaluation_result(overall_score=overall_score, level=level)

            return {
                "overall_score": overall_score,
                "level": level,
            }
        except Exception as e:
            logger.error(f"Scoring failed: {e}")
            # Record failed LLM request
            duration = time.time() - start_time
            record_llm_request(
                service="scoring",
                model="gemini-3-flash",
                status="failed",
                duration=duration,
            )
            raise e

    def _build_prompt(self, user_text: str, criteria: dict) -> str:
        return f"""
        You are an expert language evaluator.
        Please evaluate the following user text based on the provided criteria.
        
        [Criteria]
        {json.dumps(criteria, ensure_ascii=False, indent=2)}

        [User Text]
        {user_text}

        [Output Format]
        Return purely JSON without any markdown formatting.
        {{
            "overall_score": <0-100 integer>,
            "level": <1-5 integer>
        }}
        """


scoring_service = ScoringService()
