from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.runpod_client import runpod_client

router = APIRouter()


# POST endpoint for triggering GPU warmup
# GPU 워밍업을 트리거하기 위한 POST 엔드포인트
@router.post("/warmup")
async def trigger_warmup():
    """
    Trigger GPU warmup asynchronously (SYS-001).
    Returns immediately with success status.
    """
    result = runpod_client.warmup_async()

    if result["status"] == "failed":
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "data": None,
                "error": f"WARMUP_FAILED: {result.get('error')}",
            },
        )

    return {"success": True, "data": {"status": "WARMING_UP"}, "error": None}
