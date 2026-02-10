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


## 8. STT Hallucination (환각) 이슈

Whisper 모델 사용 시, 실제 음성에 없는 텍스트가 생성되는 환각 현상이 발생. 주요 원인은 다음과 같음.

### 8.1. 데이터 편향에 의한 연상 작용 (Association-based Hallucination)
- **현상**: 비디오의 시작, 끝, 혹은 배경음악만 나오는 구간에서 "시청해 주셔서 감사합니다(Thanks for watching)", "자막 제공: Amara.org", "좋아요와 구독 부탁드립니다" 등의 문구가 생성됨.
- **원인**: Whisper 모델은 인터넷 영상 자막으로 학습됨. 학습 데이터에서 이러한 문구가 배경 소음(White Noise)이나 침묵 구간과 통계적으로 강하게 연결(Mapping)되어 있기 때문에, 정적 노이즈를 자막 크레딧 타이밍으로 오인하여 생성.

### 8.2. 디코더의 자기 회귀적 루프 (Autoregressive Looping)
- **현상**: 특정 단어가 무한 반복되거나 문맥에 맞지 않는 엉뚱한 문장이 생성됨.
- **원인**: Transformer 디코더는 이전 토큰을 기반으로 다음 토큰을 생성함. 침묵 구간에서 모델이 불확실성 속에 임의의 잘못된 토큰을 하나 생성하면, 이것이 다음 스텝의 입력이 되어 오류가 증폭됨. 모델은 이 오류를 정당화하기 위해 억지스러운 문맥을 이어가거나 루프(Loop)에 빠지게 됨.

[STT응답](https://www.notion.so/STT-hallucination-2fa1715a156080469f59f57df1eed8ce?source=copy_link)

---

## 9. Knowledge Evaluation: Single-Target → Multi-Decision 전환

### 9.1. 문제 상황 (Problem)
- **기존 방식**: Hybrid Search(Vector + Keyword RRF)를 통해 **단 1개의 유사 지식**만 선택하여 UPDATE/IGNORE 판단.
- **발생한 문제**:
  1. **의도한 Criteria가 검색되지 않음**: 테스트 시 예상했던 업데이트 대상 지식이 검색 결과 1위로 나오지 않고, 다른 지식이 선택됨.
  2. **UPDATE 실험 불가**: 검색된 지식이 의도와 다르다 보니, LLM이 계속 `IGNORE` 판단만 내려 실제 UPDATE 로직을 검증할 수 없었음.
  3. **Same-Keyword 우선순위 누락**: 같은 Keyword를 가진 지식은 우선적으로 업데이트 대상이 되어야 하는데, 검색 알고리즘만으로는 이를 보장할 수 없었음.

### 9.2. 원인 분석 (Root Cause)
1. **Hybrid Search의 한계**:
   - Vector 유사도와 Keyword 매칭을 결합한 RRF 알고리즘은 **전체적인 유사성**을 기준으로 순위를 매김.
   - 하지만 "같은 Keyword"라는 **명시적 우선순위**를 반영하지 못함.
   - 결과적으로 다른 Keyword의 지식이 Vector 유사도가 높다는 이유로 1위를 차지할 수 있음.

2. **Single-Target의 제약**:
   - 1개만 선택하면 LLM이 판단할 수 있는 선택지가 제한됨.
   - 검색 알고리즘의 오류나 편향을 LLM이 보정할 기회가 없음.

### 9.3. 해결 방안 (Solution)
**Multi-Decision Evaluation 도입**: 여러 개의 후보를 LLM에게 제공하고, 각각에 대해 독립적으로 UPDATE/IGNORE 판단하도록 변경.

#### 변경 사항 (Changes)

##### 1. **검색 로직 개선** (Backend: `KnowledgeBatchService.java`)
```java
// Step 1: Same-Keyword Items (항상 포함)
List<KnowledgeBase> sameKeywordItems = knowledgeRepository
    .findByKeywordId(keywordId)
    .stream()
    .limit(10)
    .collect(Collectors.toList());

// Step 2: Hybrid RRF Search (다양한 후보 검색)
List<KnowledgeSearchResult> rrfResults = knowledgeRepository
    .findSimilarKnowledgeByHybridRRF(
        candidate.refinedText(), 
        vectorStr, 
        keywordId, 
        20  // 충분한 후보 확보
    );

// Step 3: Merge & Filter
// - Same-Keyword는 무조건 포함 (distance = 0.0)
// - RRF 결과는 Threshold 필터링 후 중복 제거하여 추가
List<KnowledgeSearchResult> mergedSimilars = mergeSimilarResults(
    sameKeywordItems, 
    filteredRrfResults, 
    keyword
);
```

**핵심 개선점**:
- **Same-Keyword 우선 보장**: `findByKeywordId`로 같은 Keyword 지식을 먼저 가져와 `distance=0.0`으로 설정하여 최우선 순위 부여.
- **다양한 후보 확보**: RRF로 최대 20개 검색 후 Threshold 필터링하여 품질 유지.
- **중복 제거**: Same-Keyword와 RRF 결과를 병합하되, ID 중복은 제거.

##### 2. **AI Server 프롬프트 수정** (`prompts.py`)
```python
KNOWLEDGE_EVALUATION_PROMPT = """
당신은 지식 베이스 관리자입니다. 새로운 후보 지식과 기존 유사 지식들을 비교하여,
**각 기존 지식마다** UPDATE 또는 IGNORE 결정을 내려야 합니다.

[Decision Rules]
1. Keyword Compatibility: 같은 Keyword면 우선 UPDATE 고려
2. Conflict Check: 내용 모순 시 IGNORE
3. Value Assessment: 새로운 정보가 있으면 UPDATE

[Output Format]
{
  "results": [
    {
      "targetId": "123",
      "decision": "UPDATE",
      "finalContent": "...",  // UPDATE인 경우 병합된 텍스트
      "reasoning": "..."
    },
    {
      "targetId": "456",
      "decision": "IGNORE",
      "reasoning": "..."
    }
  ]
}
"""
```

**핵심 변경점**:
- **Single → Multi**: 1개 결과 → `results` 배열로 변경.
- **각 항목 독립 판단**: LLM이 문맥과 Keyword를 종합하여 각 Similar Item에 대해 개별 결정.
- **Keyword 우선순위 명시**: Prompt에 "같은 Keyword면 우선 고려" 규칙 추가.

##### 3. **Backend 처리 로직 수정** (`KnowledgeBatchService.java`)
```java
// 기존: 단일 결과 처리
if ("UPDATE".equals(evalResult.decision())) {
    updateKnowledge(targetId, finalContent);
}

// 변경: 다중 결과 순회 처리
for (EvaluationDecision decision : evalResult.results()) {
    if ("UPDATE".equals(decision.decision())) {
        Long targetId = Long.parseLong(decision.targetId());
        updateKnowledge(targetId, decision.finalContent());
        updatedCount++;
    } else {
        ignoredCount++;
    }
}
```

### 9.4. 결과 및 효과 (Results)
1. **UPDATE 검증 가능**: 같은 Keyword 지식이 항상 포함되므로, 의도한 업데이트 시나리오 테스트 가능.
2. **LLM 판단력 활용**: 검색 알고리즘의 한계를 LLM이 보완. 여러 후보 중 실제로 업데이트할 가치가 있는 것만 선택.
3. **유연성 향상**: 1개 제약 제거로 동시에 여러 지식을 업데이트하거나, 모두 IGNORE 가능.
4. **정확도 개선**: Keyword Context를 명시적으로 제공하여 LLM의 판단 근거 강화.

### 9.5. 트레이드오프 (Trade-offs)
- **비용 증가**: LLM에게 더 많은 정보를 전달하므로 Token 사용량 증가.
- **응답 시간**: 여러 항목 판단으로 인해 약간의 지연 발생 (하지만 `gemini-flash` 사용으로 완화).
- **복잡도**: Backend 로직이 단일 결과 처리에서 배열 순회로 변경되어 코드 복잡도 증가.

### 9.6. 향후 개선 방향 (Future Improvements)
- **Adaptive Candidate Count**: 검색 결과 품질에 따라 LLM에게 전달할 후보 수를 동적 조정.
- **Batch Evaluation**: 여러 Candidate를 한 번에 평가하여 API 호출 횟수 감소.
- **Confidence Score**: LLM이 각 결정에 대한 확신도를 반환하도록 하여 임계값 기반 필터링 가능.


## 10. `NameError: name 'settings' is not defined`
### 10.1. 원인 (Cause)
- **RunPod Client (`ai_server`)**: `app/core/config.py`의 `settings` 객체를 import하지 않고 사용하여 발생.
- **RunPod Worker (`stt_server`)**: `inference_service.py`에서 `config.py`의 `settings`를 import하지 않고 `settings.VAD_FILTER` 등을 참조하여 발생. 특히 로컬 테스트와 달리 RunPod 환경에서만 발생하여 발견이 늦음.

### 10.2. 해결 (Solution)
- **AI Server**: `runpod_client.py` 에 `from app.core.config import settings` 추가.
- **STT Server**: `inference_service.py` 에 `from config import settings` 추가.

## 11. Feedback JSON에 Markdown 포함 문제 (Prompt Engineering)
### 11.1. 문제 상황 (Problem)
- **현상**: AI가 생성한 피드백 JSON의 값(Value)에 `**bold**`나 `*italic*` 같은 마크다운 문법이 포함됨.
- **영향**: 프론트엔드에서 JSON을 파싱하여 UI에 표시할 때, 원치 않는 마크다운 기호가 그대로 노출됨.

### 11.2. 해결 (Solution)
- **프롬프트 개선**: `prompts.py`의 `BASE_SYSTEM_PROMPT`에 **"Strictly NO Markdown"** 규칙을 추가.
- **지시사항**: "JSON 내부의 값은 반드시 **평문(Plain Text)**이어야 하며, 볼드나 이탤릭 등을 절대 사용하지 말 것"을 명시.


---

## 12. Endpoint Error Handling Standardization

### 12.1. 문제 상황 (Problem)
- **일관성 부재**: API 별로 에러 응답 형식이 제각각이었음.
    - 일부는 `HTTPException` (FastAPI 기본) 사용.
    - 일부는 `JSONResponse(content={"error": ...})` 사용.
    - 일부는 Service Layer에서 `return {"status": "failed"}` 형태의 Raw Dict 반환.
- **Frontend 처리 어려움**: 클라이언트가 에러를 처리하기 위해 각 API마다 다른 로직을 구현해야 했음.
- **모호한 에러 코드**: `500 Internal Server Error`나 `400 Bad Request` 등 포괄적인 HTTP 상태 코드만으로는 구체적인 원인(예: "STT 타임아웃", "LLM 파싱 실패")을 파악하기 어려움.

### 12.2. 해결 (Solution)
**모든 API 응답을 표준화된 JSON 형식(`BaseResponse`)으로 통일하고, 중앙화된 에러 시스템 도입.**

#### 1. 표준 응답 스키마 정의 (`schemas/common.py`)
모든 응답은 아래 구조를 따름:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "STT_TIMEOUT",
    "message": "STT 작업이 타임아웃되었습니다.",
    "detail": { "timeout_seconds": 300 }
  }
}
```

#### 2. Core Error System (`core/errors.py`)
- **`ErrorCode` Enum**: 시스템 전반에서 사용하는 에러 코드를 한곳에서 관리 (`STT_FAILURE`, `INVALID_JSON`, `LLM_PROVIDER_ERROR` 등).
- **`AppException`**: 모든 비즈니스 로직 에러의 최상위 클래스. Service Layer에서는 이 예외를 발생시키기만 하면 됨.
    ```python
    # Service Layer 예시
    raise AppException(
        code=ErrorCode.STT_FAILURE,
        message="RunPod 통신 중 오류가 발생했습니다.",
        status_code=502
    )
    ```

#### 3. Global Exception Handlers (`core/exception_handlers.py`)
- **`AppException` 핸들러**: Service에서 던진 `AppException`을 잡아 표준 JSON 응답으로 변환.
- **`RequestValidationError` 핸들러**: Pydantic 유효성 검사 실패 시, 자동으로 분석하여 `MISSING_CONTEXT` 또는 `INVALID_JSON` 코드로 매핑.

#### 4. Service Layer 리팩토링 (Phase 2)
- **RunPod Client**: `HTTPException` 직접 발생 제거 → `AppException(STT_FAILURE/STT_TIMEOUT)` 사용.
- **Knowledge Service**: `ValueError` 문자열 매칭 제거 → `AppException(LLM_PROVIDER_ERROR)` 명시적 발생.
- **GPU Endpoint**: 임의의 Dict 반환 제거 → `create_error_response` 헬퍼 함수 사용.

### 12.3. 결과 (Result)
- **Frontend**: `response.data.success` 플래그 하나로 성공/실패 분기 가능하며, `error.code`를 통해 다국어 처리나 특정 에러 대응이 용이해짐.
- **Backend**: 에러 추가 시 `ErrorCode` Enum만 정의하고 `raise AppException`하면 되므로 유지보수성 향상.
- **Debugging**: `runpod_client` 등 외부 연동 구간의 에러가 명확한 코드(`STT_TIMEOUT`, `GPU_FAIL`)로 기록되어 문제 원인 파악이 빨라짐.


## 13. Solo Submission 빈 텍스트 400 에러 및 무한 대기 이슈

### 13.1. 문제 상황 (Problem)
- **현상 1 (API Error)**: 음성 인식(STT) 결과가 빈 문자열(`""`)일 때, `/api/v1/solo/submissions` 호출 시 **400 Bad Request** 에러 발생.
    ```text
    WARNING: Validation Error (ErrorCode.VALIDATION_ERROR):
    [{'field': 'body.userText', 'reason': 'String should have at least 1 character', 'type': 'string_too_short'}]
    INFO: "POST /api/v1/solo/submissions HTTP/1.0" 400 Bad Request
    ```
- **현상 2 (Backend Infinite Wait)**: Main Server(Spring Boot)는 AI Server에 요청을 보낸 후 비동기 응답(202 Accepted)을 기대하며 폴링(Polling) 로직에 진입하거나 대기 상태가 됨.
    - 하지만 AI Server가 400 에러를 즉시 반환하고 연결을 종료해버림.
    - Main Server는 **예상치 못한 400 응답에 대한 예외 처리가 미비**하여, "성공 응답이 올 때까지" 혹은 "타임아웃될 때까지" 계속 기다리는 **무한 대기(Hanging)** 상태에 빠짐.
    - 이로 인해 사용자 브라우저에서도 "분석 중..." 화면이 멈추지 않는 치명적인 UX 문제 발생.

### 13.2. 원인 분석 (Root Cause)
1.  **AI Server (FastAPI)**: `SoloSubmissionRequest` 스키마의 `min_length=1` 제약으로 인해 빈 텍스트 수신 시 **즉시 400 에러**를 리턴하고 비즈니스 로직(Task 생성)을 실행하지 않음.
2.  **Main Server (Spring Boot)**: AI Server 호출 시 `2xx` 응답이 아닌 `4xx` 에러가 왔을 때, 이를 "작업 실패"로 간주하고 즉시 중단하는 로직이 누락되었거나, `WebClient`/`FeignClient`가 에러를 삼키고 재시도(Retry)를 반복하는 구조였을 가능성.

### 13.3. 해결 (Solution)
**AI Server 측면에서 근본 해결**:
- `min_length=1` 제약을 **제거**하여 빈 문자열도 정상 요청으로 접수(202)되도록 변경.
- 이를 통해 Main Server는 항상 202 응답을 받고 정상적인 Polling 프로세스를 진행할 수 있게 됨.
- AI Server 내부 로직(`analysis_service`)에서 텍스트 길이를 체크하여 **0점 처리(COMPLETED)**를 수행하므로, Main Server는 Polling 중 "완료" 상태를 감지하여 정상 종료 가능.

```python
# 변경 후 (app/schemas/solo.py)
user_text: str = Field(..., alias="userText", ...)
```

### 13.4. 안전성 분석 (Safety Analysis)
#### ✅ 안전한 이유: Defense-in-Depth (다층 방어)
빈 문자열이 스키마를 통과하더라도, 서비스 레이어에서 안전하게 처리됨:

| 단계 | 위치 | 동작 |
|------|------|------|
| ① API Layer | `endpoints/solo.py` | 빈 문자열 수신 → 202 Accepted (즉시 접수) |
| ② Background Task | `analysis_service.py` (Line 43) | `len(user_text.strip()) < 5` 체크 → LLM 호출 **건너뜀** |
| ③ Result | `task_store` | `COMPLETED` 상태로 0점 + 안내 피드백 저장 |

- **Main Server 안정성 확보**: 이제 Main Server는 예외 상황(빈 텍스트)에서도 정상적인 분석 완료 응답을 받을 수 있어 무한 대기 문제가 해결됨.
- **LLM 비용 절감**: 5글자 미만은 API 호출 없이 처리됨.
- **예외 처리 간소화**: Main Server가 별도의 400 에러 핸들링 로직을 복잡하게 구현할 필요 없이, 표준 프로세스대로 처리 가능.

### 13.5. 변경된 API 동작 비교

| 입력 | 변경 전 | 변경 후 |
|------|---------|---------|
| `"userText": ""` | ❌ 400 Bad Request → **Main Server 무한 대기** | ✅ 202 Accepted → 0점 완료 (정상 종료) |
| `"userText": "안녕"` (1~4자) | ✅ 202 Accepted → 0점 | ✅ 202 Accepted → 0점 |
| `"userText": "프로세스란..."` (5자+) | ✅ 202 Accepted → 정상 분석 | ✅ 202 Accepted → 정상 분석 |
