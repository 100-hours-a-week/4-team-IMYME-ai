from pydantic_settings import BaseSettings
from functools import lru_cache


# Configuration class using Pydantic Settings for environment management
# 환경 설정을 관리하기 위해 Pydantic Settings를 사용하는 설정 클래스
class Settings(BaseSettings):
    # Application Title
    # 애플리케이션 제목
    PROJECT_NAME: str = "IMYME AI Server"

    # API Version path
    # API 버전 경로
    API_V1_STR: str = "/api/v1"

    # RunPod Configuration
    # RunPod 설정
    RUNPOD_API_KEY: str = ""
    RUNPOD_ENDPOINT_ID: str = ""

    # Pod (Primary) — Direct HTTP to FastAPI on RunPod Pod
    # Pod가 설정되어 있으면 우선 호출, 실패 시 Serverless Fallback
    RUNPOD_POD_URL: str = ""  # e.g. https://{POD_ID}-8000.proxy.runpod.net
    RUNPOD_POD_TIMEOUT: int = 30  # Pod 응답 대기 시간 (초)

    # Timeout for Serverless polling (Fallback)
    RUNPOD_TIMEOUT_SECONDS: int = 600

    # Gemini Configuration
    GEMINI_API_KEY: str = ""

    # Root path for reverse proxy (e.g. /ai)
    ROOT_PATH: str = ""

    # Internal Secret for Middleware Auth
    INTERNAL_SECRET_KEY: str = ""

    # RabbitMQ Configuration (PvP Mode)
    # RabbitMQ 설정 (PvP 모드)
    RABBITMQ_URL: str = ""
    STT_REQUEST_QUEUE: str = "pvp.stt.request"
    STT_RESULT_QUEUE: str = "pvp.stt.response"
    FEEDBACK_REQUEST_QUEUE: str = "pvp.feedback.request"
    FEEDBACK_RESULT_QUEUE: str = "pvp.feedback.response"
    PVP_EXCHANGE: str = "pvp.direct"
    PVP_DLQ: str = "ai.pvp.dlq"

    # RabbitMQ Configuration (Solo Mode)
    # RabbitMQ 설정 (Solo 모드)
    SOLO_STT_REQUEST_QUEUE: str = "solo.stt.request"
    SOLO_STT_RESULT_QUEUE: str = "solo.stt.response"
    SOLO_FEEDBACK_REQUEST_QUEUE: str = "solo.feedback.request"
    SOLO_FEEDBACK_RESULT_QUEUE: str = "solo.feedback.response"
    SOLO_EXCHANGE: str = "solo.direct"
    SOLO_DLQ: str = "ai.solo.dlq"

    # PostgreSQL (Knowledge Base - Shared with Spring Boot)
    DATABASE_URL: str = ""

    class Config:
        # Load settings from .env file if present
        # .env 파일이 존재하면 설정을 로드함
        env_file = ".env"


# Singleton pattern for settings using lru_cache
# lru_cache를 사용하여 설정 인스턴스를 싱글톤으로 관리
@lru_cache()
def get_settings() -> Settings:
    return Settings()


# Global settings instance
# 전역 설정 인스턴스
settings = get_settings()
