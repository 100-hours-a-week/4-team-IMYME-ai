import google.generativeai as genai
from app.core.config import settings
import json
import logging

logger = logging.getLogger(__name__)


class ScoringService:
    """
    Evaluates user text to produce quantitative metrics (Score, Level).
    """

    def __init__(self):
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel("gemini-3-pro-preview")
        else:
            logger.warning("GEMINI_API_KEY is not set. ScoringService will fail.")

    async def evaluate(self, user_text: str, criteria: dict) -> dict:
        """
        Evaluates the text and returns {"score": int, "level": str}
        """
        try:
            prompt = self._build_prompt(user_text, criteria)
            response = await self.model.generate_content_async(prompt)

            # Simple cleanup for JSON parsing (remove markdown code blocks if present)
            cleaned_text = (
                response.text.replace("```json", "").replace("```", "").strip()
            )
            result = json.loads(cleaned_text)

            return {"score": result.get("score", 0), "level": result.get("level", "C")}
        except Exception as e:
            logger.error(f"Scoring failed: {e}")
            # Return a fallback or re-raise depending on policy.
            # For now, return default to allow flow to continue (or can raise to fail task)
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
            "score": <0-100 integer>,
            "level": <"S", "A", "B", "C">
        }}
        """


scoring_service = ScoringService()
