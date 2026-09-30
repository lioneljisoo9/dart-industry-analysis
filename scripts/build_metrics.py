import argparse
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.companies import COMPANIES  # noqa: E402
from src.metrics import build_annual_metrics  # noqa: E402
from src.storage import (  # noqa: E402
    load_company_storage,
    storage_exists,
)


PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"


def _normalize_query(value):
    return "".join(
        str(value or "").casefold().split()
    ).replace("-", "")


def _targets(queries):
    configured = list(COMPANIES.values())
    if not queries:
        return configured

    selected = []
    for query in queries:
        key = _normalize_query(query)
        matches = [
            config
            for config in configured
            if key in {
                _normalize_query(config.get("corp_name")),
                _normalize_query(config.get("stock_code")),
            }
        ]
        if not matches:
            raise ValueError(
                f"KPI를 계산할 기업을 찾지 못했습니다: {query}"
            )
        if len(matches) > 1:
            raise ValueError(
                f"KPI 대상이 여러 개입니다: {query}"
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def build_metrics(queries=None):
    annual_frames = []
    for config in _targets(queries):
        company_name = str(config["corp_name"])
        stock_code = str(config.get("stock_code") or "")
        if not storage_exists(stock_code=stock_code):
            raise FileNotFoundError(
                f"{company_name}의 Master Data가 없습니다. "
                "먼저 scripts/update_financials.py를 실행하세요."
            )
        annual_df, _ = load_company_storage(stock_code=stock_code)
        annual_frames.append(annual_df)

    metrics = build_annual_metrics(
        pd.concat(annual_frames, ignore_index=True)
    )
    PROCESSED_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIRECTORY / "annual_metrics.parquet"
    metrics.to_parquet(output_path, index=False)
    return metrics, output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="로컬 Master에서 기업별 연간 KPI를 계산합니다."
    )
    parser.add_argument(
        "--company",
        action="append",
        dest="companies",
        help="기업명 또는 6자리 종목코드. 여러 번 지정할 수 있습니다.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    metrics, output_path = build_metrics(args.companies)
    latest = (
        metrics.sort_values(["company", "year"])
        .groupby("company", as_index=False)
        .tail(1)
    )
    print(f"연간 KPI Master: {output_path}")
    print(f"행 수: {len(metrics)}")
    print("최근 연도 KPI:")
    print(
        latest[
            [
                "company",
                "year",
                "operating_margin",
                "operating_cash_flow_margin",
                "contract_assets_to_revenue",
                "contract_liabilities_to_revenue",
                "earnings_cash_gap_to_revenue",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()

