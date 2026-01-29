from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.v1.router import api_router
from app.core.config import settings
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whoo-ai-server")

# Initialize FastAPI app
# FastAPI 앱 초기화
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    root_path=settings.ROOT_PATH,
)


@app.middleware("http")
async def verify_internal_secret(request: Request, call_next):
    # 1. Skip checks for Health Check or Docs
    # 헬스 체크나 문서는 통과
    # Also skip ROOT_PATH if it exists in request (Reverse Proxy handling)
    path = request.url.path
    if settings.ROOT_PATH and path.startswith(settings.ROOT_PATH):
        path = path[len(settings.ROOT_PATH) :]

    if path in [
        "/health",
        "/docs",
        "/openapi.json",
        "/",
        settings.API_V1_STR + "/openapi.json",
    ]:
        return await call_next(request)

    # 2. Check Header
    # 헤더 검사
    if not settings.INTERNAL_SECRET_KEY:
        # If no secret set in env, allow all (or block all? user didn't specify, assuming allow for dev convenience or block for safety)
        # Let's perform check only if key is set.
        pass
    elif request.headers.get("x-internal-secret") != settings.INTERNAL_SECRET_KEY:
        return JSONResponse(
            status_code=403,
            content={"detail": "Access Denied: Invalid Internal Secret"},
        )

    response = await call_next(request)
    return response


# Include API routers
# API 라우터 포함
app.include_router(api_router, prefix=settings.API_V1_STR)


# Root endpoint for health check
# 헬스 체크를 위한 루트 엔드포인트
@app.get("/")
def root():
    return {"status": "ok", "service": settings.PROJECT_NAME}


@app.get("/health")
def health_check():
    """
    Load Balancer Health Check
    """
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    # Run the server using uvicorn
    # uvicorn을 사용하여 서버 실행
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
