import time
from services.model_service import ModelService
from utils.audio_loader import AudioLoader

# Removed dependency on app.schemas
import logging
from config import settings

logger = logging.getLogger(__name__)


# Service class for handling transcription logic (Worker Side)
# 전사 로직을 처리하는 서비스 클래스 (워커 사이드)
class InferenceService:
    def __init__(self):
        self.model_service = ModelService()
        self.audio_loader = AudioLoader()

    # Main method to transcribe audio from a URL
    def transcribe(self, audio_url: str, language: str = None) -> dict:
        start_time = time.time()
        temp_file_path = None

        try:
            # 1. Download audio file
            logger.info(f"Downloading audio from {audio_url}")
            temp_file_path = self.audio_loader.download_audio(audio_url)

            # 2. Get Model
            model = self.model_service.get_model()

            # 3. Transcribe
            logger.info("Starting transcription...")
            # beam_size=5 is a common default
            # Updated with VAD & Hallucination Prevention settings
            segments_generator, info = model.transcribe(
                temp_file_path,
                beam_size=5,
                language=language,
                # [VAD & Hallucination Prevention]
                vad_filter=settings.VAD_FILTER,
                vad_parameters=dict(
                    min_silence_duration_ms=settings.MIN_SILENCE_DURATION_MS
                ),
                condition_on_previous_text=settings.CONDITION_ON_PREVIOUS_TEXT,
                no_speech_threshold=settings.NO_SPEECH_THRESHOLD,
                hallucination_silence_threshold=settings.HALLUCINATION_SILENCE_THRESHOLD,
                temperature=settings.TEMPERATURE,
            )

            segments = list(segments_generator)

            # 4. Format Response (Return Dict)
            transcription_segments = [
                {"start": s.start, "end": s.end, "text": s.text} for s in segments
            ]

            full_text = " ".join([s.text for s in segments])
            process_time = time.time() - start_time

            return {
                "text": full_text,
                "segments": transcription_segments,
                "language": info.language,
                "processing_time": process_time,
            }

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise e
        finally:
            # 5. Cleanup
            if temp_file_path:
                self.audio_loader.cleanup_file(temp_file_path)
