from fastapi import FastAPI, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exception_handlers import add_exception_handlers
from app.core.errors import ErrorCode
from app.schemas.common import create_error_response
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("imyme-ai-server")

# Swagger Auth
api_key_header = APIKeyHeader(name="x-internal-secret", auto_error=False)


# Lifespan: RabbitMQ 워커를 앱 시작/종료 시 관리
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan Context Manager.
    앱 시작 시 RabbitMQ 연결 및 PvP 워커를 백그라운드로 구동하고,
    앱 종료 시 연결을 안전하게 해제합니다.
    """
    try:
        from app.services.rabbitmq_service import rabbitmq_service
        from app.workers.stt_worker import start_stt_consumer
        from app.workers.feedback_worker import start_feedback_consumer

        # RabbitMQ 연결 초기화
        await rabbitmq_service.connect()

        # PvP 워커를 백그라운드 태스크로 구동
        asyncio.create_task(start_stt_consumer())
        asyncio.create_task(start_feedback_consumer())
        logger.info("PvP workers started successfully.")

    except Exception as e:
        # RabbitMQ 연결 실패 시 앱은 정상 구동 (기존 REST API는 유지)
        logger.warning(f"RabbitMQ connection failed: {e}. PvP workers disabled.")

    yield

    # Shutdown: RabbitMQ 연결 해제
    try:
        from app.services.rabbitmq_service import rabbitmq_service

        await rabbitmq_service.close()
    except Exception as e:
        logger.warning(f"Error closing RabbitMQ: {e}")


# Initialize FastAPI app
# FastAPI 앱 초기화
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    root_path=settings.ROOT_PATH,
    dependencies=[Security(api_key_header)],  # Add Global Security
    lifespan=lifespan,  # RabbitMQ 워커 생명주기 관리
)

# Register global exception handlers for consistent error format
add_exception_handlers(app)


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
            content=create_error_response(
                code=ErrorCode.AUTH_ERROR,
                message="접근이 거부되었습니다. (Invalid Internal Secret)",
            ),
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
