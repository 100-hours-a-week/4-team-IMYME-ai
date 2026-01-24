import asyncio
import logging
from app.services.task_store import task_store
from app.services.scoring_service import scoring_service
from app.services.feedback_service import feedback_service

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    Orchestrates the analysis process:
    1. Validates Input
    2. Calls Scoring & Feedback services (Parallel)
    3. Updates TaskStore
    """

    async def analyze_text_background(
        self, task_id: str, user_text: str, criteria: dict, history: list
    ):
        """
        Background task entry point.
        """
        logger.info(f"Task {task_id}: Started analysis.")

        # Update status to PROCESSING
        task_store.save_task(task_id, "PROCESSING")

        try:
            # 1. Validation Logic
            if len(user_text.strip()) < 5:
                # Logic Failure: TEXT_TOO_SHORT
                logger.warning(f"Task {task_id}: Text too short.")
                task_store.save_task(
                    task_id,
                    "FAILED",
                    error={
                        "code": "TEXT_TOO_SHORT",
                        "msg": "내용이 너무 짧아 분석할 수 없습니다.",
                    },
                )
                return

            # 2. Parallel Execution (Scoring + Feedback)
            score_task = scoring_service.evaluate(user_text, criteria)
            feedback_task = feedback_service.generate_feedback(
                user_text, criteria, history
            )

            # Wait for both
            score_result, feedback_result = await asyncio.gather(
                score_task, feedback_task
            )

            # 3. Aggregate Results
            final_result = {
                "score": score_result["score"],
                "level": score_result["level"],
                "feedback": feedback_result,
            }

            # 4. Save COMPLETED state
            task_store.save_task(task_id, "COMPLETED", result=final_result)
            logger.info(f"Task {task_id}: Completed successfully.")

        except Exception as e:
            logger.error(f"Task {task_id}: Failed with error {e}")
            # Map exception to error code if needed, generic for now
            task_store.save_task(
                task_id, "FAILED", error={"code": "INTERNAL_ERROR", "msg": str(e)}
            )


analysis_service = AnalysisService()
