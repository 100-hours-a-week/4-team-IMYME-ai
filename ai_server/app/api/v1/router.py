from fastapi import APIRouter
from app.api.v1.endpoints import transcription, gpu, solo, knowledge

api_router = APIRouter()

# Include the transcription router
# 전사 라우터 포함
api_router.include_router(transcription.router, tags=["transcription"])
api_router.include_router(gpu.router, prefix="/gpu", tags=["gpu"])
api_router.include_router(solo.router, prefix="/solo", tags=["solo"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
