from fastapi import APIRouter
from app.api.v1.endpoints import knowledge

api_router = APIRouter()

# Knowledge API (REST 유지)
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
