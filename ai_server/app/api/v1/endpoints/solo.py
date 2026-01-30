from fastapi import APIRouter, BackgroundTasks, Path
from fastapi.responses import JSONResponse
from app.schemas.solo import (
    SoloSubmissionRequest,
    SoloSubmissionResponse,
    SoloResultResponse,
    SoloSubmissionData,
    SoloResultData,
)
from app.services.task_service import task_service
from app.services.analysis_service import analysis_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/submissions", response_model=SoloSubmissionResponse, status_code=202)
async def submit_analysis(
    request: SoloSubmissionRequest, background_tasks: BackgroundTasks
):
    """
    [SOLO-001] 심층 분석 요청
    - 텍스트와 문맥 데이터를 받아 분석 작업을 큐(배경 작업)에 등록합니다.
    - 즉시 202 Accepted와 함께 taskId를 반환합니다.
    """
    try:
        # 1. Create Task (PENDING) using client-provided attemptId
        attempt_id = task_service.create_task(request.attempt_id)

        # 2. Register Background Task
        # AnalysisService orchestrates Scoring and Feedback in parallel
        background_tasks.add_task(
            analysis_service.analyze_text_background,
            task_id=str(attempt_id),
            user_text=request.user_text,
            criteria=request.criteria,
            history=request.history,
        )

        return SoloSubmissionResponse(
            success=True,
            data=SoloSubmissionData(attemptId=attempt_id, status="PENDING"),
            error=None,
        )

    except Exception as e:
        logger.error(f"Submission failed: {e}")
        # 400 or 500 depending on error, but typically Pydantic catches 400.
        # Unknown error is 500.
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "data": None,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "msg": "Internal Server Error during submission",
                },
            },
        )


@router.get("/submissions/{attemptId}", response_model=SoloResultResponse)
async def get_analysis_result(attempt_id: int = Path(..., alias="attemptId", description="시도 ID")):
    """
    [SOLO-002] 분석 결과 조회 (Polling)
    - attemptId를 통해 현재 작업 상태나 완료된 결과를 조회합니다.
    """
    task_data = task_service.get_task_status(attempt_id)

    # To match strictly:
    if not task_data:
        # Return 200/404 with Custom Error Body matching SoloResultResponse
        # User Spec: HTTP 404 & Error Code TASK_NOT_FOUND
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "data": None,
                "error": {
                    "code": "TASK_NOT_FOUND",
                    "msg": "존재하지 않거나 만료된 작업입니다.",
                },
            },
        )

    # Map TaskStore dict to Response Schema
    # data structure in store: { "taskId":..., "status":..., "result":..., "error":... }

    # If internal error (FAILED status)
    if task_data.get("status") == "FAILED":
        return SoloResultResponse(
            success=False,
            data=SoloResultData(
                attemptId=attempt_id, status="FAILED", result=None
            ),
            error=task_data.get("error"),  # {"code":..., "msg":...}
        )

    # If Success (COMPLETED) or Processing
    return SoloResultResponse(
        success=True,
        data=SoloResultData(
            attemptId=attempt_id,
            status=task_data["status"],
            result=task_data.get("result"),  # None if PROCESSING
        ),
        error=None,
    )
