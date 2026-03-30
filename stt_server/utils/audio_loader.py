import io
import requests


class AudioLoader:
    def __init__(self):
        self.chunk_size = 8192

    def download_audio(self, url: str) -> io.BytesIO:
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()

            buffer = io.BytesIO()
            for chunk in response.iter_content(chunk_size=self.chunk_size):
                if chunk:
                    buffer.write(chunk)
            buffer.seek(0)
            return buffer

        except requests.RequestException as e:
            raise RuntimeError(f"Failed to download audio: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Error loading audio into memory: {str(e)}")


# Global instance
audio_loader = AudioLoader()
