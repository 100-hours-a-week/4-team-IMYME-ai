from fastapi import APIRouter
import logging
from app.schemas.knowledge import (
    RefineCandidatesRequest,
    RefineCandidatesResponse,
    RefineCandidatesResponseData,
    KnowledgeEvaluationRequest,
    KnowledgeEvaluationResponse,
    KnowledgeEvaluationResult,
    KnowledgeAction,
)
from app.services.knowledge_service import knowledge_service
from app.core.errors import ErrorCode, AppException

router = APIRouter()
logger = logging.getLogger(__name__)


# 7.1. Batch Refine Candidates
@router.post("/candidates/batch", response_model=RefineCandidatesResponse)
async def refine_candidates_batch(request: RefineCandidatesRequest):
    """
    [Batch] Raw Feedback -> Knowledge Candidate & Vector

    - input: List[RawFeedbackItem]
    - output: List[KnowledgeCandidate] with Embeddings
    """
    if not request.items:
        return RefineCandidatesResponse(
            success=False,
            data=RefineCandidatesResponseData(processedCount=0, candidates=[]),
            error={
                "code": ErrorCode.EMPTY_BATCH_DATA.value,
                "message": "입력 데이터가 비어있습니다.",
            },
        )

    try:
        data = await knowledge_service.refine_candidates_batch(request.items)
        return RefineCandidatesResponse(success=True, data=data, error=None)
    except AppException as e:
        logger.error(f"Refine Batch Error: {e.code} - {e.message}")
        return RefineCandidatesResponse(
            success=False,
            data=RefineCandidatesResponseData(processedCount=0, candidates=[]),
            error={"code": e.code.value, "message": e.message},
        )
    except Exception as e:
        logger.error(f"Refine Batch Unexpected Error: {e}")
        return RefineCandidatesResponse(
            success=False,
            data=RefineCandidatesResponseData(processedCount=0, candidates=[]),
            error={
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "배치 처리 중 예상치 못한 오류가 발생했습니다.",
            },
        )


# 7.2. Evaluate Knowledge
@router.post("/evaluations", response_model=KnowledgeEvaluationResponse)
async def evaluate_knowledge(request: KnowledgeEvaluationRequest):
    """
    [Single] Evaluate Candidate vs Similars

    - input: Candidate + Similars(Top-k)
    - output: Decision(UPDATE/IGNORE) + FinalContent + FinalVector
    """

    # Validation logic could be here (e.g. TEXT_TOO_LONG)
    if len(request.candidate.text) > 5000:
        return KnowledgeEvaluationResponse(
            success=False,
            data=KnowledgeEvaluationResult(
                decision=KnowledgeAction.IGNORE, reasoning="Validation Failed"
            ),
            error={
                "code": ErrorCode.TEXT_TOO_LONG.value,
                "message": "텍스트 길이가 제한을 초과했습니다.",
            },
        )

    try:
        result = await knowledge_service.evaluate_knowledge(
            request.candidate, request.similars
        )
        return KnowledgeEvaluationResponse(success=True, data=result, error=None)
    except AppException as e:
        logger.error(f"Evaluation Error: {e.code} - {e.message}")
        return KnowledgeEvaluationResponse(
            success=False,
            data=KnowledgeEvaluationResult(
                decision=KnowledgeAction.IGNORE, reasoning=str(e.code)
            ),
            error={"code": e.code.value, "message": e.message},
        )
    except Exception as e:
        logger.error(f"Evaluation Unexpected Error: {e}")
        return KnowledgeEvaluationResponse(
            success=False,
            data=KnowledgeEvaluationResult(
                decision=KnowledgeAction.IGNORE, reasoning="Internal Error"
            ),
            error={
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "평가 처리 중 예상치 못한 오류가 발생했습니다.",
            },
        )
