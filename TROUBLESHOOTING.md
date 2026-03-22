# 트러블 슈팅 로그 (Troubleshooting Log)

**RunPod Serverless 기반 Whisper AI 서버** 구축 과정에서 발생한 주요 문제점과 해결 방법을 기록.

---

## 1. 코드 및 의존성 이슈 (Code & Dependencies) [2026-01-21]

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

## 2. Docker 빌드 및 배포 이슈 (Docker Build & Deploy) [2026-01-21]

### 2.1. PyAV 빌드 실패 (`pkg-config` 누락)
- **문제상황**: Docker 빌드 중 `faster-whisper`의 의존성인 `av` 패키지 설치 실패 (`subprocess-exited-with-error`).
- **원인**: Base Image에 `ffmpeg` 개발 라이브러리와 `pkg-config`가 없어 소스 빌드가 불가능했음.
- **해결**: `Dockerfile`에 `pkg-config`, `libavformat-dev`, `libavcodec-dev` 등 필수 개발 패키지 설치 구문 추가.

### 2.2. CUDA 버전 불일치 (`libcublas.so.12`)
- **문제상황**: RunPod에서 `Library libcublas.so.12 is not found` 에러 발생.
- **원인**: `faster-whisper`(CTranslate2)는 **CUDA 12**를 요구하나, Docker Base Image가 **CUDA 11.8** 버전이었음.
- **해결**: Base Image를 `runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04` (CUDA 12.1 지원)로 변경.

---

## 3. RAG (Knowledge System) 구현 이슈 [2026-01-28]

### 3.1. API Key 로딩 시점 문제 (Standalone Script)
- **문제상황**: FastAPI 앱 구동 시에는 문제가 없으나, 독립 스크립트(`verify_rag_core.py`) 실행 시 `GEMINI_API_KEY`를 찾지 못함.
- **원인**: `app/core/config.py`의 `Settings` 객체가 `load_dotenv()` 호출 전에 초기화되어, 환경변수 파일(.env)의 값을 읽어오지 못함 (Pydantic Settings 캐싱 특성).
- **해결**: `KnowledgeService.__init__` 메서드 내에 **방어 코드** 추가. `settings.GEMINI_API_KEY`가 비어있을 경우, 명시적으로 `.env` 파일을 찾아 다시 로드(`reload`)하고 값을 주입하도록 수정.

## 4. 성능 및 지연 시간 (Latency) 이슈 [2026-01-28]

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


## 5. 보안 강화: 내부 인증 도입 (Internal Secret) [2026-01-29]
- **배경**: AI 서버 API가 외부에 노출될 경우 무분별한 요청이나 오남용을 방지하기 위해 최소한의 인증 장치가 필요.
- **조치**: 
    - `main.py`에 Middleware를 추가하여 모든 요청(Health Check 제외)에 대해 `x-internal-secret` 헤더를 검증하도록 변경.
    - 환경 변수 `INTERNAL_SECRET_KEY`를 통해 비밀키를 관리.



## 6. API Access Denied (403 Forbidden) [2026-01-29]
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

## 7. Embedding Model Resource Crash (Server OOM) [2026-01-30]

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


## 8. STT Hallucination (환각) 이슈 [2026-02-08]

Whisper 모델 사용 시, 실제 음성에 없는 텍스트가 생성되는 환각 현상이 발생. 주요 원인은 다음과 같음.

### 8.1. 데이터 편향에 의한 연상 작용 (Association-based Hallucination)
- **현상**: 비디오의 시작, 끝, 혹은 배경음악만 나오는 구간에서 "시청해 주셔서 감사합니다(Thanks for watching)", "자막 제공: Amara.org", "좋아요와 구독 부탁드립니다" 등의 문구가 생성됨.
- **원인**: Whisper 모델은 인터넷 영상 자막으로 학습됨. 학습 데이터에서 이러한 문구가 배경 소음(White Noise)이나 침묵 구간과 통계적으로 강하게 연결(Mapping)되어 있기 때문에, 정적 노이즈를 자막 크레딧 타이밍으로 오인하여 생성.

### 8.2. 디코더의 자기 회귀적 루프 (Autoregressive Looping)
- **현상**: 특정 단어가 무한 반복되거나 문맥에 맞지 않는 엉뚱한 문장이 생성됨.
- **원인**: Transformer 디코더는 이전 토큰을 기반으로 다음 토큰을 생성함. 침묵 구간에서 모델이 불확실성 속에 임의의 잘못된 토큰을 하나 생성하면, 이것이 다음 스텝의 입력이 되어 오류가 증폭됨. 모델은 이 오류를 정당화하기 위해 억지스러운 문맥을 이어가거나 루프(Loop)에 빠지게 됨.

[STT응답](https://www.notion.so/STT-hallucination-2fa1715a156080469f59f57df1eed8ce?source=copy_link)

---

## 9. Knowledge Evaluation: Single-Target → Multi-Decision 전환 [2026-02-08]

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


## 10. `NameError: name 'settings' is not defined` [2026-02-08]
### 10.1. 원인 (Cause)
- **RunPod Client (`ai_server`)**: `app/core/config.py`의 `settings` 객체를 import하지 않고 사용하여 발생.
- **RunPod Worker (`stt_server`)**: `inference_service.py`에서 `config.py`의 `settings`를 import하지 않고 `settings.VAD_FILTER` 등을 참조하여 발생. 특히 로컬 테스트와 달리 RunPod 환경에서만 발생하여 발견이 늦음.

### 10.2. 해결 (Solution)
- **AI Server**: `runpod_client.py` 에 `from app.core.config import settings` 추가.
- **STT Server**: `inference_service.py` 에 `from config import settings` 추가.

## 11. Feedback JSON에 Markdown 포함 문제 (Prompt Engineering) [2026-02-09]
### 11.1. 문제 상황 (Problem)
- **현상**: AI가 생성한 피드백 JSON의 값(Value)에 `**bold**`나 `*italic*` 같은 마크다운 문법이 포함됨.
- **영향**: 프론트엔드에서 JSON을 파싱하여 UI에 표시할 때, 원치 않는 마크다운 기호가 그대로 노출됨.

### 11.2. 해결 (Solution)
- **프롬프트 개선**: `prompts.py`의 `BASE_SYSTEM_PROMPT`에 **"Strictly NO Markdown"** 규칙을 추가.
- **지시사항**: "JSON 내부의 값은 반드시 **평문(Plain Text)**이어야 하며, 볼드나 이탤릭 등을 절대 사용하지 말 것"을 명시.


---

## 12. Endpoint Error Handling Standardization [2026-02-09]

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


## 13. Solo Submission 빈 텍스트 400 에러 및 무한 대기 이슈 [2026-02-10]

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

## 14. STT Hallucination 및 무음 처리 개선 [2026-02-10]

### 14.1. 문제 상황 (Issue)
- **증상**: 오디오의 무음 구간이나 잡음 구간에서 "MBC 뉴스", "시청해 주셔서 감사합니다" 등의 뜬금없는 텍스트(Hallucination)가 생성됨.
- **원인**: Whisper 모델의 특성상 침묵 구간에서 언어 모델의 확률 분포가 높은 상용구(훈련 데이터 편향)를 생성하려는 경향이 있음.

### 14.2. 해결 방안 (Solution)
`4-team-IMYME-ai/stt_server`에 VAD(Voice Activity Detection)를 적용하고, 침묵 감지 로직을 강화하여 무음 구간의 입력을 원천 차단함.

#### 적용된 기술적 조치
1.  **VAD 활성화 (`VAD_FILTER = True`)**
    *   `faster-whisper` 내장 Silero VAD를 사용하여 음성이 아닌 구간을 전사 전에 필터링.
2.  **침묵 임계값 강화**
    *   `min_silence_duration_ms = 500`: 0.5초 이상의 침묵은 과감히 제거 (기본값보다 엄격하게).
    *   `no_speech_threshold = 0.4`: 모델이 "침묵"이라고 판단하는 확률 기준을 낮춰 민감하게 반응하도록 설정 (기본값 0.6 → 0.4).
    *   `hallucination_silence_threshold = 2.0`: 2초 이상 침묵으로 판단된 구간에서 텍스트가 나오면 강제로 무시.
3.  **루프 방지 (`condition_on_previous_text = False`)**
    *   이전 문맥에 의존하지 않도록 하여, 한번 발생한 환각이 다음 문장으로 이어지는 반복(Loop) 현상 차단.
4.  **결정론적 추론 (`Temperature = 0.0`)**
    *   Random Sampling을 방지하여 모델이 불확실한 구간에서 창의적인 오답을 내놓지 못하게 고정.

### 14.3. 변경 파일
- `4-team-IMYME-ai/stt_server/config.py`: 파라미터 상수 정의.
- `4-team-IMYME-ai/stt_server/services/inference_service.py`: `model.transcribe()` 호출 시 파라미터 주입 로직 추가.

## 15. RunPod STT Timeout 및 RabbitMQ Queue 무한 대기 (Hang) 이슈 [2026-02-22]

### 15.1. 문제 상황 (Problem)
- **증상**: 로컬 환경에서 PvP E2E 테스트를 진행할 때, 특정 상황(예: 유효하지 않은 오디오 URL 전달, RunPod 서버 지연 등)에서 STT Worker가 전혀 응답하지 않고 **영원히 멈춰있는(Hang) 현상** 발생.
- **영향**: RabbitMQ 큐(`pvp.stt.request`)에 쌓인 메시지가 처리되지 않은 상태(Unacked)로 계속 머물러 있어, 전체 파이프라인의 데드락을 유발함.

### 15.2. 원인 분석 (Root Cause)
- Python의 `requests` 라이브러리는 HTTP 통신을 수행할 때 `timeout` 파라미터를 명시하지 않으면, 서버가 연결을 끊어주지 않는 한 **무한정 응답을 기다리게 됨**.
- AI Server의 `runpod_client.py`에서 RunPod API로 작업 요청(`requests.post`) 및 상태 확인(`requests.get`)을 보낼 때 타임아웃 셋팅이 누락되어 있었음.

### 15.3. 해결 방안 (Solution)
모든 RunPod 외부 API 호출부에 **명시적인 Timeout(예: 60초)**을 추가하여 무한 루프를 방지.

```python
# 수정 전 (app/services/runpod_client.py)
response = requests.post(run_url, headers=self.headers, json=payload)

# 수정 후: 60초 타임아웃 추가
response = requests.post(run_url, headers=self.headers, json=payload, timeout=60)
```

**효과**: RunPod 서버가 60초 내에 응답하지 않으면 코드에서 즉시 `requests.exceptions.Timeout` 예외를 발생시킴. 이를 통해 STT Worker의 기본 에러 핸들링 로직이 작동하여, 해당 요청을 건너뛰고 큐 메시지를 정상적으로 실패(`.status = "FAIL"`)로 후처리할 수 있게 됨.

## 16. RabbitMQ DLQ 및 3회 재시도(Retry) 작동 불능 방지 [2026-02-23]

### 16.1. 문제 상황 (Problem)
- **증상**: 일시적인 네트워크 오류나 RunPod 지연이 발생했을 때, 메시지가 RabbitMQ의 재시도 큐(Retry Queue)를 통해 3번 재시도되지 않고 **단 1회 실패 후 즉시 종료(FAIL 발행)**됨.
- **원인**: Worker (`stt_worker.py`, `feedback_worker.py`) 코드 내부에 `try...except Exception as e:` 블록이 존재하여, 모든 예외를 스스로 먹고(Swallow) 직접 FAIL 응답을 쏜 뒤 함수를 정상 종료해버림. 이로 인해 인프라 레이어(`rabbitmq_service.py`)는 "작업이 성공적으로 끝났다"고 착각하고 메시지를 `Ack` 처리하여 재시도/DLQ 로직이 완전히 무력화됨.

### 16.2. 해결 방안 (Solution)
Worker에서 에러를 덮어두지 않고, 예외를 명시적으로 던져(Raise) **RabbitMQ 서비스 레이어로 에러 핸들링을 위임**하는 구조로 전면 개편.

1. **Worker 레이어 개편 (Exception Propagation)**
    - 워커의 비즈니스 로직을 감싸던 `try/except` 블록을 제거.
    - 비즈니스/네트워크 예외 발생 시 Python의 기본 예외 전파(Propagation)를 통해 콜백 바깥으로 튕겨나가게 함.

2. **RabbitMQ 인프라 레이어 보강 (`rabbitmq_service.py`)**
    - `on_message` 핸들러의 `except Exception` 블록에서 에러를 캐치.
    - **1~2차 실패**: 메시지를 `reject(requeue=False)`하여 5초 TTL이 걸린 재시도 큐로 라우팅.
    - **3차 최종 실패 (`retry_count >= 2`)**: 
        - 원본 메시지를 DLQ(`pvp.match.dlq`)로 이동 보관하여 추후 원인 분석 및 재처리 지원.
        - 매칭이 무한 로딩에 빠지지 않도록 3번째 실패 시점에만 메인 서버로 `FAIL` 전문을 즉시 조립하여 Publish (`pvp.stt.response` 등).

### 16.3. 효과 (Result)
- 일시적 장애 발생 시 최대 3번(10초)까지 인프라 복원력을 확보하여 **억울한 FAIL 응답 감소**.
- 에러 원본 페이로드가 파괴되지 않고 DLQ에 보존되어 **개발자 디버깅(Replay) 편의성 극대화**.


## 17. LLM-as-a-Judge 위치 편향(Positional Bias) 및 Logprobs 추출 이슈 [2026-02-25]

### 17.1. 문제 상황 (Problem)
- **증상 1 (위치 편향)**: 두 개의 답변(A, B)을 비교 평가하는 프롬프트에서, `gemini-2.5-flash` 모델이 **실제 품질과 무관하게 항상 두 번째(B) 혹은 첫 번째(A) 위치의 답변을 승자로 선택**하는 극단적인 위치 편향(Positional Bias) 현상이 확인됨.
- **증상 2 (Logprobs 추출 실패)**: 편향을 수학적으로 교정하기 위해 PAIRS(Pairwise-preference Search) 기법을 도입하여 토큰 확률(logprobs)을 추출하려 했으나, 일반 API Key 환경에서는 `Logprobs is not enabled` 에러가 발생.
- **증상 3 (Thinking 토큰 충돌)**: Vertex AI로 전환 후, 출력 토큰을 1개로 제한(`max_output_tokens=1`)하여 정답("1" 또는 "2")의 확률만 추출하려 했으나, 최신 Flash 모델들의 사전 내부 추론(Thinking) 기능이 발동되어 첫 토큰으로 `<thought>` 등을 출력하다가 잘려버림. 이로 인해 결과 텍스트가 빈 문자열(`EMPTY`)로 반환되고 필요한 logprobs를 얻지 못함.

### 17.2. 원인 분석 (Root Cause)
1. **API 권한**: Gemini 모델의 `logprobs` 기능은 철저히 **Google Cloud Vertex AI** 환경 전용으로 제한되어 있었음.
2. **디코딩(Decoding) 간섭**: `max_output_tokens=1` 방식은 모델의 생성 "길이"만 자를 뿐, 모델이 어떤 단어를 선택할지(확률 공간)는 제어하지 못함. "Thinking" 모델들은 본능적으로 추론 토큰을 먼저 생성하려 하므로, 길이가 1로 제한된 상태에서는 정답 토큰("1", "2")에 도달하기 전에 응답이 강제 종료됨.

### 17.3. 해결 방안 (Solution)
**Constrained Decoding (제약 기반 디코딩) 및 Vertex AI 도입**

1. **Vertex AI 클라이언트로 마이그레이션**:
   - `google.genai` SDK 사용 및 `genai.Client(vertexai=True, project=..., location=...)` 로 초기화.
   - 호환성을 위해 `gcloud auth application-default login`을 통해 로컬 인증 자격 증명(ADC) 설정.

2. **Enum Schema를 통한 출력 제약 (Constrained Decoding)**:
   - `max_output_tokens=1` 옵션을 제거하고, **공식 권장 방식인 `text/x.enum` 스키마 제약**으로 전면 교체.
   ```python
   # 수정 후: 스키마를 통해 출력 풀(Pool)을 아예 "1", "2"로 물리적 격리
   config = types.GenerateContentConfig(
       response_mime_type="text/x.enum",
       response_schema={"type": "STRING", "enum": ["1", "2"]},
       response_logprobs=True,
       logprobs=5
   )
   ```
   - **원리**: 모델의 예측 확률 공간 자체를 `["1", "2"]` 두 단어로 강제 제한함. 모델은 내부 추론(`<thought>`)을 하고 싶어도 해당 토큰이 허용되지 않으므로, 추론 과정을 건너뛰고 즉각적으로 "1" 또는 "2"에 대한 Logprob을 계산하여 반환하게 됨.

### 17.4. 결과 및 효과 (Results)
- **Logprob 정상 추출**: `gemini-3-flash-preview` 등 최신 Thinking 모델에서도 에러나 빈 응답 없이 "1"과 "2"의 토큰 확률 데이터를 안정적으로 얻어냄.
- **편향의 원천 차단 (Surprise Finding)**: Enum Schema로 디코딩을 강하게 제약한 결과, 원래 순서와 무관하게 2번을 뽑던 편향 모델이 **Raw 텍스트 판정 단계에서부터 편향 없이 항상 더 나은 정답을(100%) 고르는 부수적인 효과(Debiasing Effect)**까지 달성함.
- **최종 보정**: 추출된 Logprobs를 Softmax 정규화 및 양방향[A-B, B-A] 평균 교정(Bradley-Terry Model)에 사용하여, $\approx 99.7\%$의 매우 안정적이고 신뢰도 높은 확신 점수(Confidence Score)를 확보.


## 18. RabbitMQ 통신 포트 인지 오류(Dev vs Release) 및 시작 순서 불일치 [2026-02-27]

### 18.1. 문제 상황 (Problem)
- **증상 1 (15671 포트 큐 0개)**: 로컬 PC 브라우저에서 `15671` 포트로 관리 UI에 접속했으나, 생성되어 있어야 할 큐가 하나도 없는 빈 상태(0개)로 조회됨. 이때 이를 **Dev 서버의 MQ**라고 착각함.
- **증상 2 (15672 포트 접속 불가)**: 실제 Dev 서버의 MQ인 `15672` 포트로 외부망에서 다이렉트 접속을 시도하면 연결이 원천 차단되어 흰 화면(접속 불가)이 뜸.
- **증상 3 (CONNECTION_FORCED 에러 루프)**: 동시에 AI 서버 측 로그에서는 `CONNECTION_FORCED` 에러로 기존 연결이 끊어진 직후, `[Errno 111] Connect call failed ('127.0.0.1', 5672)` 에러가 발생하며 수 초 간격으로 엠큐 연결 재시도를 무한 반복함.

### 18.2. 원인 분석 (Root Cause)
이 현상들은 **"클라우드 인프라 망 분리(VPC) 특성에 대한 혼동"**과 **"프로세스 기동 타이밍 불일치"**가 복합적으로 얽힌 결과임.

1. **증상 1(15671 큐 0개) 원인 (Optical Illusion)**: 
   - 사용자가 AWS SSM 포트 포워딩(`15671:15671`)을 타고 접속한 타겟(`b-afe39155...mq.ap-northeast-2.on.aws`)은 Dev 서버가 아니라 **운영망(Release) 전용으로 띄워진 Amazon MQ**였음.
   - 현재 테스트 중인 AI 파이썬 프로세스('.env')는 Release Amazon MQ가 아니라, 자기 컴퓨터 내부에 떠있는 **Dev 도커 엠큐(`localhost:5672`)**를 바라보며 큐를 생성하고 있었음. 즉, '가' 서버(Dev)에 큐를 만들어두고 '나' 서버(Release 15671) 창을 열어보며 큐가 없다고 착각하는 해프닝이었음.
2. **증상 2(15672 접속 불가) 원인 (Network Isolation)**:
   - 우분투 서버 호스트에 띄워진 Dev RabbitMQ 도커 컨테이너는 보안을 위해 포트 바인딩이 `127.0.0.1:15672->15672/tcp`로 설정되어 있었음. 
   - 이 설정은 **오직 서버의 호스트 내부(`localhost`)에서만 접근을 허용**하므로, 외부 인터넷 망(개발자의 Mac/PC 브라우저)에서 해당 서버의 공인/사설 IP + 15672 포트로 직접 찔러 들어가는 트래픽은 도커 네트워크/방화벽에 의해 정상적으로 차단된 것임.
3. **증상 3(재연결 무한 루프 에러) 원인 (Startup Order Mismatch)**:
   - 우분투 OS(호스트)에 네이티브로 직접 실행되는 AI 파이썬 프로세스와, 도커(Docker)로 실행되는 RabbitMQ 컨테이너 간의 **"재시작 순서(Timing) 불일치"**가 핵심 원인임.
   - RabbitMQ 도커가 어떤 이유(재배포 등)로 컨테이너를 재시작하면서 기존 세션을 강제로 날려버려 `CONNECTION_FORCED` 에러가 발생함.
   - 직후 AI 서버의 `aio_pika` 라이브러리는 강제로 끊어진 세션을 복구하기 위해 `localhost:5672`를 미친 듯이 찌르며 재연결을 시도했지만, 도커 안의 엠큐가 부팅을 마치고 완전히 준비 상태(`healthy`)가 되기도 전에 시도했으므로 `Connect call failed` (연결 거부)가 발생함.

### 18.3. 해결 방안 (Solution)

1. **Dev/Release 엔드포인트 혼동 인지 (15671 관측 오류 해결)**: 
   - `15671` SSM 터널링은 **Release 환경 모니터링 전용**임을 팀 내 개발자들에게 명확히 인지시킴.
   - Dev 서버 통신 테스트를 할 때는 반드시 아래 2번 방법을 사용해 도커 내부 엠큐(`15672`)를 모니터링해야 함.
2. **안전한 Dev 관리 UI 접속 (SSH 터널링)**: 
   - 도커 컨테이너의 보안 호스트 바인딩(`127.0.0.1:15672`)을 해제해 퍼블릭으로 뚫는 것은 위험함. 바인딩을 그대로 유지하되, 개발자의 로컬 PC에서 **SSH 터널링(Port Forwarding)**을 사용하여 캡슐화된 암호 파이프를 뚫어 호스트 내부망으로 우회 접속해야 함.
   ```bash
   # 로컬 PC 터미널에서 실행 (pem 키가 필요한 경우 -i 옵션 추가)
   ssh -L 15672:localhost:15672 사용자계정@서버IP주소
   ```
   이후 로컬 PC 브라우저에서 `http://localhost:15672` 로 접속하면, 방화벽을 뚫고 도커 내부의 진짜 Dev 큐 구조가 담긴 찐 UI 화면을 안전하게 열람할 수 있음.
3. **서비스 시작 순서 논리적 보장 (Shutdown Error 방지)**: 
   - **타이밍 제어**: AI 서버 파이썬 프로세스는 항상 **RabbitMQ 도커 컨테이너 상태가 완전히 `healthy`**이거나 최소한 5672 포트가 리스닝(Listening) 상태가 되었을 때 후행적으로 재시작 하도록 **"스타트업 순서(Startup Sequence) 보증 스크립트"**를 도입하여 연결 무한 실패를 방지함.

## 19. Pydantic 스키마 불일치로 인한 STT 메시지 전량 Reject [2026-02-27]

### 19.1. 문제 상황 (Problem)
- **증상**: RabbitMQ 연결이 정상화된 후, 메인 서버(Spring Boot)가 `pvp.stt.request` 큐로 보낸 메시지가 AI 서버의 Pydantic 검증 단계에서 전량 Reject 처리됨. 3회 재시도 후 DLQ로 이동.
    ```
    ERROR: 3 validation errors for STTRequest
    match_id
      Field required [input_value={'room_id': 27, 'user_id': 1, ...}]
    user_id
      Input should be a valid string [input_value=1, input_type=int]
    file_url
      Field required [input_value={'room_id': 27, 'user_id': 1, ...}]
    ```

### 19.2. 원인 분석 (Root Cause)
AI 서버의 Pydantic 스키마(`pvp_schema.py`)와 메인 서버(Spring Boot)의 DTO 정의가 서로 다른 버전의 규격서를 참조하고 있었음. 양측 간 최종 스키마 동기화(Sync-up) 과정이 누락되어, 운영 환경에서 처음으로 통신할 때 불일치가 발견됨.

| 필드 | AI 서버 (기존 코드) | 메인 서버 (실제 전송) | 불일치 |
|------|---------------------|----------------------|--------|
| 매치/방 ID | `match_id: str` | `room_id: int` | ❌ 키 이름 + 타입 |
| 사용자 ID | `user_id: str` | `user_id: int` | ❌ 타입 |
| 오디오 URL | `file_url: str` | `audio_url: str` | ❌ 키 이름 |
| 모범 답안 | `modelAnswer: str` | `model_answer: str` | ❌ camelCase vs snake_case |

### 19.3. 해결 방안 (Solution)
메인 서버의 실제 전송 형식을 기준으로 AI 서버 코드를 전면 리팩토링 (9개 파일 수정).

| # | 파일 | 변경 내용 |
|---|------|----------|
| 1 | `app/schemas/pvp_schema.py` | Pydantic 모델 전면 수정 (필드명, 타입, 구조) |
| 2 | `app/workers/stt_worker.py` | `room_id`, `audio_url` 참조 변경 |
| 3 | `app/workers/feedback_worker.py` | `room_id`, `feedbacks` 배열 구조 반영 |
| 4 | `app/services/rabbitmq_service.py` | FAIL 응답 `room_id` 반영, `feedbacks:null` 추가 |
| 5 | `app/services/pvp_feedback_service.py` | 반환 구조 배열화, 필드명 전면 교체 |
| 6-9 | `tests/services/test_*.py` (4개) | 테스트 데이터 & assertion 수정 |

**주요 스키마 변경 사항**:
- `match_id` (str) → **`room_id` (int)**
- `user_id` (str) → **`user_id` (int)**
- `file_url` (str) → **`audio_url` (str)**
- `modelAnswer` → **`model_answer`** (snake_case 통일)
- Feedback Response: `feedback` (객체 `{user_A, user_B}`) → **`feedbacks` (배열 `[{...}, {...}]`)**
- `summarize` → **`summary`**, `keyword` → **`keywords`**, `personalized` → **`personalized_feedback`**



## 20. RabbitMQ 큐 생성 주체 충돌 및 누락 이슈 (PRECONDITION_FAILED / NotAvailable) [2026-03-01]

### 20.1. 문제 상황 (Problem)
- **증상 1 (과거 - PRECONDITION_FAILED)**: AI 서버와 메인 서버가 각각 큐 생성을 시도하다가, 큐 속성(Durable 등) 불일치로 인해 보안 위반(`406 PRECONDITION_FAILED`) 에러가 발생하며 서버가 다운됨.
- **증상 2 (현재 - QueuesNotAvailableException)**: 충돌을 피해 "AI 서버만 큐를 생성"하도록 규칙을 변경했으나, 이번에는 AI 서버가 켜지기 전 메인 서버가 먼저 배포(CD)되어 기동될 때 자신이 구독해야 할 `pvp.stt.response` 큐가 없는 것을 보고 예외를 던지며 메인 서버의 Health Check가 실패(다운)함.

### 20.2. 원인 분석 (Root Cause)
- **큐 생성의 멱등성 한계**: RabbitMQ에서 큐 생성(`declare`)은 이미 존재하더라도 옵션이 100% 동일하면 무시되지만, 양측 라이브러리(Java Spring vs Python aio_pika)의 디폴트 설정 차이 유무가 충돌을 일으켰음.
- **메시징 아키텍처 원칙 위배**: AI 서버는 자기가 수신(Consume)할 5개의 큐만 생성하고 발행(Publish)할 큐는 생성하지 않음. 반면 메인 서버는 자기가 수신(Consume)해야 할 큐의 생성을 AI에게 떠넘김. 결과적으로 메인 서버 수신용 큐 2개는 아무도 생성하지 않는 사각지대에 놓임. Consumer는 대상 큐가 물리적으로 존재해야만 Bind/Listen을 시작할 수 있으므로 치명적 구조 결함 발생.

### 20.3. 해결 방안 (Solution)
**"자기가 구독(Consume)해서 읽어갈 큐는 자기가 뜰 때 스스로 만든다"** 원칙 도입.
메인 서버(`4-team-IMYME-be`)의 RabbitMQ 설정 클래스에 다음 2개의 큐와 바인딩을 명시적으로 선언(Declare)하도록 코드 수정 지시.

1. **`pvp.stt.response` 큐 생성 및 바인딩**
2. **`pvp.feedback.response` 큐 생성 및 바인딩**

### 20.4. 핵심 주의사항 (PRECONDITION_FAILED 재발 방지)
과거의 충돌을 피하기 위해, 메인 서버가 응답 큐를 선언할 때 AI 서버(생산자)가 기대하는 스펙과 **단 하나의 속성도 어긋나면 안 됨.**
- **Durable (영속성)**: 반드시 `true` 유지 (`QueueBuilder.durable(...)` 등 사용).
- **Auto-delete, Exclusive**: 모두 기본값(`false`).
- **Dead Letter Exchange (DLX)**: 응답 큐(`*.response`)에는 별도의 DLQ 라우팅 등 임의의 Arguments 추가 절대 금지.

## 21. RabbitMQ 접속 URL 파싱 오류 및 .env 갱신 이슈 [2026-03-01]

### 21.1. 문제 상황 (Problem)
- **증상 1 (Invalid URL Error)**: AI 서버를 기동하거나 재시작했을 때, RabbitMQ 통신 모듈 초기화 중 다음과 같은 경고가 뜨며 큐 생성이 진행되지 않음.
    ```text
    WARNING:imyme-ai-server:RabbitMQ connection failed: Invalid URL: port can't be converted to integer. PvP workers disabled.
    ```
- **증상 2 (설정 변경 미반영)**: 비밀번호나 URL 오타를 눈치채고 서버 호스트의 `.env` 파일을 수정 후 `docker restart imyme-ai-server`를 했음에도 불구하고, 여전히 동일한 에러가 발생하며 서버의 모델 다운로드/초기화 로그가 보이지 않음.

### 21.2. 원인 분석 (Root Cause)
1. **증상 1 원인 (특수문자 URL 파싱 충돌)**
   - RabbitMQ 주소(`amqps://아이디:비밀번호@호스트:포트`)를 설정할 때, 비밀번호에 포함된 **특수문자(`#`, `!` 등)** 가 URL 예약어로 파싱되어 발생한 문제.
   - 특히 `#` 기호는 URL 프래그먼트(Fragment)로 인식되어, 뒤에 오는 호스트와 포트 문자열 전체가 잘려 나가면서 "포트를 정수형으로 변환할 수 없다"는 에러가 발생함.
2. **증상 2 원인 (Docker Environment Caching)**
   - Docker Container는 최초 실행(Create) 시점에 `.env` 파일의 변수들을 내부 메모리 환경변수로 주입받고 캐싱함.
   - 단순한 `docker restart` 명령어는 완전히 죽은 컨테이너를 방금 전 상태 그대로 다시 깨울 뿐, 호스트 운영체제의 `.env` 파일 변경 사항을 새로 읽어들이지 않음.

### 21.3. 해결 방안 (Solution)

#### 1단계: 비밀번호 URL 인코딩 적용
`.env` 파일에 접속 문자열을 기재할 때, 비밀번호 내 특수문자를 반드시 URL 인코딩 방식(`%XX`)으로 치환해서 기재해야 함. (따옴표는 생략 가능)
자주 사용되는 특수문자 변환 목록:
- `@` ➜ `%40`
- `:` ➜ `%3A`
- `/` ➜ `%2F`
- `?` ➜ `%3F`
- `#` ➜ `%23`
- `!` ➜ `%21`
- `$` ➜ `%24`

```env
# 수정 전 (특수문자 원본 사용 시 구문 분석 오류 발생 가능성 높음)
RABBITMQ_URL=amqps://admin:P@ssw?rd!#123@b-afe...

# 수정 후 (정상 동작: 특수문자를 안전하게 인코딩)
RABBITMQ_URL=amqps://admin:P%40ssw%3Frd%21%23123@b-afe...
```

#### 2단계: `docker-compose`를 이용한 환경변수 주입 스크립트 실행
변경한 리눅스 서버의 `.env` 환경 변수가 기존 도커 컨테이너에 강제로 주입되게 하려면, 단순히 서비스를 재시작하는 것이 아니라 컨테이너를 파괴하고 새로 만들어야(Recreate) 함. 

```bash
# 운영서버 터미널에서 실행하여 컨테이너 재생성 (Downtime 약 5초 발생)
docker-compose up -d --force-recreate ai-server
```
이후 `docker logs -f imyme-ai-server` 명령어로 확인하면, RabbitMQ 큐 5장이 정상적으로 순차 선언되는 로그(Queue Declared...)를 확인할 수 있음.
## 22. AI 서버-메인 서버-프론트엔드 간 Naming Convention 충돌 및 프롬프트 제약 이슈 [2026-03-02]

### 22.1. 문제 상황 (Problem)
- **증상 1 (피드백 데이터 소실)**: 프론트엔드 화면에서 PvP 비교 피드백 결과가 빈 값으로 처리되며 "피드백이 존재하지 않습니다."라는 오류 메시지가 표출됨. AI 서버 로그 상으로는 분명히 피드백이 정상 생성되어 Main 서버로 넘어간 상태였음.
- **증상 2 (어색한 지시대명사)**: 화면에 출력된 코칭 문장 속에 "User A 측에서는..." 또는 "유저 B님은..." 과 같이, 서비스 화면에 노출되어서는 안 될 내부 식별자(프롬프트 변수명)가 텍스트에 그대로 섞여서 출력됨 ("상대방"이라는 자연스러운 호칭이 아님).

### 22.2. 원인 분석 (Root Cause)
두 증상은 각각 시스템 간 **"JSON 키 맵핑(명명 규칙) 변환 오류"**와 LLM의 **"맥락 치환 기능 결여"**가 원인이었음.

1. **증상 1 (피드백 소실) - Snake vs Camel 변환 누락**:
   - AI 서버는 Python 표준 스네이크 케이스인 `personalized_feedback` 이라는 키 이름으로 JSON을 생성하여 메인 서버로 전달함.
   - 메인 서버(Spring Boot)는 이를 DTO(`FeedbackResponseDto`)에서 정상적으로 매핑해 받았으나, 정작 DB의 JSON 컬럼에 밀어 넣고 프론트엔드에 다시 내려줄 때는 **자바 표준인 카멜 케이스 `personalizedFeedback`으로 임의 강제 변환**하여 응답해 버림.
   - 프론트엔드(React/Vue)는 과거 명세서에 적힌 스네이크 케이스나 예전 이름(`personalized`)만 찾고 있었기 때문에, 카멜 케이스로 탈바꿈된 필드를 찾지 못해 undefined 처리가 되어 빈 화면이 떴던 것.

2. **증상 2 (User A 노출) - 프롬프트 제약 조건 부족**:
   - `PVP_SYSTEM_PROMPT`에서 LLM에게 `{user_a_text}`, `{user_b_text}`라는 변수명에 담아 두 사람의 텍스트를 주입하면서, "이 둘을 비교해서 피드백을 써줘"라고만 지시했음.
   - LLM 입장에서는 이 두 사람을 지칭할 대명사가 필요하니, 프롬프트에 제공된 아이디인 "User A", "유저 B"를 아무 생각 없이 결과 텍스트 안에 그대로 사용해버림. (서비스 맥락상 이것이 화면에 그대로 나갈 것이라는 사실을 LLM은 알 수 없음)

### 22.3. 해결 방안 (Solution)

1. **API 명세 재동기화 (프론트엔드 조치)**:
   - DTO 변환 과정에서 카멜 케이스가 적용되는 Spring Boot의 특성을 인정하고, 프론트엔드 개발 파트에 **"PvP 결과 응답 JSON의 코칭 피드백 키값은 `personalizedFeedback` (카멜 케이스, F 대문자)을 사용해달라"**고 명세를 재정의/전달하여 데이터 소실을 해결함.

2. **프롬프트 엔지니어링 제약 추가 (AI 서버 조치)**:
   - AI 서버의 `PVP_SYSTEM_PROMPT` 내 `[Tone & Formatting Rules]` 섹션에 **CRITICAL(치명적) 수준의 강한 호칭 제약 조건**을 신설함.
   ```text
   2. **Naming (CRITICAL)**: NEVER output identifiers like "User A", "User B", "유저 A", or "사용자 B" in the feedback text. ALWAYS refer to the current user as "회원님" (You) and the other person as "상대방" (Opponent).
   ```
   - 이로써 LLM은 내부적으로 A와 B를 비교 계산하더라도, 사용자에게 보여줄 최종 텍스트를 인코딩할 때는 철저하게 "회원님은 ~하셨지만, 상대방은 ~했습니다." 식의 자연스러운 1:1 대화형 코칭 화법만 사용하도록 강제됨.


## 23. 오디오 임시 파일 확장자 하드코딩 결함 (STT 디버깅 사이드이펙트 예방) [2026-03-02]

### 23.1. 문제 상황 (Problem)
- **증상**: 클라이언트가 `.wav`, `.webm`, `.m4a` 등 다양한 확장자를 지닌 오디오 파일 URL을 STT 서버로 전송했을 때 기능 자체는 정상 동작하나, 컨테이너 내부에 임시 다운로드되는 파일의 이름표가 무조건 `*.mp3`로 강제 고정되어 저장됨.
- **영향**: 당장 에러를 유발하지는 않으나, 향후 오디오 메타데이터를 직접 읽어들여 2차 가공을 하거나 FFmpeg 기반 모델이 아닌 외부 VAD(Voice Activity Detection) 알고리즘과 직접 연동 시, 파일 확장자(`mp3`)와 실제 데이터 헤더 포맷이 불일치하여 원인을 찾기 힘든 파싱 에러(Corrupted File)를 유발할 수 있는 기술 부채임.

### 23.2. 원인 분석 (Root Cause)
- **ai_server (정상)**: 클라이언트와 통신하는 1차 검증용 `ai_server`의 API Endpoint (`transcription.py`) 에서는 `supported_formats` 배열을 통해 `.wav`, `.m4a`, `.webm` 등 9가지 포맷을 정상적으로 인지 및 허용하고 있었음.
- **stt_server (결함)**: 실제 오디오 스트림을 다운로드받아 파일로 저장하는 `stt_server`의 워커 모듈(`audio_loader.py`)에서 `tempfile.NamedTemporaryFile(suffix=".mp3")`라고 옵션을 하드코딩하여 쓰고 있었음. 
- **그동안 에러가 없었던 이유**: Whisper 모델 백엔드가 오디오를 메모리로 로드할 때 사용하는 FFMpeg 라이브러리가 겉표지 이름표(`.mp3`)를 무시하고 실제 바이너리 패킷 헤더를 확인하여 자동으로 정상 포맷으로 디코딩하는 기능이 있었기에 가능했던 우연의 일치였음.

### 23.3. 해결 방안 (Solution)
`stt_server`의 `audio_loader.py`에서 무분별한 `.mp3` 확장자 덧씌우기를 중단하고, 원본 URL에서 실제 확장자를 동적으로 파싱하여 정직하게 보존하도록 로직을 수정함.

```python
# 수정 전
with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:

# 수정 후: 쿼리스트링 제거 후 URL에서 순수 확장자 추출
clean_url = url.split("?")[0]
ext = os.path.splitext(clean_url)[1] or ".mp3"  # 확장자가 없을 때만 mp3 fallback

with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
```

**개선 효과**: 임시 파일의 명칭(`ext`)과 실제 데이터가 1:1로 일치하게 되어 디버깅 시 개발자 혼란이 사라지고, 다른 포맷 특화 라이브러리와의 연동 안정성을 사전 확보함.


## 24. 외부 API(RunPod STT) 호출의 완전 비동기(Async) 전환 [2026-03-02]

### 24.1. 문제 상황 (Problem)
- **증상**: 기존 AI 서버(`ai_server`)는 `requests` 라이브러리를 사용하여 RunPod(GPU 서버)에 STT 처리를 요청하는 **동기(Blocking)** 통신을 수행함.
- **기존의 꼼수 (Workaround)**: FastAPI의 비동기 이벤트 루프가 STT 응답 대기 시간(예: 10초) 동안 멈추는 것을 막기 위해, 호출부에 `asyncio.to_thread()`를 덧씌워 별도의 더미 스레드(Thread)로 요청을 던지는 방식을 사용 중이었음.
- **영향**: 요청이 몰릴 때마다 임시 스레드가 생성되어 서버 메모리와 컨텍스트 스위칭 비용이 증가하는 비효율이 존재함.

### 24.2. GPU 연산 특성과 비동기의 오해 (Misconception)
- **오해**: "통신을 비동기로 바꾸면 백엔드 GPU 연산도 병렬로 빨라지는 것 아닌가?"
- **진실 (Fact)**: GPU 상의 STT 추론 연산 시간 자체는 물리적으로 고정되어 있으며 전혀 빨라지지 않음. 이번 비동기 전환의 목적은 GPU 속도 향상이 아니라, 긴 연산 시간을 **"기다리는 AI 서버(FastAPI)의 효율성 극대화"**에 있음.

### 24.3. 해결 방안 (Solution)
`runpod_client.py`의 모든 핵심 메서드(`transcribe`, `_poll_status`, `warmup` 등)를 순수 비동기 기반인 `httpx.AsyncClient`로 전면 재작성함.

```python
# 수정 전 (동기 + 스레드 격리)
stt_result = await asyncio.to_thread(
    runpod_client.transcribe_sync, audio_url=request.audio_url
)

# 수정 후 (완전 비동기 - Non-Blocking)
stt_result = await runpod_client.transcribe(audio_url=request.audio_url)
```

**개선 효과 (Impact)**:
1. **스레드 오버헤드 제거**: 무거운 `asyncio.to_thread()` 래퍼를 제거하여 AI 서버의 리소스(메모리) 낭비를 원천 차단함.
2. **동시성(Concurrency) 극대화**: `await` 키워드를 만나는 순간, AI 서버는 응답을 멍하니 기다리지 않고 **즉시 제어권을 반환(Yield)**함. 대기하는 10여 초 동안 같은 이벤트 루프 내에서 수십 개의 다른 API 요청(웹소켓, DB I/O 등)을 멈춤 없이 병렬로 쳐낼 수 있게 됨 (Throughput 대폭 향상).
3. **폴링 최적화**: 2초 간격 리트라이 루프에서도 동기식 `time.sleep(2)`가 아닌 `await asyncio.sleep(2)`를 사용하여 대기 효율을 높임.

## 25. 챌린지 모드 동적 인원 랭킹 병합 알고리즘 설계 및 부전승(Promote) 처리 [2026-03-10 ~ 19]

### 25.1. 문제 상황 (Problem)
1. **고정 인원 한계**: 초기 챌린지 모드는 무조건 100명의 유저가 꽉 차야만 랭킹 알고리즘(PAIRS)이 일괄 동작하도록 설계되었음. 하지만 실제 서비스 환경에서는 네트워킹 지연, 이탈 등 다양한 요인으로 98명, 87명 등 유동적인 인원으로 게임이 시작되더라도 유연하게 동작해야 하는 요구사항이 발생함.
2. **동적 상황에서의 최종 레벨(Root Node) 붕괴**: 인원이 유동적으로 변하면 트리의 뎁스(Depth)가 매번 달라지므로, 기존처럼 단순히 "길이가 100인 배열이 나오면 끝"이라는 식의 하드코딩된 종료 조건이 무력화됨. 언제 랭킹 비교가 끝난 것인지 추적 불가 상태에 빠짐.
3. **홀수 병합 교착 상태 (Odd-Number Deadlock)**: 비동기 워커가 짝(Pair)을 지어 병합하게 되는데, 특정 레벨(Level)에 15명 등 홀수 개의 노드가 도달하면, 마지막 남은 1개 노드는 영원히 짝을 찾지 못하고 무한 대기(Hang) 상태에 빠져 전체 프로세스가 정지됨.

### 25.2. 원인 분석 (Root Cause)
- **비연결성 분산 트리 구조의 약점**: AI 워커들은 MQ(`q.pairs.eval`)에서 각자 맡은 노드만 떼어가서 평가하므로, "현재 자신이 합친 노드가 전체 트리의 어느 위치에 있는지", "이 노드가 최상단 루트(Root)에 가까운지" 여부를 판단할 전역 상태값(Global Context)이 설계상 부재했음.
- **Merge Sort 구조 파괴**: 단순히 큐에 도착하는 순서대로 무작위 병합을 허용하면, 길이가 8인 노드와 길이가 1인 노드가 극단적으로 불평등하게 평가되는 트리 불균형 현상이 발생하여 효율적인 O(N log N) 시간 복잡도는 고사하고 LLM 토큰 소모가 극심해짐.

### 25.3. 해결 방안 (Solution)

#### 1. 동일 레벨 수평 병합 (Level-matched Queuing)을 통한 복잡도 확보
Merge Sort 알고리즘의 복잡도를 효율적으로 통제하기 위해, 아무 노드나 병합하지 않고 반드시 **"동일한 Level에 도착한 노드끼리만"** 짝을 맞추도록 설계함.
- MQ 페이로드에 `level` 값을 강제 부여하여, Level 0에서 승리한(합쳐진) 배열은 무조건 Level 1 대기열(Redis Hash)로 밀어넣어(Push) 완전히 동등한 길이(Weight)를 가진 다른 배열과 만나게 함으로써 이진 트리(Binary Tree)의 균형을 엄격하게 유지.

#### 2. 동적 인원을 수용하는 스마트 Lua 스크립트 (Atomic Routing)
워커들 간의 동시성 동기화 문제를 막기 위해 핵심 큐 라우팅 로직을 **원자적 단위로 작동하는 단일 Lua 스크립트**로 분리함.
- `expected_count` (각 레벨에서 최종 도달해야 할 총 노드의 계산된 개수) 개념을 도입.
- 노드가 레벨에 밀어넣어질(Push) 때마다 `arrived += 1`을 기록하며, `list_len >= 2`가 되는 순간 가장 먼저 2개를 Pop하여 **`PAIR`** (병합 미션 발행) 상태로 넘김.

#### 3. 홀수 부전승(Promote) 감지 및 최종 레벨 확정 로직
"홀수 깍두기" 및 "종료 시점 파악"이라는 고난도 알고리즘적 난제를 수학적 조건 하나로 깔끔하게 치환함.
- **마지막 홀수 부전승 판단 로직**:
  - 방금 들어온 노드로 인해 드디어 `arrived(도착 수) == expected(목표 수)`가 달성되었음에도 불구하고 짝꿍을 이루지 못하고 혼자 덩그러니 남았다면(`list_len == 1`), 이는 해당 레벨의 **"마지막 홀수 생존자"**임이 증명됨.
  - 이 경우 Lua 스크립트는 **`PROMOTE`** 상태를 즉시 반환하며, 워커는 이 노드를 LLM 낭비 없이 쿨하게 그대로 다음 레벨(Level+1) 대기열로 부전승 승급(Cascading) 시킴.
- **동적 인원 100% 대응의 핵심 (Root Node 파악)**: 
  - 맨 처음 생성 시점의 `target_count`(전체 유동 참가자 73명, 89명 등)를 페이로드에 불변 값으로 계속 들고 다니도록 설계. 
  - 워커가 병합 통계를 내어 현재 배열 길이가 `len(merged_ids) >= target_count`에 정확히 맞물리는 순간, 그 길이에 도달했다는 자체가 어떤 가변 인원이든 간에 **"모든 노드가 하나로 뭉친 최종 루트 노드"**임을 의미하므로 그 즉시 비동기로 랭킹 로직을 종료하고 피드백 Fan-out을 트리거하도록 구현함.

### 25.4. 결과 및 효과 (Results)
- 단 하나의 데드락 오류도 없이 5명, 7명, 99명 등 극한의 엣지 케이스부터 홀수 연쇄 폭발 상황까지 무한정 소화가 가능한 완전한 동적(Dynamic) 토너먼트 머신이 완성됨.
- 각 레벨의 무결한 병합이 독립적인 MQ에서 병렬로 이루어짐으로써 최적의 O(N log N) 트리를 자율적으로 그려냄.


## 26. Dev 환경 S3 Presigned URL 만료(403) — 환경 분리 미숙지 및 부하 테스트 충돌 [2026-03-20]

### 26.1. 문제 상황 (Problem)
- **증상**: Dev 서버의 STT 처리 전 단계에서 403 에러가 산발적으로 발생.
  AI 서버 로그에는 타임스탬프가 없어 원인을 즉시 특정할 수 없었음.
- **발견**: RunPod Serverless 대시보드에서 특정 인스턴스 1개가 계속 에러를 반복 출력하는 것을 확인. 해당 인스턴스 로그에는 타임스탬프와 함께 아래와 같은 에러가 찍혀 있었음.
  ```
  Transcription failed: Failed to download audio: 403 Client Error: Forbidden for url:
  https://dev-imymemine.s3.../...?X-Amz-Expires=3600&X-Amz-Date=20260320T110430Z...
  ```
- **영향**: RabbitMQ 큐에 쌓인 **1,227개**의 STT 요청이 전량 만료된 Presigned URL로 재시도를 반복하는 상황이 발생.

### 26.2. 원인 분석 (Root Cause)

**복합 원인 2가지가 연속으로 충돌함:**

1. **환경 공유에 대한 인지 미숙**:
   - `prod`, `release`, `dev` 환경이 **서로 다른 EC2 인스턴스**지만, **RunPod Serverless 엔드포인트는 3개 환경이 동일한 것을 공유**하고 있었음.
   - Cloud 팀원이 `release` 서버를 대상으로 대규모 부하 테스트를 진행하기로 했고, 관련 팀원이 승인을 줬으나 **RunPod이 공유된다는 사실을 인지하지 못한 채** 승인함.
   - 부하 테스트로 release 서버에서 대량의 STT 요청이 발생 → RunPod 큐가 폭발적으로 적체됨.

2. **Presigned URL 만료 (TTL 1시간)**:
   - S3 Presigned URL의 유효기간이 `3600초(1시간)`으로 설정되어 있었음.
   - 부하 테스트로 인한 적체로 메시지가 큐에서 **1시간 이상** 대기하다 처리되는 순간, URL이 이미 만료되어 RunPod의 S3 다운로드 요청이 403을 받게 됨.

### 26.3. 해결 방법 (Solution)
1. 팀 내 공유를 통해 상황을 파악하고, 부하 테스트를 즉시 중단.
2. RabbitMQ에 적체된 **1,227개의 메시지를 Management UI에서 전량 Purge(삭제)** 처리.

### 26.4. 재발 방지 (Prevention)
- **환경별 RunPod 엔드포인트 분리** 필요. 최소한 부하 테스트 시에는 별도 엔드포인트를 사용해야 함.
- AI 서버 로그에 **타임스탬프가 출력되도록 로깅 설정을 보강**하여, 다음에는 RunPod 대시보드를 먼저 보는 일을 줄일 수 있음.


## 27. RabbitMQ prefetch_count=1 설정으로 인한 RunPod 단일 Worker 병목 [2026-03-20]

### 27.1. 문제 상황 (Problem)
- **증상**: 26번 인시던트 해결 과정에서, RunPod Serverless 대시보드를 보니 **6개의 Max Worker 설정에도 불구하고 항상 Worker 1개만 동작** 중인 것을 발견.
- **기대**: 여러 유저가 동시에 STT를 요청하면 RunPod이 ALB를 통해 부하를 분산하여 최대 6개 Worker를 활용해야 함.
- **현실**: 과거 REST API 방식일 때는 AI 서버가 동시에 여러 RunPod 요청을 날렸기 때문에 Worker가 여러 개 사용되었으나, **MQ 도입 이후 단 1개 Worker만 활용**되고 있었음.

### 27.2. 원인 분석 (Root Cause)
MQ 도입 시 `rabbitmq_service.py`에 **`prefetch_count=1`을 글로벌 채널 레벨로 적용**한 것이 원인이었음.

`prefetch_count=1`의 의미는 "컨슈머가 현재 처리 중인 메시지를 완전히 Ack 하기 전까지는 절대 다음 메시지를 가져오지 말 것"으로, 이는 **완전한 순차(Sequential) 처리**를 의미함.

결과적으로:
```
solo_stt_worker: msg1 처리 완료 (RunPod 1회 호출) → msg2 처리 완료 → msg3 처리 완료 ...
               (한 번에 RunPod에 요청 1개만 → Worker 1개만 가동)
```

MQ 도입 당시 이 설정의 의미를 완전히 이해하지 못한 채 "안전하게 1개씩"이라는 의도로 적용했으나, 그 결과 6개 Serverless Worker 인프라를 사실상 낭비하고 있었음.

### 27.3. 해결 방법 (Solution)
글로벌 채널 레벨의 `prefetch_count=1` 설정을 **컨슈머 레벨의 per-consumer 방식으로 전환**하고, 수치를 `6`으로 상향 조정.

```python
# 수정 전: 채널 전체에 순차 처리 강제
await self.channel.set_qos(prefetch_count=1)

# 수정 후: 컨슈머 레벨에서 동시 6개 처리 허용 (부하 테스트 기준)
prefetch = 6
await queue.channel.set_qos(prefetch_count=prefetch)
```

이로써 각 STT 워커가 최대 6개의 메시지를 동시에 꺼내어 RunPod에 병렬 요청을 발생시키므로, RunPod ALB가 부하를 분산하여 최대 6개 Worker를 풀가동할 수 있게 됨.

### 27.4. 교훈 (Lesson Learned)
- **RabbitMQ prefetch_count는 단순한 배치 크기가 아니라, 인프라 병렬성을 결정하는 핵심 설정임**을 명심해야 함.
- MQ 도입 시 "직전 아키텍처(REST API)에서 어떻게 동시성이 보장되었는지"를 먼저 파악하고, MQ 전환 후에도 동일한 동시성이 유지되는지 검증하는 단계가 반드시 필요함.
- 실운영 시 `prefetch_count`는 RunPod `max_workers`와 STT 워커 수를 함께 고려하여 `ceil(max_workers / num_stt_workers)` 공식으로 산정하는 것을 권장함.

## 28. 챌린지 모드 빈 배열(Empty Array) Truthiness 검증 버그 및 페이로드 기각 현상 [2026-03-22]

### 28.1. 문제 상황 (Problem)
- **증상**: 챌린지 모드 병합 큐(`challenge.pairs.eval`)에 정상적인 Payload 형태(`{target_count: 1, array_a: ["user1"], array_b: []}`)가 들어왔음에도 불구하고, AI 서버가 즉시 에러(`Invalid challenge merge payload`)를 뿜으며 처리를 튕겨냄 (Reject).
- **영향**: 1인 플레이(참여자 1명)나, 홀수 인원으로 짝맞추기를 하다 마지막에 혼자 남은 유저 등 `PROMOTE`를 통해 부전승 승급 처리가 되어야 할 정상적인 데이터 흐름이 완전히 단절됨.

### 28.2. 원인 분석 (Root Cause)
`app/workers/challenge_worker.py` 내의 큐 메시지 Payload 검증(`Validation`) 구문의 설계 결함.

```python
# 기존 결함 코드
if not all([job_id, level is not None, arr_a_ids, arr_b_ids]):
    logger.error("Invalid challenge merge payload")
```

Python 언어의 **Truthiness(참/거짓 평가)** 특성에 의해, 빈 리스트(`[]`)는 조건문에서 암묵적으로 `False`로 취급됨. 따라서 짝꿍이 없는 홀수 케이스여서 `arr_b_ids` 필드에 정상적으로 빈 배열(`[]`)이 들어왔음에도 불구하고, 코드 검증문 전체가 거짓(`False`)으로 튕겨나가며 에러를 발생시킨 것.

### 28.3. 해결 방법 (Solution)
Python 내장 함수 `isinstance()`를 사용해 **"값이 비어있냐"가 아니라 "객체의 자료형이 리스트(List)가 맞느냐"**로 Truthiness 평가 방식을 전면 교체하여, 빈 배열도 안전하게 통과되도록 조치함.

```python
# 수정된 방어 코드
if not all(
    [
        job_id is not None,
        level is not None,
        isinstance(arr_a_ids, list),  # 빈 배열 [] 도 True
        isinstance(arr_b_ids, list),  # 빈 배열 [] 도 True
    ]
):
```

### 28.4. 교훈 (Lesson Learned)
- Python에서 `if variable:` 과 같은 Truthiness 평가는 코드는 간결하게 만들지만, **0, "", [] 등 텅 빈 "정상 값(Falsy Value)"들까지 에러로 취급해버리는 엄청난 폭탄**이 될 수 있음.
- 통신의 관문이 되는 Validation 로직에서는 반드시 `isinstance()`나 `is not None`처럼 엄격한 자료형(Type) 검사를 명시적으로 수행해야 우발적인 데이터 Drop을 막을 수 있음.

## 29. 챌린지 모드 최종 피드백 JSON 구조(Payload) 스펙 불일치 오류 [2026-03-22]

### 29.1. 문제 상황 (Problem)
- **증상**: AI 챌린지 피드백 워커 로직과 Spring(백엔드) 서버 간의 Redis Hash(`challenge:{id}:feedbacks`) 적재 페이로드 스펙 불일치 및 속성명 누락 발생.
- **상세**:
  - 백엔드 기대 스펙: `{"user_id": 5, "rank": 1, "feedback_json": "{...}"}` (피드백 데이터가 통째로 Stringified JSON으로 묶인 형태)
  - 기존 AI 서버 직렬화 스펙: `{"attemptId": 101, "rank": 1, "summary": "...", "keywords": [...]}` (개별 속성들이 모두 루트 레벨로 분산된 Spread 형태, user_id 누락)
- **영향**: Spring 서버에서 HGET을 통해 최종 리더보드의 개인 피드백(My Page)을 렌더링할 때 역직렬화(Deserialization) 오류 또는 데이터 누락 발생.

### 29.2. 원인 분석 (Root Cause)
- 백엔드와 AI 간 챌린지 모드 최종 저장 단계에 대한 API/DB 협약(Spec)이 완벽히 동기화되지 않은 상태에서 각자 개발이 진행됨.
- AI 워커는 참가자의 고유 식별자로 `attemptId`만 사용해 처리했으나 백엔드는 화면 렌더링에 `user_id`를 혼용하였고, 피드백 데이터를 단일 String 필드(`feedback_json`)로 매핑하려는 Java 엔티티 구조와 불일치함.

### 29.3. 해결 방법 (Solution)
- AI 단(`app/workers/challenge_feedback_worker.py`)에서 Redis에 적재하기 직전 데이터를 재조립하여 엄격한 백엔드 API 명세에 강제 정렬함.
  1. `_get_participant_data()` 헬퍼 함수를 추상화하여, `participants` 해시에서 `sttText`뿐만 아니라 `userId` 필드를 같이 꺼내오도록 수정 (N+1 문제 없이 기존 로직 재활용).
  2. Gemini가 산출한 딕셔너리(`feedback`)를 최상위에 Spread 하지 않고, `json.dumps()`를 통해 단일 문자열로 압축하여 `feedback_json` 키 안에 캡슐화.
  3. JSON 최상단에 `user_id`, `rank` 필드만 선언하여 DTO 파싱 규격 통일.

### 29.4. 교훈 (Lesson Learned)
- 마이크로서비스(Spring ↔ Python Worker) 분리 환경에서는 **메시지 큐(MQ) 통신 포맷뿐만 아니라, 양쪽이 공유하는 Redis 스토리지의 입출력 JSON 직렬화 스키마(Schema)까지 완벽히 문서화하고 합의**해야 함.
- TDD(단위 테스트)를 짤 때 역시, 내부 로직의 정상 동작 여부만 검증(`assert "summary" in parsed`)할 것이 아니라, 외부 인터페이스 스펙(계약, Contract) 자체를 Mock 데이터와 Asserion 코드에 반영하는 "계약 주도 테스트"가 필요함을 깨달음.
