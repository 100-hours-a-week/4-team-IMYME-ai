from pydantic import BaseModel, Field
from typing import Optional


# Request Schema for Transcription
# 전사 요청을 위한 스키마 정의
class TranscriptionRequest(BaseModel):
    # The URL of the audio file in S3 (or any accessible URL)
    # S3 또는 접근 가능한 오디오 파일의 URL (camelCase alias)
    # Note: Changed to str to handle validation errors manually with custom code (INVALID_URL)
    audio_url: str = Field(
        ..., alias="audioUrl", description="오디오 파일 경로 (S3 Presigned URL)"
    )

    class Config:
        populate_by_name = True


# Inner Data Schema for Response
class TranscriptionData(BaseModel):
    text: str


# Response Schema for Transcription (Wrapped in standard envelope)
# 전사 응답을 위한 스키마 정의 (success, data, error)
class TranscriptionResponse(BaseModel):
    success: bool
    data: Optional[TranscriptionData] = None
    error: Optional[str] = None
