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


## 5. 보안 강화: 내부 인증 도입 (Internal Secret)
- **배경**: AI 서버 API가 외부에 노출될 경우 무분별한 요청이나 오남용을 방지하기 위해 최소한의 인증 장치가 필요.
- **조치**: 
    - `main.py`에 Middleware를 추가하여 모든 요청(Health Check 제외)에 대해 `x-internal-secret` 헤더를 검증하도록 변경.
    - 환경 변수 `INTERNAL_SECRET_KEY`를 통해 비밀키를 관리.



## 6. API Access Denied (403 Forbidden)
**증상**: API 호출 시 `403 Forbidden` 에러와 `{"detail": "Access Denied: Invalid Internal Secret"}` 응답 발생.

**원인**: AI 서버에 내부 인증 미들웨어가 적용되어 올바른 `x-internal-secret` 헤더 없이 요청했기 때문.

**해결 방법**:
1. **서버 설정**: 파일에 비밀키 정의
   ```bash
   SECRET_KEY=your-secret-key
   ```
2. **클라이언트 요청**: HTTP Header에 `x-internal-secret` 추가
   ```http
   x-internal-secret: your-secret-key
   ```
3. **Swagger UI 사용 시**:
    - **증상**: Swagger에서 API 테스트 시 `Authorize` 버튼이 없어서 헤더를 넣을 수 없고 `403` 에러 발생.
    - **해결**: `main.py`에 `APIKeyHeader` 설정을 추가하여 Swagger UI에 자물쇠 버튼을 활성화해야 함.
      ```python
      from fastapi.security import APIKeyHeader
      api_key_header = APIKeyHeader(name="x-internal-secret", auto_error=False)
      app = FastAPI(..., dependencies=[Security(api_key_header)])
      ```
    - **적용 범위**: 위 코드가 적용된 서버라면 **로컬(Local)과 배포된 서버(Remote) 모두 동일하게 적용됨**. Swagger 우측 상단 `Authorize` 버튼에 키를 입력하면 정상 호출 가능.

## 7. Embedding Model Resource Crash (Server OOM)

### 7.1. 증상 (Symptoms)
- **상황**: API 클라이언트를 통해 **임베딩 생성 요청**(`/api/v1/knowledge/candidates/batch`)을 짧은 시간동안 3번 보낸 직후, **서버가 응답 없음**.
    서버 측 로그에는 별다른 에러 없이 프로세스가 사라짐 (OOM Kill 등).

### 7.2. 원인 (Cause)
- **모델 부하**: 사용 중인 임베딩 모델(`Qwen/Qwen3-Embedding-0.6B`)은 0.6B 파라미터 크기를 가지며, 초기 로딩 및 배치 처리 시 **상당한 CPU 메모리와 연산 자원**을 소모함.
- **리소스 부족**: 배포된 서버(EC2)의 가용 메모리가 모델의 피크 메모리 사용량을 감당하지 못해 OS 레벨에서 프로세스를 강제 종료(OOM Killer)시킴.
- **Warmup 부하**: 서버가 무거운 모델 로딩과 추론 요청이 동시에 들어오면서 부하가 급증함.

### 7.3. 해결 및 완화 (Mitigation)
1.  **서버 리소스 증설**: 근본적으로는 모델을 감당할 수 있는 충분한 VRAM/RAM이 있는 인스턴스로 업그레이드.
2.  **스왑 메모리 설정**: EC2 인스턴스에 스왑 메모리를 설정하여 메모리 부족 시 디스크를 메모리처럼 사용하도록 함.

---

## 8. RAG Hybrid Search Similarity Score 이슈

### 8.1. 증상 (Symptoms)
- **상황**: `/api/v1/knowledge/evaluations` 엔드포인트로 전송되는 요청에서 `similars` 배열의 모든 항목이 `similarity: 0.0`으로 고정되어 있음.
- **영향**: AI 서버가 정확한 유사도 점수를 받지 못해 중복 판단(UPDATE/IGNORE) 정확도가 저하됨.

### 8.2. 원인 (Root Cause)
1.  **Repository 반환 타입 한계**:
    - `KnowledgeRepository.hybridRRFSearch` 메소드가 `KnowledgeBase` **엔티티**를 반환하도록 설계됨.
    - 엔티티는 DB 테이블과 1:1 매핑되므로, SQL 쿼리 실행 중 계산된 **임시 값(`similarity`, `rrf_score`)을 담을 필드가 없음**.
    - 결과적으로 쿼리 내부에서 점수를 계산하고 정렬에 사용하지만, 최종 반환 시 점수 정보가 소실됨.

2.  **Controller의 하드코딩**:
    - `IntegrationTestController`에서 검색 결과를 `EvaluateSimilarInput`으로 변환할 때, 유사도 정보가 없어 `similarity: 0.0`으로 하드코딩됨.

### 8.3. 해결 (Solution)
1.  **Repository 수정** (`KnowledgeRepository.java`):
    - 새로운 메소드 `hybridSearchWithScore` 추가.
    - SQL 쿼리의 `SELECT` 절에 `COALESCE(sr.similarity, 0.0) AS similarity` 포함.
    - `semantic_ranked` CTE에 `similarity` 컬럼 추가.
    - 반환 타입을 `List<SimilarKnowledge>` DTO로 변경하여 점수 정보 포함.

2.  **Controller 수정** (`IntegrationTestController.java`):
    - `hybridRRFSearch` → `hybridSearchWithScore` 호출로 변경.
    - DTO에서 실제 유사도 값(`dto.getSimilarity()`)을 추출하여 AI 서버로 전송.

### 8.4. 검증 (Verification)
수정 후 로그 확인 결과, 정상적인 유사도 점수가 출력됨:
```json
{
  "similars": [
    { "id": "11", "similarity": 0.6684612032542473 },
    { "id": "13", "similarity": 0.34919357016201613 },
    { "id": "12", "similarity": 0.2953150184358715 }
  ]
}
```

