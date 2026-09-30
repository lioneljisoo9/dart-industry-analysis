import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


DART_API_KEY = os.getenv(
    "DART_API_KEY",
    "",
).strip()


def get_dart_api_key():
    """실제 DART API 호출 시점에 키를 검증해 반환한다."""

    if not DART_API_KEY:
        raise ValueError(
            "DART_API_KEY가 설정되어 있지 않습니다. "
            ".env 파일 또는 실행 환경변수를 확인하세요."
        )

    return DART_API_KEY

