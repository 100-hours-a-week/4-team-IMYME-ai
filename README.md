# 🧠 IMYME AI Server

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-Pro%2F2.5%20Flash-4285F4?logo=google&logoColor=white)
![RunPod](https://img.shields.io/badge/RunPod-Serverless-7B16FF?logo=runpod&logoColor=white)
![Whisper](https://img.shields.io/badge/Whisper-Large%20v3-FF9E0F?logo=openai&logoColor=white)

> **"Speak, Learn, Improve."**
> 
> IMYME 서비스의 핵심 두뇌 역할을 하는 **AI 추론 및 오케스트레이션 서버**입니다.
> 고성능 STT 엔진과 Gemini 기반의 지식 평가 시스템을 통해 사용자에게 실시간 피드백을 제공합니다.

---

## ✨ Key AI Features

이 프로젝트는 단순한 API 서버가 아니라, **복합적인 AI 파이프라인**을 처리하는 엔진입니다.

### 1. ⚡️ High-Performance Dual-Model Engine
- **Speed & Cost**: 실시간 피드백 생성과 점수 산정에는 **Gemini 2.5 Flash**를 사용하여 응답 속도를 극대화했습니다.
- **Deep Reasoning**: 복잡한 지식 검증 및 평가(RAG)에는 **Gemini 3 Pro**를 사용하여 정확한 판단력을 보장합니다.
- **Flexible Architecture**: 모듈형 설계를 통해 상황에 따라 모델을 자유롭게 교체할 수 있습니다.

### 2. 🎯 Advanced RAG System (Multi-Decision)
- **Knowledge Verification**: 사용자가 말한 내용이 올바른 지식인지 검증합니다.
- **Multi-Candidate Evaluation**: 단순히 가장 유사한 지식 1개만 비교하는 것이 아니라, **Top-N개의 후보군**을 독립적으로 평가하여 정보의 정합성을 높였습니다.

### 3. 🎙️ Robust STT Pipeline
- **Whisper Large v3 Turbo**: 최신 Whisper 모델을 사용하여 한국어 및 기술 용어 인식률을 높였습니다.
- **Silero VAD Integration**: Voice Activity Detection을 통해 비음성 구간(침묵, 배경음악)을 제거하여 **Hallucination(환각)** 현상을 원천 차단했습니다.

### 4. ☁️ Scalable Serverless Infrastructure
- **RunPod Serverless**: GPU가 필요한 STT 워커는 RunPod 위에서 동작하며, 트래픽에 따라 **0개에서 N개까지 오토스케일링** 됩니다.
- **Cost Efficiency**: 사용하지 않을 때는 비용이 0원에 수렴하는 구조입니다.

---

## 🏗️ Architecture

시스템은 크게 **AI Server(Controller)**와 **STT Worker(GPU)**로 분리되어 있습니다.

```mermaid
graph LR
    User[Client] -->|Audio/Text| GW[API Gateway]
    GW -->|REST API| AI[AI Server (FastAPI)]
    
    subgraph "AI Core"
        AI -->|Generate| GEMINI[Google Gemini API]
        AI -->|Retrieve| DB[(PostgreSQL + pgvector)]
    end
    
    subgraph "GPU Workload"
        AI -->|Job Request| RP[RunPod Serverless]
        RP -->|Auto-Scale| W1[STT Worker 1]
        RP -->|Auto-Scale| W2[STT Worker 2]
    end
```

1.  **AI Server (`ai_server/`)**: 클라이언트의 요청 처리, 프롬프트 엔지니어링, RAG 로직, LLM 통신 담당.
2.  **STT Worker (`stt_server/`)**: 무거운 음성 인식 모델(Whisper)을 전담 처리하는 GPU 컨테이너.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Docker (for deployment)
- RunPod Account & API Key
- Google Gemini API Key

### 1. Installation

```bash
# Clone Repository
git clone https://github.com/100-hours-a-week/4-team-IMYME-ai.git
cd 4-team-IMYME-ai

# Install Dependencies
pip install -r ai_server/requirements.txt
```

### 2. Configuration (.env)

`ai_server/.env` 파일을 생성하고 키를 설정하세요.

```ini
# Gemini
GEMINI_API_KEY=your_gemini_key

# RunPod STT
RUNPOD_API_KEY=your_runpod_key
RUNPOD_ENDPOINT_ID=your_endpoint_id

# Security
INTERNAL_SECRET_KEY=your_secret_key
```

### 3. Run AI Server (Local)

```bash
cd ai_server
python -m app.main
```
서버가 실행되면 `http://localhost:8000/docs`에서 API 문서를 확인할 수 있습니다.

---

## 📦 Deployment (STT Worker)

STT 서버는 RunPod Serverless 환경에 배포되어야 합니다.

**Build & Push**
```bash
# 프로젝트 루트에서 실행
docker build --platform linux/amd64 -t your-repo/whisper-worker:v1.0 -f stt_server/Dockerfile .
docker push your-repo/whisper-worker:v1.0
```

RunPod 콘솔에서 해당 이미지를 사용하여 Serverless Endpoint를 생성하세요.

---

## 📚 API Guidelines

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/transcriptions` | 오디오 URL을 텍스트로 변환 (STT) |
| `POST` | `/api/v1/solo/submissions` | 사용자 답변 분석 및 피드백 생성 (AI Coaching) |
| `POST` | `/api/v1/knowledge/candidates/batch` | 대량의 지식 데이터를 임베딩 및 정제 (RAG) |
| `POST` | `/api/v1/gpu/warmup` | GPU Cold Start 방지를 위한 워밍업 |

---

## 📝 Troubleshooting

주요 이슈 및 해결 방법은 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) 파일을 참고하세요.

- `NameError: settings not defined` 해결법
- STT Hallucination 방지 팁
- Docker 빌드 이슈 등
