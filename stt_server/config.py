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

    # [Hallucination Prevention & VAD]
    VAD_FILTER: bool = True
    MIN_SILENCE_DURATION_MS: int = 500  # 0.5s silence -> removal
    CONDITION_ON_PREVIOUS_TEXT: bool = False  # Prevent loop
    NO_SPEECH_THRESHOLD: float = 0.4  # Stricter silence detection
    HALLUCINATION_SILENCE_THRESHOLD: float = (
        2.0  # (Advanced) Ignore text from >2s silence
    )
    TEMPERATURE: float = 0.0  # Deterministic

    class Config:
        env_file = ".env"


@lru_cache()
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


settings = get_worker_settings()
