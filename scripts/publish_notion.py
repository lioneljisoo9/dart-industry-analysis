import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.notion import publish_dashboard  # noqa: E402


METRICS_PATH = PROJECT_ROOT / "data" / "processed" / "annual_metrics.parquet"


def main():
    if not METRICS_PATH.exists():
        raise FileNotFoundError(
            "연간 KPI Master가 없습니다. 먼저 scripts/build_metrics.py를 "
            "실행하세요."
        )

    metrics = pd.read_parquet(METRICS_PATH)
    page_id = publish_dashboard(metrics)
    print(f"Notion 대시보드 갱신 완료: {page_id}")


if __name__ == "__main__":
    main()

