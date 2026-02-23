import logging
from typing import List, Optional
from sentence_transformers import SentenceTransformer
import warnings

from app.core.errors import AppException, ErrorCode

# Suppress warnings for cleaner logs
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class EmbeddingService:
    _instance = None
    model: Optional[SentenceTransformer] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
        return cls._instance

    def initialize(self):
        if self.model is not None:
            return

        self.model_name = "Qwen/Qwen3-Embedding-0.6B"
        self.device = "cpu"
        logger.info(f"Loading Embedding Model: {self.model_name} on {self.device}...")

        try:
            # trust_remote_code is required for Qwen models
            self.model = SentenceTransformer(
                self.model_name, trust_remote_code=True, device=self.device
            )
            logger.info("Embedding Model Loaded Successfully.")
        except Exception as e:
            logger.error(f"Failed to load Embedding Model: {e}")
            self.model = None

    def generate_embedding(self, text: str, is_query: bool = False) -> List[float]:
        if not self.model:
            # Try to initialize if not loaded (lazy load attempt)
            self.initialize()
            if not self.model:
                raise AppException(
                    code=ErrorCode.EMBEDDING_FAILURE,
                    message="임베딩 모델이 로드되지 않았습니다.",
                    status_code=500,
                )

        # NOTE: For Qwen3-Embedding, queries generally benefit from an instruction.
        # "Instruct: ...\nQuery: ..."
        # For knowledge candidate storage (documents), no instruction is needed.
        # For this implementation phase, we treat inputs as documents.

        try:
            # normalize_embeddings=True is recommended for cosine similarity
            embeddings = self.model.encode(
                text, convert_to_tensor=False, normalize_embeddings=True
            )

            if isinstance(embeddings, list):
                return embeddings
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise AppException(
                code=ErrorCode.EMBEDDING_FAILURE,
                message="임베딩 생성 중 오류가 발생했습니다.",
                detail={"raw_error": str(e)},
                status_code=500,
            )


# Global instance pattern (optional, but convenient)
embedding_service = EmbeddingService()
