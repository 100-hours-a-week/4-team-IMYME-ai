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

    # Timeout for polling
    RUNPOD_TIMEOUT_SECONDS: int = 600

    # Gemini Configuration
    GEMINI_API_KEY: str = ""

    # Root path for reverse proxy (e.g. /ai)
    ROOT_PATH: str = ""

    # Internal Secret for Middleware Auth
    INTERNAL_SECRET_KEY: str = ""

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
