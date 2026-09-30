import re
from pathlib import Path

from src.corp_codes import (
    find_company,
    get_corp_code_dataframe,
)
from src.excel_export import export_financial_workbook
from src.storage import load_or_bootstrap_company_storage


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "excel"

ANNUAL_COUNT = 5
QUARTER_COUNT = 20
FS_DIV = "AUTO"


def _safe_filename(value):
    """기업명을 Windows에서도 안전한 파일명으로 변환한다."""

    filename = re.sub(
        r'[<>:"/\\|?*]+',
        "_",
        str(value),
    )
    filename = re.sub(
        r"\s+",
        "_",
        filename.strip(),
    )

    return filename.strip("._") or "company"


def main():
    company_query = input(
        "기업명 또는 6자리 종목코드를 입력하세요: "
    ).strip()

    print()
    print("DART 기업목록을 조회하는 중...")

    corp_df = get_corp_code_dataframe()
    company = find_company(corp_df, company_query)

    corp_code = str(company["corp_code"])
    company_name = str(company["corp_name"])
    stock_code_value = company.get("stock_code")
    stock_code = (
        ""
        if stock_code_value is None
        else str(stock_code_value).strip()
    )

    print()
    print("=== 선택된 기업 ===")
    print(f"기업명: {company_name}")
    print(f"DART 고유번호: {corp_code}")
    print(
        "종목코드: "
        f"{stock_code if stock_code else '비상장'}"
    )

    print()
    print("=== Master Data ===")
    annual_df, quarterly_df = load_or_bootstrap_company_storage(
        corp_code=corp_code,
        company_name=company_name,
        stock_code=stock_code,
        annual_count=ANNUAL_COUNT,
        quarter_count=QUARTER_COUNT,
        fs_div=FS_DIV,
    )

    annual_years = sorted(
        annual_df["year"].dropna().astype(int).unique().tolist()
    )
    quarter_periods = (
        quarterly_df[["year", "quarter_num", "period"]]
        .drop_duplicates()
        .sort_values(["year", "quarter_num"])["period"]
        .tolist()
    )

    print()
    print("=== 로컬 Master 범위 ===")
    print("연간:", ", ".join(map(str, annual_years)))
    print("분기:", ", ".join(quarter_periods))

    company_identifier = stock_code if stock_code else corp_code
    output_filename = (
        f"{_safe_filename(company_name)}_"
        f"{company_identifier}_"
        f"recent_{ANNUAL_COUNT}y_{QUARTER_COUNT}q.xlsx"
    )
    output_path = OUTPUT_DIRECTORY / output_filename

    export_financial_workbook(
        annual_df=annual_df,
        quarterly_df=quarterly_df,
        file_path=output_path,
    )

    print()
    print(
        "평소 분석은 data/master의 Parquet을 사용합니다. "
        "최신 공시 확인은 scripts/update_financials.py 또는 GitHub Actions가 담당합니다."
    )


if __name__ == "__main__":
    main()

