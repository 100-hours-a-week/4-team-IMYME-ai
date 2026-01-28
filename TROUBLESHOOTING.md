# 트러블 슈팅 로그 (Troubleshooting Log)

**RunPod Serverless 기반 Whisper AI 서버** 구축 과정에서 발생한 주요 문제점과 해결 방법을 기록.

---

## 1. 코드 및 의존성 이슈 (Code & Dependencies)

### 1.1. 로컬 Python 3.13 호환성 문제
- **문제상황**: 로컬 개발 환경(Python 3.13)에서 `pip install` 시 `pydantic-core` 빌드 실패 (`maturin failed`).
- **원인**: `pydantic==2.6.0` 등 구버전 라이브러리가 Python 3.13의 변경된 C API를 지원하지 않음.
- **해결**: `src/requirements.txt`에서 버전을 `pydantic>=2.9.0` 등으로 상향 조정하여 Python 3.13 호환성 확보.

### 1.2. Pydantic List Validation Error (Solo Mode API)
- **문제상황**: `Solo Mode` 피드백 생성 API 호출 시 `result.feedback.keyword` 필드에서 `ValidationError` 발생.
    ```text
    pydantic_core._pydantic_core.ValidationError: 2 validation errors for SoloResultData
    result.feedback.keyword.0 Input should be a valid string [type=string_type, input_value=['Handshake', ...], input_type=list]
    ```
- **원인**: Gemini API 프롬프트가 키워드를 "성공한 키워드", "실패한 키워드" 두 그룹으로 나누어 **이중 리스트**(`[[ok...], [missed...]]`) 형태로 반환했으나, Pydantic 스키마(`schemas/solo.py`)는 단순 문자열 리스트 `List[str]`만 허용하도록 정의되어 있었음.
- **해결**:
    1.  `schemas/solo.py`: `keyword` 필드 타입을 `List[str]` → `List[Any]`로 변경하여 중첩 리스트 구조 허용.
    2.  `prompts.py`: 시스템 프롬프트의 `[Output Format]` 예시를 이중 리스트 형태(`[["..."], ["..."]]`)로 명확히 수정하여 LLM의 의도된 출력 유도.

---

## 2. Docker 빌드 및 배포 이슈 (Docker Build & Deploy)

### 2.1. PyAV 빌드 실패 (`pkg-config` 누락)
- **문제상황**: Docker 빌드 중 `faster-whisper`의 의존성인 `av` 패키지 설치 실패 (`subprocess-exited-with-error`).
- **원인**: Base Image에 `ffmpeg` 개발 라이브러리와 `pkg-config`가 없어 소스 빌드가 불가능했음.
- **해결**: `Dockerfile`에 `pkg-config`, `libavformat-dev`, `libavcodec-dev` 등 필수 개발 패키지 설치 구문 추가.

### 2.2. CUDA 버전 불일치 (`libcublas.so.12`)
- **문제상황**: RunPod에서 `Library libcublas.so.12 is not found` 에러 발생.
- **원인**: `faster-whisper`(CTranslate2)는 **CUDA 12**를 요구하나, Docker Base Image가 **CUDA 11.8** 버전이었음.
- **해결**: Base Image를 `runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04` (CUDA 12.1 지원)로 변경.

---

## 3. RAG (Knowledge System) 구현 이슈

### 3.1. API Key 로딩 시점 문제 (Standalone Script)
- **문제상황**: FastAPI 앱 구동 시에는 문제가 없으나, 독립 스크립트(`verify_rag_core.py`) 실행 시 `GEMINI_API_KEY`를 찾지 못함.
- **원인**: `app/core/config.py`의 `Settings` 객체가 `load_dotenv()` 호출 전에 초기화되어, 환경변수 파일(.env)의 값을 읽어오지 못함 (Pydantic Settings 캐싱 특성).
- **해결**: `KnowledgeService.__init__` 메서드 내에 **방어 코드** 추가. `settings.GEMINI_API_KEY`가 비어있을 경우, 명시적으로 `.env` 파일을 찾아 다시 로드(`reload`)하고 값을 주입하도록 수정.

## 4. 성능 및 지연 시간 (Latency) 이슈

### 4.1. Solo Mode Feedback 지연 (Submissions)
- **문제상황**: `/api/v1/solo/submissions` 요청 완료 및 피드백 생성까지 약 30~60초 이상 소요됨.
- **원인**:
    1. **Gemini Pro 모델의 응답 속도**: 복잡한 프롬프트(페르소나 분석, 채점) 처리 시 근본적인 LLM 추론 시간 소요.
    2. **병렬/순차 실행 트레이드오프**: `gRPC` 데드락 이슈 회피를 위해 한때 순차 실행(Scoring -> Feedback)을 적용했으나, 이 경우 시간이 2배로 늘어남. (현재는 안정성 확인 후 병렬 실행으로 유지 중이나, 여전히 모델 자체 속도가 병목)
- **현황**: 안정성을 위해 병렬 실행을 유지하되, 클라이언트가 Polling 방식으로 대기하도록 설계됨.

### 4.2. RAG Embedding 생성 지연 (Knowledge Batch)
- **문제상황**: `/api/v1/knowledge/candidates/batch` 호출 시 대량의 데이터를 정제하고 임베딩하는 과정에서 응답이 매우 느림(2~3분).
- **원인**:
    1. **LLM Refinement**: 모든 Raw Feedback에 대해 Gemini가 1차 정제(Refinement)를 수행해야 함.
    2. **Local Embedding Model**: `sentence-transformers` 모델이 CPU/GPU 자원을 사용하여 벡터를 생성하는 연산 비용이 높음.
- **해결 및 현황**:
    - **Model 교체**: `gemini-3-pro-preview` -> **`gemini-3-flash-preview`**로 변경.
    - **결과**: 응답 시간이 **2~3분 -> 7~10초**로 대폭 개선됨. (비동기 배치 처리가 필수는 아니게 됨)

