# Whoo AI Server (RunPod + FastAPI + Whisper)

이 프로젝트는 `faster-whisper`를 사용한 STT(Speech-to-Text) AI 추론 서버를 구현함.
시스템은 두 가지 주요 컴포넌트로 나뉨:

1.  **AI Server (FastAPI)**: 클라이언트의 요청을 받고 RunPod Serverless로 작업을 위임(오케스트레이션)함.
2.  **RunPod Worker**: RunPod GPU 인스턴스(Serverless) 위에서 도커 컨테이너로 실행되며 실제 전사 작업을 수행함.

## 프로젝트 구조 (Project Structure)

-   **`ai_server/`**: FastAPI AI 서버 (클라이언트 역할).
    -   로컬 컴퓨터나 일반 서버에서 실행됨.
    -   `ai_server/app/core/config.py`에서 설정 관리 (`RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID` 필요).
    -   실행: `cd ai_server && python -m app.main`
-   **`stt_server/`**: RunPod Serverless 워커 (GPU 작업).
    -   **RunPod**에 도커 이미지로 배포됨.
    -   `handler.py`와 모델/추론 서비스 코드가 플랫(Flat) 구조로 포함되어 있음.
    -   `Dockerfile`이 이 디렉토리에 포함되어 있음.

## 워커 이미지 빌드 방법 (How to Build)

**중요:** 반드시 터미널에서 **프로젝트 최상위 경로(`runpod_stt`)**에서 명령어를 실행해야 합니다.

```bash
docker build --platform linux/amd64 -t whoo-ai-server-worker -f stt_server/Dockerfile .
```

*   이 명령어는 `deepdml/faster-whisper-large-v3-turbo-ct2` 모델을 다운로드하여 이미지 안에 포함(Baking)시킴.
*   빌드된 이미지를 Docker Hub 등에 푸시하여 RunPod에서 사용하면 됨.

## AI 서버 실행 방법 (How to Run AI Server)

로컬에서 AI 서버 테스트 시:

1.  **의존성 설치**:
    ```bash
    pip install -r ai_server/requirements.txt
    ```

2.  **서버 실행**:
    (환경 변수 설정이 필요합니다. `.env` 파일을 만들거나 직접 export 하세요.)
    ```bash
    export RUNPOD_API_KEY="your_api_key"
    export RUNPOD_ENDPOINT_ID="your_endpoint_id"
    
    cd ai_server
    python -m app.main
    ```

    *주의: `ai_server` 디렉토리로 이동 후 실행해야 `app` 패키지를 올바르게 인식합니다.*
    
    ```bash
    cd ai_server
    python -m app.main
    ```

3.  **API 문서 확인**:
    브라우저에서 `http://localhost:8000/docs` 로 접속하면 Swagger UI를 볼 수 있음.

## API 문서 (API Documentation)

### 1. 전사 요청 (STT Transcription)
-   **Endpoint**: `POST /api/v1/transcriptions`
-   **Description**: S3 URL에 있는 오디오 파일을 텍스트로 변환함. (한국어 기본)

**Request Body**
```json
{
  "audioUrl": "https://s3.ap-northeast-2.amazonaws.com/..."
}
```

**Response**
```json
{
  "success": true,
  "data": {
    "text": "변환된 텍스트 결과입니다."
  },
  "error": null
}
```

### 2. GPU 워밍업 (GPU Warmup) [SYS-001]
-   **Endpoint**: `POST /api/v1/gpu/warmup`
-   **Description**: Cold Start 방지를 위해 RunPod GPU를 미리 깨움. (비동기)

**Request Body**
-   없음 (Empty Body `{}`)

**Response**
```json
{
  "success": true,
  "data": {
    "status": "WARMING_UP"
  },
  "error": null
}
```

### 3. 에러 코드 (Error Codes)

| HTTP Code | Error Code | 설명 |
| :--- | :--- | :--- |
| **400** | `INVALID_URL` | 유효하지 않은 URL 형식 |
| **400** | `UNSUPPORTED_FORMAT` | 지원하지 않는 오디오 포맷 (mp3, wav 등 지원) |
| **500** | `DOWNLOAD_FAILURE` | 오디오 파일 다운로드 실패 (S3 권한/만료 등) |
| **500** | `STT_FAILURE` | STT 엔진 변환 실패 또는 타임아웃 |
| **500** | `WARMUP_FAILED` | 워밍업 신호 전송 실패 |

### 4. RunPod 배포 (RunPod Deployment)

이미지를 **Docker Hub** 등에 올렸다면(`docker push`), 이제 RunPod 웹사이트에서 Serverless Endpoint를 생성해야 함.

#### 4.1. 템플릿 생성 (New Template)
1.  RunPod 콘솔 > Serverless > **Templates** > **New Template** 클릭.
2.  **Container Image**: 방금 올린 이미지 주소 (예: `sincheol/whisper-serverless:v1`).
3.  **Container Disk**: 모델이 크므로 **10GB 이상**.
4.  **Env Variables**: 필요한 경우 추가 (기본적으로 필요 없음).
5.  **Save Template** 클릭.

#### 4.2. 엔드포인트 생성 (New Endpoint)
1.  RunPod 콘솔 > Serverless > **Network Volume**(선택) / **Endpoint** > **New Endpoint** 클릭.
2.  방금 만든 템플릿 선택.
3.  **GPU Type**: GPU 선택.
4.  **Create** 클릭.

#### 4.3. 연동 정보 확인 및 AI 서버 설정
1.  생성된 Endpoint 클릭 > 상세 페이지 이동.
2.  **Endpoint ID** 확인 (예: `vllm-xxxxx`).
3.  **API Key** 생성 (RunPod 설정 > API Keys).
4.  이 정보들을 .env 파일에 설정하여 실행.
