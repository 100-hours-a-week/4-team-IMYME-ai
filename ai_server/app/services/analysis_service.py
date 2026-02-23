import asyncio
import logging
from app.services.task_store import task_store
from app.services.scoring_service import scoring_service
from app.services.feedback_service import feedback_service
from app.core.errors import ErrorCode

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
            if not criteria:
                task_store.save_task(
                    task_id,
                    "FAILED",
                    error={
                        "code": ErrorCode.INVALID_CRITERIA.value,
                        "message": "분석 기준(Criteria)이 누락되었습니다.",
                    },
                )
                return

            if len(user_text.strip()) < 5:
                # Skip LLM and return hardcoded feedback (Business Logic: Not an error, just low score)
                # If strict error is needed, we could use ErrorCode.TEXT_TOO_SHORT here.
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
            logger.info(f"Task {task_id}: Completed successfully.")

        except Exception as e:
            logger.error(f"Task {task_id}: Failed with error {e}")

            error_msg = str(e).lower()
            code = ErrorCode.INTERNAL_ERROR

            if "llm" in error_msg or "gemini" in error_msg or "500" in error_msg:
                code = ErrorCode.LLM_PROVIDER_ERROR
            elif "embedding" in error_msg or "vector" in error_msg:
                code = ErrorCode.EMBEDDING_FAILURE

            task_store.save_task(
                task_id,
                "FAILED",
                error={
                    "code": code.value,
                    "message": f"분석 처리 중 오류가 발생했습니다. ({code.value})",
                },
            )


analysis_service = AnalysisService()
