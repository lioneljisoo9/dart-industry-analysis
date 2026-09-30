import os
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.companies import COMPANIES  # noqa: E402
from src.corp_codes import (  # noqa: E402
    find_company,
    get_corp_code_dataframe,
)
from src.excel_export import export_financial_workbook  # noqa: E402
from src.storage import update_company_storage  # noqa: E402


ANNUAL_COUNT = int(os.getenv("DART_ANNUAL_COUNT", "5"))
QUARTER_COUNT = int(os.getenv("DART_QUARTER_COUNT", "20"))
FS_DIV = os.getenv("DART_FS_DIV", "AUTO").upper()
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "excel"


def _safe_filename(value):
    filename = re.sub(r'[<>:"/\\|?*]+', "_", str(value))
    filename = re.sub(r"\s+", "_", filename.strip())
    return filename.strip("._") or "company"


def _target_companies():
    override = os.getenv("DART_COMPANIES", "").strip()

    if override:
        return [
            item.strip()
            for item in override.split(",")
            if item.strip()
        ]

    return [
        config["corp_name"]
        for config in COMPANIES.values()
    ]


def main():
    targets = _target_companies()

    if not targets:
        raise ValueError("자동 갱신 대상 기업이 없습니다.")

    print("자동 갱신 대상:", ", ".join(targets))
    corp_df = get_corp_code_dataframe(refresh=True)
    changed_companies = []

    for query in targets:
        print()
        print("=" * 70)
        print(f"기업 처리 시작: {query}")
        print("=" * 70)

        company = find_company(corp_df, query)
        corp_code = str(company["corp_code"])
        company_name = str(company["corp_name"])
        stock_code = str(company.get("stock_code") or "").strip()

        annual_df, quarterly_df, changed = update_company_storage(
            corp_code=corp_code,
            company_name=company_name,
            stock_code=stock_code,
            annual_count=ANNUAL_COUNT,
            quarter_count=QUARTER_COUNT,
            fs_div=FS_DIV,
        )

        if changed:
            changed_companies.append(company_name)

        identifier = stock_code if stock_code else corp_code
        output_path = OUTPUT_DIRECTORY / (
            f"{_safe_filename(company_name)}_"
            f"{identifier}_"
            f"recent_{ANNUAL_COUNT}y_{QUARTER_COUNT}q.xlsx"
        )

        export_financial_workbook(
            annual_df=annual_df,
            quarterly_df=quarterly_df,
            file_path=output_path,
        )

    print()
    if changed_companies:
        print("Master Data 변경 기업:", ", ".join(changed_companies))
    else:
        print("모든 기업의 Master Data가 최신 상태입니다.")


if __name__ == "__main__":
    main()

