import random
import json
from app.core.prompts import BASE_SYSTEM_PROMPT, PERSONA_PROMPTS
import logging

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Manages the selection and construction of System Prompts using Strategy Pattern.
    """

    def __init__(self):
        self.personas = list(PERSONA_PROMPTS.keys())

    def get_system_prompt(
        self, criteria: dict, user_text: str, history: list, persona: str = None
    ) -> str:
        """
        Constructs the final system prompt by combining Base + Persona Strategy.
        """
        # 1. Select Persona
        if not persona or persona not in PERSONA_PROMPTS:
            persona = random.choice(self.personas)

        logger.info(f"Selected Persona: {persona}")

        # 2. Get Instructions
        persona_instruction = PERSONA_PROMPTS[persona]

        # 3. Format Data
        history_str = (
            json.dumps(history, ensure_ascii=False, indent=2) if history else "None"
        )
        criteria_str = json.dumps(criteria, ensure_ascii=False, indent=2)

        # 4. Combine and Format
        # We append persona instruction to the base role definition
        # Note: BASE_SYSTEM_PROMPT has placeholders.

        full_instruction = f"""
        {BASE_SYSTEM_PROMPT}

        [Your Current Persona Strategy]
        {persona_instruction}
        """

        # 5. Inject Data
        final_prompt = full_instruction.format(
            criteria=criteria_str, user_text=user_text, history=history_str
        )

        return final_prompt

    def get_available_personas(self):
        return self.personas


prompt_manager = PromptManager()
