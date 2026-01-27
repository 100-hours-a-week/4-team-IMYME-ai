from fastapi import APIRouter
import logging
from app.schemas.knowledge import *
from app.services.knowledge_service import knowledge_service

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
        # 400 EMPTY_BATCH_DATA
        return RefineCandidatesResponse(
            success=False,
            data=RefineCandidatesResponseData(processedCount=0, candidates=[]),
            error={"code": "EMPTY_BATCH_DATA", "msg": "Input items list is empty."},
        )

    try:
        data = await knowledge_service.refine_candidates_batch(request.items)
        return RefineCandidatesResponse(success=True, data=data, error=None)
    except Exception as e:
        logger.error(f"Refine Batch Error: {e}")
        # 500 EMBEDDING_FAILURE or LLM_FAILURE
        return RefineCandidatesResponse(
            success=False,
            data=RefineCandidatesResponseData(processedCount=0, candidates=[]),
            error={"code": "INTERNAL_ERROR", "msg": str(e)},
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
            # Return empty/default result wrapper to satisfy schema if needed, but Pydantic expects data.
            # However, schema says data is required. Let's create dummy fail data.
            data=KnowledgeEvaluationResult(
                decision=KnowledgeAction.IGNORE, reasoning="Validation Failed"
            ),
            error={"code": "TEXT_TOO_LONG", "msg": "Candidate text exceeds limit."},
        )

    try:
        result = await knowledge_service.evaluate_knowledge(
            request.candidate, request.similars
        )
        return KnowledgeEvaluationResponse(success=True, data=result, error=None)
    except ValueError as ve:
        # Invalid LLM Response
        return KnowledgeEvaluationResponse(
            success=False,
            data=KnowledgeEvaluationResult(
                decision=KnowledgeAction.IGNORE, reasoning="LLM Error"
            ),
            error={"code": "INVALID_LLM_RESPONSE", "msg": str(ve)},
        )
    except Exception as e:
        logger.error(f"Evaluation Error: {e}")
        return KnowledgeEvaluationResponse(
            success=False,
            data=KnowledgeEvaluationResult(
                decision=KnowledgeAction.IGNORE, reasoning="Internal Error"
            ),
            error={"code": "INTERNAL_ERROR", "msg": str(e)},
        )
