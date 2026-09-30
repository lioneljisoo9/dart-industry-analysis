import json
import re
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
from numbers import Number
from pathlib import Path

import pandas as pd

from src.financials import (
    DartNoDataError,
    collect_annual_year_accounts,
    collect_recent_annual_accounts,
)
from src.quarterly import (
    collect_recent_quarterly_accounts,
    collect_year_quarters,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASTER_DIRECTORY = PROJECT_ROOT / "data" / "master"
DATA_ENGINE_VERSION = 2


def _safe_identifier(value):
    text = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(value).strip())
    return text.strip("._") or "company"


def company_storage_key(stock_code=None, corp_code=None):
    stock_code_text = str(stock_code or "").strip()
    corp_code_text = str(corp_code or "").strip()

    if stock_code_text:
        return _safe_identifier(stock_code_text.zfill(6))
    if corp_code_text:
        return _safe_identifier(corp_code_text)

    raise ValueError("stock_code 또는 corp_code가 필요합니다.")


def get_storage_paths(stock_code=None, corp_code=None):
    key = company_storage_key(stock_code=stock_code, corp_code=corp_code)

    return {
        "annual": MASTER_DIRECTORY / f"{key}_annual.parquet",
        "quarterly": MASTER_DIRECTORY / f"{key}_quarterly.parquet",
        "metadata": MASTER_DIRECTORY / f"{key}_metadata.json",
    }


def storage_exists(stock_code=None, corp_code=None):
    paths = get_storage_paths(stock_code=stock_code, corp_code=corp_code)
    return paths["annual"].exists() and paths["quarterly"].exists()


def load_company_metadata(stock_code=None, corp_code=None):
    paths = get_storage_paths(
        stock_code=stock_code,
        corp_code=corp_code,
    )

    if not paths["metadata"].exists():
        return {}

    return json.loads(
        paths["metadata"].read_text(
            encoding="utf-8"
        )
    )


def storage_needs_rebuild(stock_code=None, corp_code=None):
    """저장된 Master가 현재 계산 엔진 버전과 다른지 확인한다."""

    if not storage_exists(
        stock_code=stock_code,
        corp_code=corp_code,
    ):
        return True

    metadata = load_company_metadata(
        stock_code=stock_code,
        corp_code=corp_code,
    )

    return metadata.get(
        "data_engine_version"
    ) != DATA_ENGINE_VERSION


def _atomic_to_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    df.to_parquet(temp_path, index=False)
    temp_path.replace(path)


def _atomic_write_json(payload, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _normalize_year_column(df):
    result = df.copy()
    if "year" in result.columns:
        result["year"] = pd.to_numeric(
            result["year"],
            errors="coerce",
        ).astype("Int64")
    return result


def trim_recent_annual(df, count=5):
    if df.empty:
        return df.copy()

    result = _normalize_year_column(df)
    years = (
        result["year"]
        .dropna()
        .astype(int)
        .drop_duplicates()
        .sort_values()
        .tail(count)
        .tolist()
    )

    result = result[result["year"].isin(years)].copy()

    sort_columns = ["year", "sj_div"]
    if "ord" in result.columns:
        sort_columns.append("ord")

    return result.sort_values(
        sort_columns,
        na_position="last",
    ).reset_index(drop=True)


def trim_recent_quarterly(df, count=20):
    if df.empty:
        return df.copy()

    result = _normalize_year_column(df)
    result["quarter_num"] = pd.to_numeric(
        result["quarter_num"],
        errors="coerce",
    ).astype("Int64")

    periods = (
        result[["year", "quarter_num", "period"]]
        .dropna(subset=["year", "quarter_num", "period"])
        .drop_duplicates()
        .assign(
            quarter_index=lambda x: (
                x["year"].astype(int) * 4
                + x["quarter_num"].astype(int)
            )
        )
        .sort_values("quarter_index")
        .tail(count)
    )

    keep_periods = periods["period"].tolist()
    result = result[result["period"].isin(keep_periods)].copy()

    result["_quarter_index"] = (
        result["year"].astype(int) * 4
        + result["quarter_num"].astype(int)
    )

    sort_columns = ["_quarter_index", "sj_div"]
    if "ord" in result.columns:
        sort_columns.append("ord")

    return (
        result
        .sort_values(sort_columns, na_position="last")
        .drop(columns=["_quarter_index"])
        .reset_index(drop=True)
    )


def _receipt_number(df):
    if df is None or df.empty or "rcept_no" not in df.columns:
        return ""

    values = (
        df["rcept_no"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    values = values[values.ne("")]

    return values.iloc[0] if not values.empty else ""


def _canonical_cell(value):
    """dtype 차이는 무시하면서 실제 셀 값은 안정적으로 비교한다."""

    if pd.isna(value):
        return "<NA>"

    if isinstance(value, Number) and not isinstance(value, bool):
        try:
            return f"N:{Decimal(str(value)).normalize()}"
        except InvalidOperation:
            pass

    return f"S:{str(value).strip()}"


def _period_signature(df):
    """행 순서와 pandas dtype에 영향받지 않는 기간 데이터 서명."""

    if df is None or df.empty:
        return (), ()

    columns = tuple(sorted(str(column) for column in df.columns))
    ordered = df.loc[:, list(columns)]

    rows = [
        tuple(_canonical_cell(value) for value in row)
        for row in ordered.itertuples(index=False, name=None)
    ]

    return columns, tuple(sorted(rows))


def _annual_period_changed(existing_df, incoming_df, year):
    old_period = existing_df[
        pd.to_numeric(existing_df["year"], errors="coerce").eq(int(year))
    ]
    if old_period.empty:
        return True

    return _period_signature(incoming_df) != _period_signature(
        old_period
    )


def _quarter_period_changed(existing_df, incoming_period_df, period):
    old_period = existing_df[
        existing_df["period"].astype(str).eq(str(period))
    ]
    if old_period.empty:
        return True

    return _period_signature(
        incoming_period_df
    ) != _period_signature(old_period)


def _replace_annual_period(existing_df, incoming_df, year):
    if existing_df.empty:
        return incoming_df.copy()

    keep = existing_df[
        ~pd.to_numeric(existing_df["year"], errors="coerce").eq(int(year))
    ].copy()

    return pd.concat([keep, incoming_df], ignore_index=True)


def _replace_quarter_period(existing_df, incoming_period_df, period):
    if existing_df.empty:
        return incoming_period_df.copy()

    keep = existing_df[
        ~existing_df["period"].astype(str).eq(str(period))
    ].copy()

    return pd.concat([keep, incoming_period_df], ignore_index=True)


def _metadata_payload(
    company_name,
    corp_code,
    stock_code,
    annual_df,
    quarterly_df,
):
    annual_years = []
    if not annual_df.empty:
        annual_years = sorted(
            pd.to_numeric(annual_df["year"], errors="coerce")
            .dropna()
            .astype(int)
            .unique()
            .tolist()
        )

    quarter_periods = []
    if not quarterly_df.empty:
        quarter_periods = (
            quarterly_df[["year", "quarter_num", "period"]]
            .drop_duplicates()
            .assign(
                quarter_index=lambda x: (
                    pd.to_numeric(x["year"], errors="coerce").astype(int) * 4
                    + pd.to_numeric(x["quarter_num"], errors="coerce").astype(int)
                )
            )
            .sort_values("quarter_index")["period"]
            .astype(str)
            .tolist()
        )

    return {
        "data_engine_version": DATA_ENGINE_VERSION,
        "company_name": company_name,
        "corp_code": str(corp_code),
        "stock_code": str(stock_code or ""),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "annual_years": annual_years,
        "quarter_periods": quarter_periods,
        "annual_rows": int(len(annual_df)),
        "quarterly_rows": int(len(quarterly_df)),
    }


def save_company_storage(
    annual_df,
    quarterly_df,
    company_name,
    corp_code,
    stock_code=None,
):
    paths = get_storage_paths(stock_code=stock_code, corp_code=corp_code)

    _atomic_to_parquet(annual_df, paths["annual"])
    _atomic_to_parquet(quarterly_df, paths["quarterly"])

    metadata = _metadata_payload(
        company_name=company_name,
        corp_code=corp_code,
        stock_code=stock_code,
        annual_df=annual_df,
        quarterly_df=quarterly_df,
    )
    _atomic_write_json(metadata, paths["metadata"])

    return paths


def load_company_storage(stock_code=None, corp_code=None):
    paths = get_storage_paths(stock_code=stock_code, corp_code=corp_code)

    if not paths["annual"].exists() or not paths["quarterly"].exists():
        raise FileNotFoundError(
            "저장된 Master Data가 없습니다. "
            "먼저 bootstrap_company_storage()를 실행하세요."
        )

    annual_df = pd.read_parquet(paths["annual"])
    quarterly_df = pd.read_parquet(paths["quarterly"])

    return annual_df, quarterly_df


def bootstrap_company_storage(
    corp_code,
    company_name,
    stock_code=None,
    annual_count=5,
    quarter_count=20,
    fs_div="AUTO",
):
    print("로컬 Master Data가 없어 최초 수집을 시작합니다.")

    annual_df = collect_recent_annual_accounts(
        corp_code=corp_code,
        company_name=company_name,
        count=annual_count,
        fs_div=fs_div,
    )

    quarterly_df = collect_recent_quarterly_accounts(
        corp_code=corp_code,
        company_name=company_name,
        count=quarter_count,
        fs_div=fs_div,
    )

    annual_df = trim_recent_annual(annual_df, count=annual_count)
    quarterly_df = trim_recent_quarterly(quarterly_df, count=quarter_count)

    save_company_storage(
        annual_df=annual_df,
        quarterly_df=quarterly_df,
        company_name=company_name,
        corp_code=corp_code,
        stock_code=stock_code,
    )

    return annual_df, quarterly_df


def load_or_bootstrap_company_storage(
    corp_code,
    company_name,
    stock_code=None,
    annual_count=5,
    quarter_count=20,
    fs_div="AUTO",
):
    if storage_exists(
        stock_code=stock_code,
        corp_code=corp_code,
    ) and not storage_needs_rebuild(
        stock_code=stock_code,
        corp_code=corp_code,
    ):
        print("저장된 로컬 Master Data를 불러옵니다. DART 재무 API는 호출하지 않습니다.")
        return load_company_storage(
            stock_code=stock_code,
            corp_code=corp_code,
        )

    if storage_exists(
        stock_code=stock_code,
        corp_code=corp_code,
    ):
        print(
            "데이터 엔진 버전이 변경되어 Master Data를 "
            "전체 재구축합니다."
        )

    return bootstrap_company_storage(
        corp_code=corp_code,
        company_name=company_name,
        stock_code=stock_code,
        annual_count=annual_count,
        quarter_count=quarter_count,
        fs_div=fs_div,
    )


def update_company_storage(
    corp_code,
    company_name,
    stock_code=None,
    annual_count=5,
    quarter_count=20,
    fs_div="AUTO",
    as_of_year=None,
):
    """
    기존 Master가 있으면 최신 가능 연도만 다시 확인해 증분 갱신한다.

    - 연간: 현재연도와 직전연도 사업보고서를 확인
    - 분기: 현재연도와 직전연도의 Q1~Q4를 확인

    직전연도를 함께 확인하는 이유는 새해 초 사업보고서가 제출되면서
    전년도 Q4가 처음 계산 가능해지는 경우를 반영하기 위해서다.
    """

    if not storage_exists(
        stock_code=stock_code,
        corp_code=corp_code,
    ) or storage_needs_rebuild(
        stock_code=stock_code,
        corp_code=corp_code,
    ):
        if storage_exists(
            stock_code=stock_code,
            corp_code=corp_code,
        ):
            print(
                "  → 데이터 엔진 버전 변경 감지. "
                "Master Data 전체 재구축"
            )
        annual_df, quarterly_df = bootstrap_company_storage(
            corp_code=corp_code,
            company_name=company_name,
            stock_code=stock_code,
            annual_count=annual_count,
            quarter_count=quarter_count,
            fs_div=fs_div,
        )
        return annual_df, quarterly_df, True

    annual_df, quarterly_df = load_company_storage(
        stock_code=stock_code,
        corp_code=corp_code,
    )

    current_year = int(as_of_year or date.today().year)
    changed = False

    # 최신 사업보고서 및 직전연도 정정 가능성 확인
    for year in (current_year, current_year - 1):
        try:
            incoming_annual = collect_annual_year_accounts(
                corp_code=corp_code,
                company_name=company_name,
                year=year,
                fs_div=fs_div,
            )
        except DartNoDataError:
            continue

        if _annual_period_changed(annual_df, incoming_annual, year):
            print(f"  → 연간 {year} FY 신규/변경 감지")
            annual_df = _replace_annual_period(
                annual_df,
                incoming_annual,
                year,
            )
            changed = True

    # 최신 분기 및 전년도 Q4/정정 가능성 확인
    for year in (current_year - 1, current_year):
        incoming_year = collect_year_quarters(
            corp_code=corp_code,
            company_name=company_name,
            year=year,
            fs_div=fs_div,
        )

        if incoming_year.empty:
            continue

        for period in incoming_year["period"].dropna().unique():
            incoming_period = incoming_year[
                incoming_year["period"].eq(period)
            ].copy()

            if _quarter_period_changed(
                quarterly_df,
                incoming_period,
                period,
            ):
                print(f"  → 분기 {period} 신규/변경 감지")
                quarterly_df = _replace_quarter_period(
                    quarterly_df,
                    incoming_period,
                    period,
                )
                changed = True

    annual_df = trim_recent_annual(annual_df, count=annual_count)
    quarterly_df = trim_recent_quarterly(
        quarterly_df,
        count=quarter_count,
    )

    if changed:
        save_company_storage(
            annual_df=annual_df,
            quarterly_df=quarterly_df,
            company_name=company_name,
            corp_code=corp_code,
            stock_code=stock_code,
        )
        print("  → Master Data 저장 완료")
    else:
        print("  → 신규/변경 재무공시 없음. Master Data 유지")

    return annual_df, quarterly_df, changed

