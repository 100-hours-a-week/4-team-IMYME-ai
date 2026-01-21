from fastapi import APIRouter
from app.api.v1.endpoints import transcription, gpu

api_router = APIRouter()

# Include the transcription router
# 전사 라우터 포함
api_router.include_router(transcription.router, tags=["transcription"])
api_router.include_router(gpu.router, prefix="/gpu", tags=["gpu"])
