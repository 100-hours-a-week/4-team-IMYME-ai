from faster_whisper import download_model
import os
import sys

# Define the model to download (must match config or be parameterized)
# 다운로드할 모델 정의 (설정과 일치하거나 매개변수화되어야 함)
MODEL_SIZE = "deepdml/faster-whisper-large-v3-turbo-ct2"
OUTPUT_DIR = "/app/models"


def main():
    print(f"Downloading {MODEL_SIZE} model to {OUTPUT_DIR}...")

    # Create directory if it doesn't exist
    # 디렉토리가 없으면 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        # Download the model
        # 모델 다운로드
        path = download_model(MODEL_SIZE, output_dir=OUTPUT_DIR)
        print(f"Model downloaded successfully to {path}")
    except Exception as e:
        print(f"Failed to download model: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
