import asyncio
import logging
import time
from app.services.task_store import task_store
from app.services.scoring_service import scoring_service
from app.services.feedback_service import feedback_service
from app.core.metrics import record_analysis_task

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
        start_time = time.time()
        logger.info(f"Task {task_id}: Started analysis.")

        # Update status to PROCESSING
        task_store.save_task(task_id, "PROCESSING")
        record_analysis_task(status="PROCESSING")

        try:
            # 1. Validation Logic
            if len(user_text.strip()) < 5:
                # Skip LLM and return hardcoded feedback
                logger.info(
                    f"Task {task_id}: Text too short (< 5 chars). Returning hardcoded feedback."
                )

                final_result = {
                    "overall_score": 0,
                    "level": 1,
                    "feedback": {
                        "summarize": "입력된 내용이 너무 짧거나 인식이 되지 않았습니다.",
                        "keyword": ["음성 인식 실패", "짧은 답변"],
                        "facts": "분석할 텍스트가 부족합니다.",
                        "understanding": "사용자의 의도를 파악하기 어렵습니다.",
                        "personalized": "조금 더 길게 말씀해주시거나, 다시 시도 부탁드립니다.",
                    },
                }

                task_store.save_task(task_id, "COMPLETED", result=final_result)
                duration = time.time() - start_time
                record_analysis_task(status="COMPLETED", duration=duration)
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
                "overall_score": score_result["overall_score"],
                "level": score_result["level"],
                "feedback": feedback_result,
            }

            # 4. Save COMPLETED state
            task_store.save_task(task_id, "COMPLETED", result=final_result)
            duration = time.time() - start_time
            record_analysis_task(status="COMPLETED", duration=duration)
            logger.info(f"Task {task_id}: Completed successfully.")

        except Exception as e:
            logger.error(f"Task {task_id}: Failed with error {e}")
            # Map exception to error code if needed, generic for now
            task_store.save_task(
                task_id, "FAILED", error={"code": "INTERNAL_ERROR", "msg": str(e)}
            )
            duration = time.time() - start_time
            record_analysis_task(status="FAILED", duration=duration)


analysis_service = AnalysisService()
