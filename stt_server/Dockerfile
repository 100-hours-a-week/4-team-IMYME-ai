# Use RunPod's specific PyTorch base image
# RunPod의 특정 PyTorch 기본 이미지 사용 (CUDA 12.1.1 호환 - faster-whisper 최신 호환)
FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

# Set working directory
# 작업 디렉토리 설정
WORKDIR /app

# Install system dependencies
# 시스템 의존성 설치 (ffmpeg 필수)
# PKG-CONFIG is required for building PyAV if binary wheels are missing
# PyAV 빌드를 위해 pkg-config 및 빌드 도구, 그리고 FFmpeg 개발 라이브러리 추가
RUN apt-get update && apt-get install -y \
    ffmpeg \
    pkg-config \
    build-essential \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
# Docker 캐시를 활용하기 위해 요구 사항 파일 먼저 복사
# NOTE: Building from project root, so path includes stt_server/
COPY stt_server/requirements.txt .

# Upgrade pip to ensure we get the latest wheels
# 바이너리 휠을 다운로드하기 위해 pip 업그레이드
RUN pip install --upgrade pip

# Install Python dependencies
# Python 의존성 설치
RUN pip install --no-cache-dir -r requirements.txt

# Create models directory
# 모델 디렉토리 생성
RUN mkdir -p /app/models

# Copy builder script for model downloading
# 모델 다운로드를 위한 빌더 스크립트 복사
COPY stt_server/builder/download_model.py /app/builder/download_model.py

# Download the model (this layer will be cached if model doesn't change)
# 모델 다운로드 (모델이 변경되지 않으면 이 레이어는 캐시됨)
RUN python /app/builder/download_model.py

# Copy all source code
# 모든 소스 코드 복사 (stt_server 폴더의 내용물을 컨테이너의 /app으로 복사)
# NOTE: This flat copies stt_server content (handler.py, services, etc) to /app
COPY stt_server/ /app/

# Set Python path to include /app so we can import packages
# 패키지 임포트를 위해 Python 경로 설정
ENV PYTHONPATH=/app

# Set the command to run the RunPod handler
# RunPod 핸들러를 실행하기 위한 명령 설정
CMD ["python", "-u", "/app/handler.py"]
