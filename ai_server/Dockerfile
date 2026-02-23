# 1) builder: wheels 생성
FROM python:3.10-slim AS builder

# Python 런타임 기본 최적화
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
# 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install Python dependencies
# Python 의존성 설치
# For ARM64, PyTorch installation might need special handling
# ARM64의 경우 PyTorch 설치에 특별한 처리가 필요할 수 있음
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# 2) runtime: 실제 실행 이미지
FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# torch/sentence-transformers 런타임에서 필요한 라이브러리(특히 libgomp1)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 빌드 단계에서 생성된 wheel 복사 및 설치
COPY --from=builder /app/wheels /wheels
COPY requirements.txt .

# wheel 폴더만 보고 설치 (인터넷 재다운로드 방지)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels

# 앱 복사
COPY app/ /app/app/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
