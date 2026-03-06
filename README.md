# 🧠 IMYME AI Server

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/RabbitMQ-Message%20Queue-FF6600?logo=rabbitmq&logoColor=white" alt="RabbitMQ"/>
  <img src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Gemini-3%20Pro%2F3%20Flash-4285F4?logo=google&logoColor=white" alt="Gemini"/>
  <img src="https://img.shields.io/badge/RunPod-Serverless-7B16FF?logo=runpod&logoColor=white" alt="RunPod"/>
</div>

<br>

> **"Speak, Learn, Improve."**
> 
> IMYME 서비스의 핵심 두뇌 역할을 하는 **AI 추론 및 오케스트레이션 서버**입니다.
> 고성능 STT 엔진과 Gemini 기반의 지식 평가 시스템을 통해 사용자에게 실시간 피드백을 제공하며, **RabbitMQ 기반의 비동기 워커(Worker) 아키텍처**로 동작하여 메인 서버와의 결합도를 낮추고 대규모 트래픽에도 안정적으로 대응합니다.

---

## ✨ Key AI Features

이 프로젝트는 단순한 API 서버가 아니라, **복합적인 AI 파이프라인**을 처리하는 비동기 메시징 엔진입니다.

### 1. 🐇 Message Driven Architecture (RabbitMQ)
- **Asynchronous Processing**: STT 변환 및 LLM 피드백 생성과 같은 무거운 작업을 HTTP 동기 통신 대신 MQ 기반의 비동기 워커 패턴으로 처리하여 병목을 제거했습니다.
- **Robust Error Handling**: 3회 재시도(Retry) 및 DLQ(Dead Letter Queue, `ai.pvp.dlq`, `ai.solo.dlq`) 라우팅을 통해 장애 발생 시에도 데이터 유실 없이 안전하게 예외를 수집합니다.

### 2. ⚡️ High-Performance Dual-Model Engine
- **Speed & Cost**: 실시간 피드백 생성과 점수 산정에는 **Gemini 3 Flash**를 사용하여 응답 속도를 극대화했습니다.
- **Deep Reasoning**: 복잡한 지식 심층 분석 및 평가에는 **Gemini 3 Pro**를 사용하여 정확한 판단력을 보장합니다.

### 3. 🤔 Advanced RAG System (Multi-Decision)
- **Knowledge Verification**: 사용자가 말한 내용이 올바른 지식인지 RAG(Retrieval-Augmented Generation) 시스템을 통해 검증합니다.
- **Multi-Candidate Evaluation**: 단순히 가장 유사한 지식 1개만 비교하는 것이 아니라, **Top-N개의 후보군**을 독립적으로 평가하여 정보의 정합성을 높입니다.

### 4. 🎙️ Robust STT Pipeline (RunPod Serverless)
- **Auto-Scaling**: GPU가 필요한 STT 워커는 RunPod 위에서 동작하며, 트래픽에 따라 **0개에서 N개까지 오토스케일링** 되어 비용 효율을 극대화합니다.
- **Whisper Large v3 Turbo**: 최신 모델을 사용하여 한국어 및 IT 기술 용어 인식률을 대폭 끌어올렸습니다.

---

## 🏗️ Architecture

시스템은 크게 메인 서버(Spring)의 요청을 비동기로 수신하는 **AI Server (RabbitMQ Worker)** 와 실제 GPU 연산을 수행하는 **STT Worker (RunPod)** 로 분리되어 있습니다.

```mermaid
graph LR
    User[Client] --> GW[Spring Backend]
    
    subgraph "Messaging Layer"
        GW -->|Publish Request| MQ[RabbitMQ]
        AI -->|Publish Response| MQ
    end
    
    subgraph "AI Core (Workers)"
        MQ -->|Consume| AI["AI Server (Python)"]
        AI -->|Generate| GEMINI[Google Gemini API]
        AI -->|Retrieve| DB[("PostgreSQL + pgvector")]
    end
    
    subgraph "GPU Workload"
        AI -->|Job Request| RP[RunPod Serverless]
        RP -->|Auto-Scale| W1[STT Worker 1]
    end
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- RabbitMQ (Local or Amazon MQ)
- RunPod Account & API Key
- Google Gemini API Key
- PostgreSQL (pgvector enabled)

### 1. Installation

```bash
# Repository 클론
git clone https://github.com/100-hours-a-week/4-team-IMYME-ai.git
cd 4-team-IMYME-ai

# 가상환경 생성 및 의존성 설치
python -m venv venv
source venv/bin/activate
pip install -r ai_server/requirements.txt
```

### 2. Configuration (.env)

`ai_server/.env` 파일을 생성하고 다음 환경변수들을 설정해야 합니다.

```ini
# RabbitMQ Connection
RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# LLM 
GEMINI_API_KEY=your_gemini_api_key

# RunPod GPU STT
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_runpod_endpoint_id

# RAG Database
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/db_name
```

### 3. Run AI Server (Local)

FastAPI 프레임워크를 베이스로 하지만, 메인 역할은 RabbitMQ 워커의 백그라운드 실행입니다. 애플리케이션 시작 시(Lifespan) 모든 큐 수신기가 자동으로 연결됩니다.

```bash
cd ai_server
uvicorn app.main:app --reload
```

---

## 📚 Communication Interfaces

### 1. Message Queue (RabbitMQ)
기존 HTTP API로 동작하던 피드백 채점 및 STT 로직은 모두 비동기 큐잉 방식으로 이관되었습니다. 메인 서버는 아래 큐에 JSON Payload로 작업을 요청해야 합니다.

| 워커 (Worker) | 요청 큐 (Request Queue) | 응답 큐 (Response Queue) | 역할 설명 |
| :--- | :--- | :--- | :--- |
| **Solo STT** | `solo.stt.request` | `solo.stt.response` | S3 오디오 파일을 텍스트로 변환 |
| **Solo Feedback**| `solo.feedback.request` | `solo.feedback.response` | STT 텍스트와 기준을 바탕으로 심층 분석 |
| **PvP STT** | `pvp.stt.request` | `pvp.stt.response` | (PvP 전용) 오디오 파일 텍스트 변환 |
| **PvP Feedback** | `pvp.feedback.request` | `pvp.feedback.response` | (PvP 전용) 심층 채점 및 페르소나 피드백 |

> 📌 상세한 요청/응답 JSON 스키마 규격은 백엔드 협업용 문서를 참고하세요.

### 2. REST API (RAG System Only)
메시지 큐 방식이 아닌, 실시간 동기 처리가 필요한 어드민용 지식(Knowledge) 데이터 RAG 시스템 통신만 HTTP API를 유지합니다.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/knowledge/candidates/batch` | 대량의 면접/기술 지식 데이터를 임베딩 및 DB 적재 |

---

## 📝 Troubleshooting

주요 이슈 및 해결 방법은 [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md) 파일을 참고하십시오.
- RabbitMQ Connection Timeout 이슈 해결
- RunPod STT Serverless 배포 가이드 및 Cold Start 
- Pydantic Validation Error 및 DLQ 추적 방법
