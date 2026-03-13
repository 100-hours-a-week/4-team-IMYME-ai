import httpx
import asyncio

from app.core.config import settings
from app.core.errors import AppException, ErrorCode
import logging

logger = logging.getLogger(__name__)


# Service to interact with RunPod STT (Pod primary, Serverless fallback)
# RunPod STT 호출 서비스 (Pod 우선, Serverless 폴백)
class RunPodClient:
    def __init__(self):
        self.api_key = settings.RUNPOD_API_KEY
        self.endpoint_id = settings.RUNPOD_ENDPOINT_ID
        self.base_url = f"https://api.runpod.ai/v2/{self.endpoint_id}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # Pod direct URL (e.g. https://{POD_ID}-8000.proxy.runpod.net)
        self.pod_url = settings.RUNPOD_POD_URL
        self.pod_timeout = settings.RUNPOD_POD_TIMEOUT

    # ──────────────────────────────────────────────
    # Public API — Pod 우선, Serverless 폴백
    # ──────────────────────────────────────────────
    async def transcribe(self, audio_url: str, language: str = None) -> dict:
        if not self.endpoint_id or not self.api_key:
            logger.warning("RunPod credentials not set. Returning mock response.")
            return self._mock_response(audio_url)

        # 1️⃣ Pod가 설정되어 있으면 우선 시도
        if self.pod_url:
            try:
                return await self._call_pod(audio_url, language)
            except Exception as e:
                logger.warning(
                    f"Pod request failed ({e}). Falling back to Serverless..."
                )

        # 2️⃣ Serverless 폴백 (기존 로직)
        return await self._call_serverless(audio_url, language)

    # ──────────────────────────────────────────────
    # Pod — Direct HTTP POST to FastAPI
    # ──────────────────────────────────────────────
    async def _call_pod(self, audio_url: str, language: str = None) -> dict:
        url = f"{self.pod_url.rstrip('/')}/transcribe"
        payload = {"audio_url": audio_url, "language": language}

        logger.info(f"Sending request to Pod: {url}")
        async with httpx.AsyncClient(timeout=self.pod_timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        data = response.json()
        logger.info("Pod responded successfully.")
        return data

    # ──────────────────────────────────────────────
    # Serverless — /run + polling (비동기 전환)
    # ──────────────────────────────────────────────
    async def _call_serverless(self, audio_url: str, language: str = None) -> dict:
        payload = {"input": {"audio_url": audio_url, "language": language}}

        try:
            run_url = f"{self.base_url}/run"

            logger.info(f"Sending job to RunPod Serverless: {run_url}")
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    run_url, headers=self.headers, json=payload
                )
                response.raise_for_status()

            job_data = response.json()
            job_id = job_data["id"]

            logger.info(f"Job started with ID: {job_id}. Polling for status...")
            return await self._poll_status(job_id)

        except httpx.HTTPError as e:
            logger.error(f"RunPod Serverless error: {e}")
            raise AppException(
                code=ErrorCode.STT_FAILURE,
                message="RunPod 통신 중 오류가 발생했습니다.",
                detail={"raw_error": str(e)},
                status_code=502,
            )

    # ──────────────────────────────────────────────
    # Warmup (Serverless only — Pod은 항시 구동이므로 불필요)
    # ──────────────────────────────────────────────
    async def warmup_async(self) -> dict:
        """
        Send a warmup request to RunPod asynchronously.
        RunPod에 워밍업 요청을 비동기적으로 보냅니다.
        """
        if not self.endpoint_id or not self.api_key:
            logger.warning("RunPod credentials not set. Skipping warmup.")
            return {"status": "mock_success", "message": "Mock warmup (no credentials)"}

        payload = {"input": {"warmup": True}}

        try:
            run_url = f"{self.base_url}/run"
            logger.info(f"Sending warmup signal to RunPod({self.endpoint_id})...")

            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    run_url, headers=self.headers, json=payload
                )
                response.raise_for_status()

            job_data = response.json()
            return {"status": "success", "job_id": job_data["id"]}

        except httpx.HTTPError as e:
            logger.error(f"Warmup failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ──────────────────────────────────────────────
    # Polling helper (Serverless, 비동기)
    # ──────────────────────────────────────────────
    async def _poll_status(self, job_id: str) -> dict:
        import time

        status_url = f"{self.base_url}/status/{job_id}"
        start_time = time.time()

        async with httpx.AsyncClient(timeout=60) as client:
            while time.time() - start_time < settings.RUNPOD_TIMEOUT_SECONDS:
                response = await client.get(status_url, headers=self.headers)
                response.raise_for_status()

                data = response.json()
                status = data.get("status")

                if status == "COMPLETED":
                    logger.info("Job completed successfully.")
                    return data["output"]
                elif status == "FAILED":
                    logger.error(f"Job failed: {data}")
                    raise AppException(
                        code=ErrorCode.STT_FAILURE,
                        message="STT 작업이 실패했습니다.",
                        detail={"job_error": data.get("error")},
                        status_code=500,
                    )

                await asyncio.sleep(2)  # Non-blocking polling interval

        raise AppException(
            code=ErrorCode.STT_TIMEOUT,
            message="STT 작업이 타임아웃되었습니다.",
            detail={"timeout_seconds": settings.RUNPOD_TIMEOUT_SECONDS},
            status_code=504,
        )

    def _mock_response(self, url: str):
        return {
            "text": "This is a mock transcription because RunPod API key is missing.",
            "segments": [],
            "language": "en",
            "processing_time": 0.1,
        }


runpod_client = RunPodClient()
