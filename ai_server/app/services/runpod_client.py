import requests
import time
import json
from app.core.config import settings
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

# Service to interact with RunPod Serverless API
# RunPod Serverless API와 상호작용하는 서비스
class RunPodClient:
    def __init__(self):
        self.api_key = settings.RUNPOD_API_KEY
        self.endpoint_id = settings.RUNPOD_ENDPOINT_ID
        self.base_url = f"https://api.runpod.ai/v2/{self.endpoint_id}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    # Helper method to run sync or async request
    # RunPod 요청을 보내고 결과를 기다리는 메서드
    def transcribe_sync(self, audio_url: str, language: str = None) -> dict:
        if not self.endpoint_id or not self.api_key:
             # For local testing without RunPod keys, mock it or raise error
             # RunPod 키 없이 로컬 테스트 시 모의(Mock) 처리 또는 오류 발생
            logger.warning("RunPod credentials not set. Returning mock response.")
            return self._mock_response(audio_url)

        payload = {
            "input": {
                "audio_url": audio_url,
                "language": language
            }
        }

        try:
            # 1. Run Job (Sync run)
            # 1. 작업 실행 (동기 실행 요청)
            # Using 'runsync' endpoint for waiting connection, or 'run' for async. 
            # 'runsync' is easier for immediate response if duration is short (< 90s).
            # For longer, use 'run' and poll. Assuming 'run' for robustness.
            run_url = f"{self.base_url}/run"
            
            logger.info(f"Sending job to RunPod: {run_url}")
            response = requests.post(run_url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            job_data = response.json()
            job_id = job_data["id"]
            
            logger.info(f"Job started with ID: {job_id}. Polling for status...")
            return self._poll_status(job_id)

        except requests.RequestException as e:
            logger.error(f"RunPod internal error: {e}")
            raise HTTPException(status_code=502, detail=f"RunPod communication error: {str(e)}")

    def warmup_async(self) -> dict:
        """
        Send a warmup request to RunPod asynchronously.
        RunPod에 워밍업 요청을 비동기적으로 보냅니다.
        """
        if not self.endpoint_id or not self.api_key:
            logger.warning("RunPod credentials not set. Skipping warmup.")
            return {"status": "mock_success", "message": "Mock warmup (no credentials)"}

        payload = {
            "input": {
                "warmup": True
            }
        }
        
        try:
             # Use 'run' endpoint for async fire-and-forget
            run_url = f"{self.base_url}/run"
            logger.info(f"Sending warmup signal to RunPod({self.endpoint_id})...")
            
            response = requests.post(run_url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            job_data = response.json()
            return {"status": "success", "job_id": job_data["id"]}
            
        except requests.RequestException as e:
            logger.error(f"Warmup failed: {e}")
            # Warmup failure shouldn't crash the server, but we report it
            return {"status": "failed", "error": str(e)}

    def _poll_status(self, job_id: str) -> dict:
        status_url = f"{self.base_url}/status/{job_id}"
        start_time = time.time()
        
        while time.time() - start_time < settings.RUNPOD_TIMEOUT_SECONDS:
            response = requests.get(status_url, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            status = data.get("status")
            
            if status == "COMPLETED":
                logger.info("Job completed successfully.")
                return data["output"]
            elif status == "FAILED":
                logger.error(f"Job failed: {data}")
                raise HTTPException(status_code=500, detail=f"Transcription job failed: {data.get('error')}")
            
            time.sleep(2) # Polling interval

        raise HTTPException(status_code=504, detail="Transcription job timed out")

    def _mock_response(self, url: str):
        return {
            "text": "This is a mock transcription because RunPod API key is missing.",
            "segments": [],
            "language": "en",
            "processing_time": 0.1
        }

runpod_client = RunPodClient()
