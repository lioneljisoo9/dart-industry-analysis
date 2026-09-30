import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from config.settings import get_dart_api_key
from src.dart_client import BASE_URL
from src.normalize import normalize_all_accounts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_FINANCIAL_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "financials"


class DartAPIError(RuntimeError):
    """OpenDART API 호출 자체가 실패했을 때 사용하는 예외."""


class DartNoDataError(DartAPIError):
    """요청한 회사/연도/보고서에 재무데이터가 없을 때 사용하는 예외."""


def _safe_path_component(value):
    text = re.sub(
        r"[^0-9A-Za-z가-힣_-]+",
        "_",
        str(value).strip(),
    )
    return text.strip("._") or "unknown"


def _raw_receipt_key(data):
    receipt_numbers = sorted(
        {
            str(row.get("rcept_no") or "").strip()
            for row in data.get("list", [])
            if str(row.get("rcept_no") or "").strip()
        }
    )

    if not receipt_numbers:
        return "no_receipt"

    return "_".join(receipt_numbers)


def _save_raw_financial_response(
    data,
    corp_code,
    year,
    report_code,
    fs_div,
):
    """API Key를 제외한 요청 정보와 DART 원본 응답을 보존한다."""

    corp_directory = (
        RAW_FINANCIAL_DIRECTORY
        / _safe_path_component(corp_code)
        / str(int(year))
    )
    corp_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    receipt_key = _safe_path_component(
        _raw_receipt_key(data)
    )
    filename = (
        f"{_safe_path_component(report_code)}_"
        f"{_safe_path_component(fs_div)}_"
        f"{receipt_key}.json"
    )
    path = corp_directory / filename
    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    payload = {
        "retrieved_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "request": {
            "corp_code": str(corp_code),
            "bsns_year": str(year),
            "reprt_code": str(report_code),
            "fs_div": str(fs_div),
        },
        "response": data,
    }

    temp_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temp_path.replace(path)

    return path


def get_financial_statements(
    corp_code,
    year,
    report_code="11011",
    fs_div="CFS",
):
    """
    OpenDART에서 단일 회사의 전체 재무제표를 가져온다.

    report_code
    11011 : 사업보고서
    11012 : 반기보고서
    11013 : 1분기보고서
    11014 : 3분기보고서

    fs_div
    CFS : 연결재무제표
    OFS : 별도재무제표
    """

    if fs_div not in {"CFS", "OFS"}:
        raise ValueError(
            "get_financial_statements()의 fs_div는 "
            "'CFS' 또는 'OFS'여야 합니다."
        )

    url = f"{BASE_URL}/fnlttSinglAcntAll.json"

    params = {
        "crtfc_key": get_dart_api_key(),
        "corp_code": str(corp_code),
        "bsns_year": str(year),
        "reprt_code": str(report_code),
        "fs_div": fs_div,
    }

    response = requests.get(
        url,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    status = data.get("status")
    message = data.get("message")

    if status == "013":
        raise DartNoDataError(
            f"DART 조회 데이터 없음 "
            f"[{year} / {report_code} / {fs_div}]"
        )

    if status != "000":
        raise DartAPIError(
            f"DART API 오류 "
            f"[{year} / {report_code} / {fs_div}] "
            f"{status} - {message}"
        )

    _save_raw_financial_response(
        data=data,
        corp_code=corp_code,
        year=year,
        report_code=report_code,
        fs_div=fs_div,
    )

    return pd.DataFrame(data.get("list", []))


def get_financial_statements_auto(
    corp_code,
    year,
    report_code="11011",
    fs_div="AUTO",
):
    """
    재무제표를 가져오고 실제 사용된 fs_div도 함께 반환한다.

    fs_div='AUTO'이면 연결(CFS)을 먼저 시도하고,
    연결재무제표가 없을 때 별도(OFS)를 시도한다.
    """

    if fs_div in {"CFS", "OFS"}:
        df = get_financial_statements(
            corp_code=corp_code,
            year=year,
            report_code=report_code,
            fs_div=fs_div,
        )
        return df, fs_div

    if fs_div != "AUTO":
        raise ValueError(
            "fs_div는 'AUTO', 'CFS', 'OFS' 중 하나여야 합니다."
        )

    no_data_errors = []

    for candidate in ("CFS", "OFS"):
        try:
            df = get_financial_statements(
                corp_code=corp_code,
                year=year,
                report_code=report_code,
                fs_div=candidate,
            )
            return df, candidate
        except DartNoDataError as exc:
            no_data_errors.append(str(exc))

    raise DartNoDataError(
        f"DART 조회 데이터 없음 "
        f"[{year} / {report_code} / CFS·OFS 모두 없음]"
    )


def _prepare_annual_frame(
    raw_df,
    company_name,
    year,
    fs_div_source,
):
    all_df = normalize_all_accounts(raw_df)

    all_df.insert(0, "company", company_name)
    all_df.insert(1, "year", int(year))
    all_df.insert(2, "period", f"{year} FY")
    all_df.insert(3, "fs_div_source", fs_div_source)

    return all_df


def collect_annual_year_accounts(
    corp_code,
    company_name,
    year,
    fs_div="AUTO",
):
    """한 사업연도의 사업보고서 전체 재무계정을 수집한다."""

    raw_df, used_fs_div = get_financial_statements_auto(
        corp_code=corp_code,
        year=year,
        report_code="11011",
        fs_div=fs_div,
    )

    return _prepare_annual_frame(
        raw_df=raw_df,
        company_name=company_name,
        year=year,
        fs_div_source=used_fs_div,
    )


def collect_annual_all_accounts(
    corp_code,
    company_name,
    start_year,
    end_year,
    fs_div="AUTO",
):
    """
    지정한 연도 구간의 사업보고서를 순서대로 수집한다.

    기존 코드와의 호환을 위해 유지하는 함수다.
    """

    results = []

    for year in range(int(start_year), int(end_year) + 1):
        print(f"{company_name} {year}년 사업보고서 수집 중...")

        raw_df, used_fs_div = get_financial_statements_auto(
            corp_code=corp_code,
            year=year,
            report_code="11011",
            fs_div=fs_div,
        )

        all_df = _prepare_annual_frame(
            raw_df=raw_df,
            company_name=company_name,
            year=year,
            fs_div_source=used_fs_div,
        )
        results.append(all_df)

        print(f"  → {len(all_df):,}개 계정 행 수집 완료")

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def collect_recent_annual_accounts(
    corp_code,
    company_name,
    count=5,
    fs_div="AUTO",
    as_of_year=None,
    max_lookback_years=12,
):
    """
    현재 시점을 기준으로 가장 최근에 존재하는 사업보고서 count개를 수집한다.

    예: 2026년 사업보고서가 아직 없으면
        2025, 2024, 2023, 2022, 2021 사업보고서를 수집한다.
    """

    if count <= 0:
        raise ValueError("count는 1 이상이어야 합니다.")

    current_year = int(as_of_year or date.today().year)
    results = []
    collected_years = []

    for offset in range(max_lookback_years + 1):
        year = current_year - offset

        try:
            print(f"{company_name} {year}년 사업보고서 확인 중...")

            raw_df, used_fs_div = get_financial_statements_auto(
                corp_code=corp_code,
                year=year,
                report_code="11011",
                fs_div=fs_div,
            )
        except DartNoDataError:
            print("  → 사업보고서 재무데이터 없음, 이전 연도 확인")
            continue

        all_df = _prepare_annual_frame(
            raw_df=raw_df,
            company_name=company_name,
            year=year,
            fs_div_source=used_fs_div,
        )
        results.append(all_df)
        collected_years.append(year)

        print(f"  → {len(all_df):,}개 계정 행 수집 완료")

        if len(collected_years) >= count:
            break

    if len(collected_years) < count:
        raise DartNoDataError(
            f"최근 사업보고서 {count}개를 확보하지 못했습니다. "
            f"확보 연도: {sorted(collected_years)}"
        )

    annual_df = pd.concat(results, ignore_index=True)
    annual_df = annual_df.sort_values(
        ["year", "sj_div", "ord"],
        na_position="last",
    ).reset_index(drop=True)

    return annual_df

