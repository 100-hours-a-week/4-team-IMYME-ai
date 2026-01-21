from fastapi import FastAPI
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
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Include API routers
# API 라우터 포함
app.include_router(api_router, prefix=settings.API_V1_STR)

# Root endpoint for health check
# 헬스 체크를 위한 루트 엔드포인트
@app.get("/")
def health_check():
    return {"status": "ok", "service": settings.PROJECT_NAME}

if __name__ == "__main__":
    import uvicorn
    # Run the server using uvicorn
    # uvicorn을 사용하여 서버 실행
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
