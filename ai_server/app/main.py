from fastapi import FastAPI, Request, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.metrics import (
    http_request_duration_seconds,
    record_http_request,
    service_info,
)
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("imyme-ai-server")

# Swagger Auth
api_key_header = APIKeyHeader(name="x-internal-secret", auto_error=False)

# Initialize FastAPI app
# FastAPI 앱 초기화
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    root_path=settings.ROOT_PATH,
    dependencies=[Security(api_key_header)],  # Add Global Security
)

# Set service info for Prometheus
# 프로메테우스용 서비스 정보 설정
service_info.info(
    {
        "service": settings.PROJECT_NAME,
        "version": "1.0.0",
    }
)


@app.middleware("http")
async def verify_internal_secret(request: Request, call_next):
    # Start timer for request duration
    start_time = time.time()

    # 1. Skip checks for Health Check or Docs
    # 헬스 체크나 문서는 통과
    # Also skip ROOT_PATH if it exists in request (Reverse Proxy handling)
    path = request.url.path
    if settings.ROOT_PATH and path.startswith(settings.ROOT_PATH):
        path = path[len(settings.ROOT_PATH) :]

    # Skip metrics endpoint from auth
    if path in [
        "/health",
        "/docs",
        "/openapi.json",
        "/",
        "/metrics",
        settings.API_V1_STR + "/openapi.json",
    ]:
        response = await call_next(request)
        # Record metrics
        duration = time.time() - start_time
        http_request_duration_seconds.labels(
            method=request.method, endpoint=path
        ).observe(duration)
        record_http_request(request.method, path, response.status_code)
        return response

    # 2. Check Header
    # 헤더 검사
    if not settings.INTERNAL_SECRET_KEY:
        # If no secret set in env, allow all (or block all? user didn't specify, assuming allow for dev convenience or block for safety)
        # Let's perform check only if key is set.
        pass
    elif request.headers.get("x-internal-secret") != settings.INTERNAL_SECRET_KEY:
        response = JSONResponse(
            status_code=403,
            content={"detail": "Access Denied: Invalid Internal Secret"},
        )
        # Record metrics for auth failure
        duration = time.time() - start_time
        record_http_request(request.method, path, 403)
        return response

    response = await call_next(request)

    # Record metrics for all requests
    duration = time.time() - start_time
    http_request_duration_seconds.labels(
        method=request.method, endpoint=path
    ).observe(duration)
    record_http_request(request.method, path, response.status_code)

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


@app.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint
    프로메테우스 메트릭 엔드포인트
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    # Run the server using uvicorn
    # uvicorn을 사용하여 서버 실행
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
