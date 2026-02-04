import google.generativeai as genai
from app.core.config import settings
import json
import logging
from typing import List, Dict, Any
from app.services.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


class FeedbackService:
    """
    Generates qualitative feedback (Summary, Keywords, Advice).
    """

    def __init__(self):
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel("gemini-3-flash-preview")

    async def generate_feedback(
        self, user_text: str, criteria: dict, history: List[Dict[str, Any]]
    ) -> dict:
        """
        Returns { "summarize": str, "keyword": [], "personalized": str }
        """

        try:
            # Generate Dynamic Prompt via Manager
            prompt = prompt_manager.get_system_prompt(
                criteria=criteria, user_text=user_text, history=history
            )

            response = await self.model.generate_content_async(prompt)

            cleaned_text = (
                response.text.replace("```json", "").replace("```", "").strip()
            )
            return json.loads(cleaned_text)

        except Exception as e:
            logger.error(f"Feedback generation failed: {e}")
            raise e


feedback_service = FeedbackService()
