import runpod
from services.inference_service import InferenceService
import logging

# Configure logging for RunPod
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runpod-handler")

# Initialize Service
inference_service = InferenceService()

# Initialize the model once during cold start
logger.info("Initializing Inference Service...")
inference_service.model_service.load_model()
logger.info("Service initialized.")

# Handler function that RunPod calls for each request
# RunPod가 각 요청에 대해 호출하는 핸들러 함수
def handler(job):
    """
    Handler for RunPod serverless worker.
    RunPod serverless 워커를 위한 핸들러.
    """
    job_input = job.get("input", {})
    
    # Extract arguments from input
    # 입력에서 인자 추출
    audio_url = job_input.get("audio_url")
    language = job_input.get("language")

    # Handle Warmup Request
    # 워밍업 요청 처리
    if job_input.get("warmup"):
        logger.info("Warmup signal received. Returning immediately.")
        return {"status": "success", "message": "Warmed up"}

    if not audio_url:
        return {"error": "Missing 'audio_url' in input"}

    try:
        logger.info(f"Processing job {job.get('id')} for URL: {audio_url}")
        
        # Call the transcription service
        # 전사 서비스 호출
        result = inference_service.transcribe(audio_url, language)
        
        # Return serializable dict
        # 직렬화 가능한 딕셔너리 반환
        return result

    except Exception as e:
        logger.error(f"Job failed: {e}")
        return {"error": str(e)}

# Start the RunPod worker
# RunPod 워커 시작
runpod.serverless.start({"handler": handler})
