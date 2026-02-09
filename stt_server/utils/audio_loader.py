import requests
import tempfile
import os


# Service class for handling audio file operations
# 오디오 파일 작업을 처리하는 서비스 클래스
class AudioLoader:
    def __init__(self):
        # Chunk size for streaming downloads (8KB)
        # 스트리밍 다운로드를 위한 청크 크기 (8KB)
        self.chunk_size = 8192

    # Downloads audio from a URL to a temporary file
    # URL에서 오디오를 다운로드하여 임시 파일로 저장하는 메서드
    def download_audio(self, url: str) -> str:
        try:
            # Create a GET request with stream=True to handle large files efficiently
            # 대용량 파일을 효율적으로 처리하기 위해 stream=True로 GET 요청 생성
            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Create a temporary file to save the downloaded content
            # 다운로드한 내용을 저장할 임시 파일 생성
            # delete=False ensures the file exists after closing, so we can pass the path to Whisper
            # delete=False는 파일을 닫은 후에도 유지하여 Whisper에 경로를 전달할 수 있게 함
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        temp_file.write(chunk)

                # Return the absolute path of the temporary file
                # 임시 파일의 절대 경로 반환
                return temp_file.name

        except requests.RequestException as e:
            # Raise an exception if download fails
            # 다운로드 실패 시 예외 발생
            raise RuntimeError(f"Failed to download audio: {str(e)}")
        except Exception as e:
            # Raise generic exception for file IO errors
            # 파일 IO 오류 등 일반적인 예외 처리
            raise RuntimeError(f"Error saving audio file: {str(e)}")

    # Clean up the temporary file
    # 임시 파일 정리(삭제) 메서드
    def cleanup_file(self, file_path: str):
        if os.path.exists(file_path):
            os.remove(file_path)


# Global instance
audio_loader = AudioLoader()
