from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List

# Request Schema for Transcription
# 전사 요청을 위한 스키마 정의
class TranscriptionRequest(BaseModel):
    # The URL of the audio file in S3 (or any accessible URL)
    # S3 또는 접근 가능한 오디오 파일의 URL
    audio_url: HttpUrl = Field(..., description="URL of the audio file (S3)")
    
    # Optional language code (e.g., "ko", "en"). If None, auto-detects.
    # 언어 코드 (선택 사항). 지정하지 않으면 자동 감지.
    language: Optional[str] = Field(None, description="Language code (e.g., 'ko', 'en'). Auto-detect if None.")

# Segment Schema representing a part of the transcribed text
# 전사된 텍스트의 세그먼트(일부분)를 나타내는 스키마
class TranscriptionSegment(BaseModel):
    # Start time of the segment in seconds
    # 세그먼트 시작 시간 (초 단위)
    start: float
    
    # End time of the segment in seconds
    # 세그먼트 종료 시간 (초 단위)
    end: float
    
    # Text content of the segment
    # 세그먼트의 텍스트 내용
    text: str

# Response Schema for Transcription
# 전사 응답을 위한 스키마 정의
class TranscriptionResponse(BaseModel):
    # Full transcribed text combined
    # 전체 전사 텍스트 결합본
    text: str
    
    # List of detailed segments
    # 상세 세그먼트 리스트
    segments: List[TranscriptionSegment]
    
    # Detected language (useful if auto-detect was used)
    # 감지된 언어 (자동 감지 사용 시 유용)
    language: str
    
    # Processing time duration (optional, for monitoring)
    # 처리 소요 시간 (선택 사항, 모니터링 용도)
    processing_time: float
