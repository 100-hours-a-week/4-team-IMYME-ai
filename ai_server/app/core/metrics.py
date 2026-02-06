"""
Prometheus Metrics Definition
프로메테우스 메트릭 정의
"""
from prometheus_client import Counter, Histogram, Info
import time

# =============================================================================
# 1. API Request Metrics (API 요청 메트릭)
# =============================================================================

# HTTP 요청 카운터 (endpoint, method, status별)
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

# HTTP 요청 처리 시간 (histogram)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# =============================================================================
# 2. STT (Speech-to-Text) Metrics
# =============================================================================

# STT 처리 시간 (RunPod)
stt_processing_duration_seconds = Histogram(
    "stt_processing_duration_seconds",
    "STT processing time in seconds",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# STT 요청 카운터
stt_requests_total = Counter(
    "stt_requests_total",
    "Total STT requests",
    ["status"],  # success, failed, timeout
)

# STT 오디오 길이 (초)
stt_audio_duration_seconds = Histogram(
    "stt_audio_duration_seconds",
    "Audio file duration in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

# =============================================================================
# 3. LLM (Large Language Model) Metrics
# =============================================================================

# LLM 추론 시간
llm_inference_duration_seconds = Histogram(
    "llm_inference_duration_seconds",
    "LLM inference time in seconds",
    ["service", "model"],  # service: feedback/scoring, model: gemini-flash/pro
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# LLM 요청 카운터
llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM requests",
    ["service", "status"],  # service: feedback/scoring, status: success/failed/blocked
)

# LLM 토큰 사용량 (추정)
llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens used",
    ["service", "type"],  # type: input/output
)

# =============================================================================
# 4. Task Processing Metrics (작업 처리 메트릭)
# =============================================================================

# 분석 작업 상태별 카운터
analysis_tasks_total = Counter(
    "analysis_tasks_total",
    "Total analysis tasks",
    ["status"],  # PENDING, PROCESSING, COMPLETED, FAILED
)

# 분석 작업 처리 시간
analysis_duration_seconds = Histogram(
    "analysis_duration_seconds",
    "Analysis task duration in seconds",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# =============================================================================
# 5. Quality Metrics (품질 메트릭)
# =============================================================================

# 평가 점수 분포
evaluation_score = Histogram(
    "evaluation_score",
    "Evaluation overall score distribution",
    buckets=(0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)

# 평가 레벨 분포
evaluation_level = Histogram(
    "evaluation_level",
    "Evaluation level distribution",
    buckets=(1, 2, 3, 4, 5),
)

# =============================================================================
# 6. Error Metrics (에러 메트릭)
# =============================================================================

# 에러 카운터
errors_total = Counter(
    "errors_total",
    "Total errors",
    ["error_type", "service"],  # error_type: STT_FAILURE, INTERNAL_ERROR, etc.
)

# RunPod Job 실패 카운터
runpod_job_failures_total = Counter(
    "runpod_job_failures_total",
    "Total RunPod job failures",
    ["failure_reason"],  # timeout, failed, download_error
)

# =============================================================================
# 7. System Info (시스템 정보)
# =============================================================================

# 서비스 정보
service_info = Info("service_info", "Service information")

# =============================================================================
# Helper Functions (헬퍼 함수)
# =============================================================================


class MetricsTimer:
    """
    Context manager for timing operations
    작업 시간 측정을 위한 컨텍스트 매니저

    Usage:
        with MetricsTimer(stt_processing_duration_seconds):
            # ... do work ...
    """

    def __init__(self, histogram):
        self.histogram = histogram
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        self.histogram.observe(duration)
        return False


def record_http_request(method: str, endpoint: str, status: int):
    """Record HTTP request metrics"""
    http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()


def record_stt_request(status: str, processing_time: float = None):
    """Record STT request metrics"""
    stt_requests_total.labels(status=status).inc()
    if processing_time:
        stt_processing_duration_seconds.observe(processing_time)


def record_llm_request(
    service: str, model: str, status: str, duration: float = None
):
    """Record LLM request metrics"""
    llm_requests_total.labels(service=service, status=status).inc()
    if duration:
        llm_inference_duration_seconds.labels(service=service, model=model).observe(
            duration
        )


def record_analysis_task(status: str, duration: float = None):
    """Record analysis task metrics"""
    analysis_tasks_total.labels(status=status).inc()
    if duration:
        analysis_duration_seconds.observe(duration)


def record_evaluation_result(overall_score: int, level: int):
    """Record evaluation quality metrics"""
    evaluation_score.observe(overall_score)
    evaluation_level.observe(level)


def record_error(error_type: str, service: str):
    """Record error metrics"""
    errors_total.labels(error_type=error_type, service=service).inc()


def record_runpod_failure(failure_reason: str):
    """Record RunPod job failure"""
    runpod_job_failures_total.labels(failure_reason=failure_reason).inc()
