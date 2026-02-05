from pydantic_settings import BaseSettings
from functools import lru_cache


class WorkerSettings(BaseSettings):
    # Whisper Model Size
    # Configured by build, but runtime checks or fallbacks
    # deepdml/faster-whisper-large-v3-turbo-ct2
    MODEL_SIZE: str = "deepdml/faster-whisper-large-v3-turbo-ct2"

    # Device (cuda/cpu)
    DEVICE: str = "cuda"

    # Compute Type
    COMPUTE_TYPE: str = "float16"

    # Baked Model Path
    MODEL_PATH: str = "/app/models"

    class Config:
        env_file = ".env"


@lru_cache()
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


settings = get_worker_settings()
