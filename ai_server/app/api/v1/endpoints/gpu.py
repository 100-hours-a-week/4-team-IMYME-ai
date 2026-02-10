from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.runpod_client import runpod_client
from app.core.errors import ErrorCode
from app.schemas.common import create_error_response, create_success_response

router = APIRouter()


# POST endpoint for triggering GPU warmup
# GPU 워밍업을 트리거하기 위한 POST 엔드포인트
@router.post("/warmup", status_code=202)
async def trigger_warmup():
    """
    Trigger GPU warmup asynchronously (SYS-001).
    Returns immediately with success status.
    """
    result = runpod_client.warmup_async()

    if result["status"] == "failed":
        return JSONResponse(
            status_code=500,
            content=create_error_response(
                code=ErrorCode.GPU_FAIL,
                message="GPU 워밍업에 실패했습니다.",
                detail={"raw_error": result.get("error")},
            ),
        )

    return create_success_response(data={"status": "WARMING_UP"})
