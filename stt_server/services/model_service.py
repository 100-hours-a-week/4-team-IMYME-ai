from faster_whisper import WhisperModel

# Updated import for decoupled worker
from config import settings
import logging

# Logger setup
logger = logging.getLogger(__name__)


# Service class for managing the Whisper Model
# Whisper 모델을 관리하는 서비스 클래스
class ModelService:
    _instance = None
    _model = None

    # Singleton pattern to ensure only one model instance loads in memory
    # 메모리에 하나의 모델 인스턴스만 로드되도록 싱글톤 패턴 적용
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelService, cls).__new__(cls)
            cls._instance.load_model()
        return cls._instance

    # Loads the Whisper model using settings
    # 설정을 사용하여 Whisper 모델을 로드하는 메서드
    def load_model(self):
        if self._model is None:
            logger.info(f"Loading Whisper model from {settings.MODEL_PATH}...")
            try:
                # Initialize WhisperModel with parameters from config
                # 설정 파일의 파라미터로 WhisperModel 초기화
                # local_files_only=True prevents trying to download if path exists
                # local_files_only=True는 경로가 존재할 경우 다운로드를 시도하지 않음
                self._model = WhisperModel(
                    settings.MODEL_PATH,  # Or just settings.MODEL_SIZE if not using baked path logic yet, but we will use path.
                    device=settings.DEVICE,
                    compute_type=settings.COMPUTE_TYPE,
                )
                logger.info("Whisper model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise RuntimeError(f"Could not load model: {e}")

    # Returns the loaded model instance
    # 로드된 모델 인스턴스를 반환하는 메서드
    def get_model(self) -> WhisperModel:
        if self._model is None:
            self.load_model()
        return self._model


# Dependency/Global accessor
# 의존성/전역 접근자
def get_model_service() -> ModelService:
    return ModelService()
