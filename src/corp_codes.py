import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from src.dart_client import (
    extract_corp_code_xml,
    get_corp_code_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORP_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "corp_codes.parquet"


def _download_corp_code_dataframe():
    """DART 전체 기업목록을 다운로드해 DataFrame으로 만든다."""

    zip_content = get_corp_code_file()
    xml_content = extract_corp_code_xml(zip_content)
    root = ET.fromstring(xml_content)

    rows = []

    for item in root.findall("list"):
        rows.append(
            {
                "corp_code": item.findtext("corp_code"),
                "corp_name": item.findtext("corp_name"),
                "stock_code": item.findtext("stock_code"),
                "modify_date": item.findtext("modify_date"),
            }
        )

    return pd.DataFrame(rows)


def get_corp_code_dataframe(refresh=False):
    """
    DART 전체 기업목록을 DataFrame으로 반환한다.

    로컬 cache가 있으면 평소에는 DART를 다시 호출하지 않는다.
    refresh=True이면 최신 기업목록을 다시 다운로드한다.
    """

    if CORP_CACHE_PATH.exists() and not refresh:
        return pd.read_parquet(CORP_CACHE_PATH)

    df = _download_corp_code_dataframe()
    CORP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CORP_CACHE_PATH, index=False)

    return df


def _normalize_company_name(value):
    """검색 비교용으로 기업명의 표기 차이를 정리한다."""

    if value is None:
        return ""

    normalized = unicodedata.normalize(
        "NFKC",
        str(value),
    ).casefold()

    # DART 기업명에 붙을 수 있는 법인 표기를 검색에서 제외한다.
    normalized = normalized.replace(
        "주식회사",
        "",
    )
    normalized = normalized.replace(
        "(주)",
        "",
    )

    # 공백과 일반적인 구분기호 차이도 무시한다.
    normalized = re.sub(
        r"[\s\-_.·,]+",
        "",
        normalized,
    )

    return normalized


def _validate_corp_dataframe(df):
    required_columns = {
        "corp_code",
        "corp_name",
        "stock_code",
    }
    missing_columns = required_columns.difference(
        df.columns
    )

    if missing_columns:
        missing_text = ", ".join(
            sorted(missing_columns)
        )
        raise ValueError(
            "기업목록에 필요한 컬럼이 없습니다: "
            f"{missing_text}"
        )


def _format_candidates(result, limit=10):
    candidates = []

    for _, row in result.head(limit).iterrows():
        stock_code = str(
            row.get("stock_code") or ""
        ).strip()
        stock_text = (
            f" / 종목코드 {stock_code}"
            if stock_code
            else " / 비상장"
        )
        candidates.append(
            f"{row['corp_name']}"
            f"{stock_text}"
        )

    return ", ".join(candidates)


def find_company_by_stock_code(
    df,
    stock_code,
):
    """6자리 종목코드로 하나의 기업을 찾는다."""

    _validate_corp_dataframe(df)

    stock_code = str(stock_code).strip()

    if stock_code.isdigit():
        stock_code = stock_code.zfill(6)

    result = df[
        df["stock_code"].fillna("").astype(str).str.strip()
        == stock_code
    ].copy()

    if result.empty:
        raise ValueError(
            f"종목코드 '{stock_code}'에 해당하는 기업을 "
            "찾지 못했습니다."
        )

    if len(result) > 1:
        raise ValueError(
            f"종목코드 '{stock_code}' 검색 결과가 "
            "여러 개입니다: "
            f"{_format_candidates(result)}"
        )

    return result.iloc[0]


def find_company_by_name(
    df,
    company_name,
):
    """
    기업명으로 하나의 기업을 찾는다.

    먼저 정규화된 기업명이 정확히 일치하는 회사를 찾고,
    정확한 결과가 없을 때만 부분 일치를 시도한다.
    여러 회사가 일치하면 임의로 선택하지 않고 후보를 안내한다.
    """

    _validate_corp_dataframe(df)

    search_name = str(
        company_name or ""
    ).strip()
    search_key = _normalize_company_name(
        search_name
    )

    if not search_key:
        raise ValueError(
            "기업명을 입력하세요."
        )

    search_df = df.copy()
    search_df["_normalized_name"] = (
        search_df["corp_name"]
        .fillna("")
        .map(_normalize_company_name)
    )

    exact_result = search_df[
        search_df["_normalized_name"]
        == search_key
    ].copy()

    if len(exact_result) == 1:
        return exact_result.drop(
            columns=["_normalized_name"]
        ).iloc[0]

    if len(exact_result) > 1:
        raise ValueError(
            f"'{search_name}' 검색 결과가 여러 개입니다: "
            f"{_format_candidates(exact_result)}"
        )

    partial_result = search_df[
        search_df["_normalized_name"].str.contains(
            re.escape(search_key),
            na=False,
        )
    ].copy()

    if len(partial_result) == 1:
        return partial_result.drop(
            columns=["_normalized_name"]
        ).iloc[0]

    if len(partial_result) > 1:
        raise ValueError(
            f"'{search_name}'에 해당하는 기업이 여러 개입니다. "
            "기업명을 더 정확히 입력하거나 종목코드를 사용하세요: "
            f"{_format_candidates(partial_result)}"
        )

    raise ValueError(
        f"'{search_name}'에 해당하는 기업을 찾지 못했습니다. "
        "DART 등록 기업명 또는 6자리 종목코드를 확인하세요."
    )


def find_company(
    df,
    query,
):
    """기업명 또는 6자리 종목코드로 하나의 기업을 찾는다."""

    query_text = str(query or "").strip()

    if query_text.isdigit() and len(query_text) <= 6:
        return find_company_by_stock_code(
            df,
            query_text,
        )

    return find_company_by_name(
        df,
        query_text,
    )

