from datetime import date

import numpy as np
import pandas as pd

from src.financials import (
    DartNoDataError,
    get_financial_statements_auto,
)
from src.normalize import normalize_all_accounts


REPORT_CODES = {
    "Q1": "11013",
    "Q2": "11012",  # 반기보고서
    "Q3": "11014",
    "Q4": "11011",  # 사업보고서
}

QUARTER_NUMBERS = {
    "Q1": 1,
    "Q2": 2,
    "Q3": 3,
    "Q4": 4,
}

DEFAULT_DISPLAY_QUARTERS = 20
DEFAULT_BUFFER_QUARTERS = 4


INVALID_ACCOUNT_IDS = {
    "",
    "-표준계정코드 미사용-",
    "<NA>",
    "nan",
    "None",
}


def _prepare_source_frame(
    raw_df,
    company_name,
    year,
    quarter,
    fs_div_source,
):
    df = normalize_all_accounts(raw_df)

    df.insert(0, "company", company_name)
    df.insert(1, "year", int(year))
    df.insert(2, "quarter", quarter)
    df.insert(3, "quarter_num", QUARTER_NUMBERS[quarter])
    df.insert(4, "period", f"{year} {quarter}")
    df.insert(5, "fs_div_source", fs_div_source)

    return df


def _normalize_account_name_for_key(series):
    """
    account_id가 없는 계정을 분기간 매칭할 때 사용하는 보조 정규화.
    앞쪽 번호·로마숫자 표현 정도만 제거하고 원래 계정명은 보존한다.
    """

    return (
        series
        .astype("string")
        .fillna("")
        .str.strip()
        .str.replace(
            r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|\d+[.)])\s*",
            "",
            regex=True,
        )
        .str.replace(
            r"^(?:당기|분기|반기)(?=(?:순이익|순손익|총포괄손익))",
            "",
            regex=True,
        )
    )


def _add_account_key(df):
    """
    분기간 동일 계정을 매칭하기 위한 Key를 만든다.

    1순위: 재무제표 그룹 + account_id + currency
    2순위: 재무제표 그룹 + 정규화 account_nm + account_detail + currency

    계정명이나 account_detail이 바뀌더라도 유효한 account_id가
    같으면 동일 계정으로 본다. IS와 CIS는 같은 손익계정 그룹으로
    처리한다.
    """

    result = df.copy()

    statement = (
        result["sj_div"]
        .astype("string")
        .fillna("")
        .str.strip()
    )
    statement_group = statement.replace(
        {
            "IS": "INCOME",
            "CIS": "INCOME",
        }
    )

    if "account_id" in result.columns:
        account_id = (
            result["account_id"]
            .astype("string")
            .fillna("")
            .str.strip()
        )
    else:
        account_id = pd.Series("", index=result.index, dtype="string")

    if "account_nm" in result.columns:
        account_name = _normalize_account_name_for_key(
            result["account_nm"]
        )
    else:
        account_name = pd.Series("", index=result.index, dtype="string")

    if "account_detail" in result.columns:
        account_detail = (
            result["account_detail"]
            .astype("string")
            .fillna("")
            .str.strip()
        )
    else:
        account_detail = pd.Series("", index=result.index, dtype="string")

    if "currency" in result.columns:
        currency = (
            result["currency"]
            .astype("string")
            .fillna("")
            .str.strip()
        )
    else:
        currency = pd.Series("", index=result.index, dtype="string")

    valid_account_id = ~account_id.isin(INVALID_ACCOUNT_IDS)

    id_key = (
        statement_group
        + "||ID||"
        + account_id
        + "||"
        + currency
    )

    name_key = (
        statement_group
        + "||NAME||"
        + account_name
        + "||"
        + account_detail
        + "||"
        + currency
    )

    result["_account_id_valid"] = valid_account_id
    result["_account_id_key"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )
    result.loc[
        valid_account_id,
        "_account_id_key",
    ] = id_key[valid_account_id]
    result["_account_name_key"] = name_key
    result["_account_key"] = name_key
    result.loc[
        valid_account_id,
        "_account_key",
    ] = id_key[valid_account_id]

    return result


def _cumulative_series(df):
    """
    누적금액이 존재하면 thstrm_add_amount를 우선 사용하고,
    없으면 thstrm_amount를 보조적으로 사용한다.
    """

    if "thstrm_add_amount" in df.columns:
        cumulative = df["thstrm_add_amount"].copy()
    else:
        cumulative = pd.Series(np.nan, index=df.index)

    if "thstrm_amount" in df.columns:
        cumulative = cumulative.where(
            cumulative.notna(),
            df["thstrm_amount"],
        )

    return pd.to_numeric(
        cumulative,
        errors="coerce",
    )


def _unambiguous_value_map(df, key_column):
    values = df[
        [key_column, "_cumulative"]
    ].dropna(subset=[key_column])

    if values.empty:
        return pd.Series(dtype="float64")

    value_counts = (
        values
        .groupby(key_column, dropna=False)["_cumulative"]
        .nunique(dropna=False)
    )
    unambiguous_keys = value_counts[
        value_counts.eq(1)
    ].index

    return (
        values[values[key_column].isin(unambiguous_keys)]
        .drop_duplicates(key_column, keep="first")
        .set_index(key_column)["_cumulative"]
    )


def _previous_cumulative_values(current_df, previous_df):
    """
    이전 누적금액을 ID 우선으로 찾는다.

    현재 ID가 유효하면 이전의 같은 ID를 먼저 사용하고, 이전 ID가
    결측인 행에 한해서만 이름 fallback을 허용한다. 현재 ID가
    결측이면 이전 전체 행에서 이름 fallback을 사용한다.
    """

    if previous_df is None or previous_df.empty:
        return pd.Series(
            np.nan,
            index=current_df.index,
            dtype="float64",
        )

    previous = _add_account_key(previous_df)
    previous["_cumulative"] = _cumulative_series(previous)

    id_map = _unambiguous_value_map(
        previous,
        "_account_id_key",
    )
    all_name_map = _unambiguous_value_map(
        previous,
        "_account_name_key",
    )
    missing_id_name_map = _unambiguous_value_map(
        previous[~previous["_account_id_valid"]],
        "_account_name_key",
    )

    id_values = current_df["_account_id_key"].map(
        id_map
    )
    all_name_values = current_df[
        "_account_name_key"
    ].map(all_name_map)
    missing_id_name_values = current_df[
        "_account_name_key"
    ].map(missing_id_name_map)

    result = all_name_values.copy()
    current_has_id = current_df[
        "_account_id_valid"
    ]
    result.loc[current_has_id] = id_values.loc[
        current_has_id
    ].where(
        id_values.loc[current_has_id].notna(),
        missing_id_name_values.loc[current_has_id],
    )

    return pd.to_numeric(
        result,
        errors="coerce",
    )


def _frame_fs_div(df):
    if df is None or df.empty or "fs_div_source" not in df.columns:
        return ""

    values = (
        df["fs_div_source"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    values = values[values.ne("")].unique().tolist()

    if len(values) == 1:
        return values[0]

    return ""


def _same_fs_div(current_df, previous_df):
    current_fs = _frame_fs_div(current_df)
    previous_fs = _frame_fs_div(previous_df)

    if not current_fs or not previous_fs:
        return False

    return current_fs == previous_fs


def _quarterize_frame(
    current_df,
    quarter,
    previous_df=None,
):
    """
    DART 보고서 한 건을 '개별 분기' 관점으로 정리한다.

    BS      : 각 분기말 시점잔액
    IS/CIS  : Q1~Q3는 DART thstrm_amount(3개월 금액),
              Q4는 FY - 9M 누적
    CF      : 누적현금흐름을 분기간 차감하여 개별 분기값 계산
    SCE     : 원본은 보존하되 개별 분기값은 만들지 않음

    quarter_amount_basis와 calculation_status를 함께 남겨
    각 숫자의 생성 근거와 실패 원인을 추적할 수 있게 한다.
    """

    result = _add_account_key(current_df)
    result["quarter_amount"] = np.nan
    result["quarter_amount_basis"] = pd.Series(
        "not_quarterized",
        index=result.index,
        dtype="string",
    )
    result["calculation_status"] = pd.Series(
        "NOT_QUARTERIZED",
        index=result.index,
        dtype="string",
    )

    statement = result["sj_div"].astype("string")

    if "thstrm_amount" in result.columns:
        current_amount = result["thstrm_amount"]
    else:
        current_amount = pd.Series(np.nan, index=result.index)

    # BS: 시점 잔액
    bs_mask = statement.eq("BS")
    bs_valid = bs_mask & current_amount.notna()
    result.loc[bs_valid, "quarter_amount"] = current_amount[bs_valid]
    result.loc[bs_mask, "quarter_amount_basis"] = "point_in_time"
    result.loc[bs_valid, "calculation_status"] = "OK"
    result.loc[
        bs_mask & ~bs_valid,
        "calculation_status",
    ] = "AMOUNT_MISSING"

    # IS / CIS
    income_mask = statement.isin(["IS", "CIS"])

    if quarter in {"Q1", "Q2", "Q3"}:
        income_valid = income_mask & current_amount.notna()
        result.loc[
            income_valid,
            "quarter_amount",
        ] = current_amount[income_valid]
        result.loc[
            income_mask,
            "quarter_amount_basis",
        ] = "dart_3month_amount"
        result.loc[
            income_valid,
            "calculation_status",
        ] = "OK"
        result.loc[
            income_mask & ~income_valid,
            "calculation_status",
        ] = "AMOUNT_MISSING"

    else:
        result.loc[
            income_mask,
            "quarter_amount_basis",
        ] = "fy_minus_q3_ytd"

        if previous_df is None or previous_df.empty:
            result.loc[
                income_mask,
                "calculation_status",
            ] = "PREVIOUS_PERIOD_MISSING"
        elif not _same_fs_div(current_df, previous_df):
            result.loc[
                income_mask,
                "calculation_status",
            ] = "FS_DIV_MISMATCH"
        else:
            previous_values = _previous_cumulative_values(
                result,
                previous_df,
            )

            valid = (
                income_mask
                & current_amount.notna()
                & previous_values.notna()
            )

            result.loc[valid, "quarter_amount"] = (
                current_amount[valid]
                - previous_values[valid]
            )
            result.loc[valid, "calculation_status"] = "OK"

            missing_previous = (
                income_mask
                & current_amount.notna()
                & previous_values.isna()
            )
            missing_current = income_mask & current_amount.isna()

            result.loc[
                missing_previous,
                "calculation_status",
            ] = "PREVIOUS_ACCOUNT_MISSING"
            result.loc[
                missing_current,
                "calculation_status",
            ] = "AMOUNT_MISSING"

    # CF: 누적값 차감
    cf_mask = statement.eq("CF")
    current_cumulative = _cumulative_series(result)

    if quarter == "Q1":
        valid = cf_mask & current_cumulative.notna()
        result.loc[valid, "quarter_amount"] = current_cumulative[valid]
        result.loc[
            cf_mask,
            "quarter_amount_basis",
        ] = "q1_ytd"
        result.loc[valid, "calculation_status"] = "OK"
        result.loc[
            cf_mask & ~valid,
            "calculation_status",
        ] = "AMOUNT_MISSING"

    else:
        basis = {
            "Q2": "h1_ytd_minus_q1_ytd",
            "Q3": "q3_ytd_minus_h1_ytd",
            "Q4": "fy_minus_q3_ytd",
        }[quarter]

        result.loc[
            cf_mask,
            "quarter_amount_basis",
        ] = basis

        if previous_df is None or previous_df.empty:
            result.loc[
                cf_mask,
                "calculation_status",
            ] = "PREVIOUS_PERIOD_MISSING"
        elif not _same_fs_div(current_df, previous_df):
            result.loc[
                cf_mask,
                "calculation_status",
            ] = "FS_DIV_MISMATCH"
        else:
            previous_values = _previous_cumulative_values(
                result,
                previous_df,
            )

            valid = (
                cf_mask
                & current_cumulative.notna()
                & previous_values.notna()
            )

            result.loc[valid, "quarter_amount"] = (
                current_cumulative[valid]
                - previous_values[valid]
            )
            result.loc[valid, "calculation_status"] = "OK"

            missing_previous = (
                cf_mask
                & current_cumulative.notna()
                & previous_values.isna()
            )
            missing_current = cf_mask & current_cumulative.isna()

            result.loc[
                missing_previous,
                "calculation_status",
            ] = "PREVIOUS_ACCOUNT_MISSING"
            result.loc[
                missing_current,
                "calculation_status",
            ] = "AMOUNT_MISSING"

    return result.drop(
        columns=[
            "_account_key",
            "_account_id_key",
            "_account_name_key",
            "_account_id_valid",
        ]
    )


def collect_year_quarters(
    corp_code,
    company_name,
    year,
    fs_div="AUTO",
):
    """
    한 사업연도에 존재하는 Q1~Q4 보고서를 가져와
    개별 분기 기준 데이터로 변환한다.
    """

    source_frames = {}

    for quarter in ("Q1", "Q2", "Q3", "Q4"):
        report_code = REPORT_CODES[quarter]

        try:
            raw_df, used_fs_div = get_financial_statements_auto(
                corp_code=corp_code,
                year=year,
                report_code=report_code,
                fs_div=fs_div,
            )
        except DartNoDataError:
            continue

        source_frames[quarter] = _prepare_source_frame(
            raw_df=raw_df,
            company_name=company_name,
            year=year,
            quarter=quarter,
            fs_div_source=used_fs_div,
        )

    results = []

    for quarter in ("Q1", "Q2", "Q3", "Q4"):
        if quarter not in source_frames:
            continue

        previous_quarter = {
            "Q1": None,
            "Q2": "Q1",
            "Q3": "Q2",
            "Q4": "Q3",
        }[quarter]

        previous_df = (
            source_frames.get(previous_quarter)
            if previous_quarter
            else None
        )

        results.append(
            _quarterize_frame(
                current_df=source_frames[quarter],
                quarter=quarter,
                previous_df=previous_df,
            )
        )

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def _quarter_index_series(df):
    return (
        pd.to_numeric(df["year"], errors="coerce").astype(int) * 4
        + pd.to_numeric(df["quarter_num"], errors="coerce").astype(int)
    )


def select_recent_quarters(
    quarterly_df,
    count=DEFAULT_DISPLAY_QUARTERS,
):
    """계산이 끝난 데이터에서 최근 count개 분기만 선택한다."""

    if quarterly_df.empty:
        return quarterly_df.copy()

    if count <= 0:
        raise ValueError("count는 1 이상이어야 합니다.")

    result = quarterly_df.copy()
    result["_quarter_index"] = _quarter_index_series(result)

    periods = (
        result[["year", "quarter_num", "period", "_quarter_index"]]
        .drop_duplicates()
        .sort_values("_quarter_index")
        .tail(count)
    )

    keep_periods = periods["period"].tolist()
    result = result[result["period"].isin(keep_periods)].copy()

    sort_columns = ["_quarter_index", "sj_div"]
    if "ord" in result.columns:
        sort_columns.append("ord")

    return (
        result
        .sort_values(sort_columns, na_position="last")
        .drop(columns=["_quarter_index"])
        .reset_index(drop=True)
    )


def collect_quarterly_calculation_window(
    corp_code,
    company_name,
    display_count=DEFAULT_DISPLAY_QUARTERS,
    buffer_quarters=DEFAULT_BUFFER_QUARTERS,
    fs_div="AUTO",
    as_of_year=None,
    max_lookback_years=10,
):
    """
    표시 분기보다 더 긴 계산용 window를 확보한다.

    기본값은 20개 표시 + 4개 buffer = 최대 최근 24개 분기다.
    오래된 첫 표시 분기의 계산에 필요한 직전 분기를 buffer로 확보한다.
    """

    if display_count <= 0:
        raise ValueError("display_count는 1 이상이어야 합니다.")

    if buffer_quarters < 0:
        raise ValueError("buffer_quarters는 0 이상이어야 합니다.")

    target_source_count = display_count + buffer_quarters
    current_year = int(as_of_year or date.today().year)

    yearly_frames = []
    available_periods = set()

    for offset in range(max_lookback_years + 1):
        year = current_year - offset
        print(f"{company_name} {year}년 분기보고서 확인 중...")

        year_df = collect_year_quarters(
            corp_code=corp_code,
            company_name=company_name,
            year=year,
            fs_div=fs_div,
        )

        if year_df.empty:
            print("  → 사용 가능한 분기 재무데이터 없음")
            continue

        yearly_frames.append(year_df)

        year_periods = set(
            year_df["period"]
            .dropna()
            .astype(str)
            .unique()
        )
        available_periods.update(year_periods)

        print(
            "  → 사용 가능 분기: "
            + ", ".join(sorted(year_periods))
        )

        if len(available_periods) >= target_source_count:
            break

    if len(available_periods) < display_count:
        raise DartNoDataError(
            f"최근 {display_count}개 표시 분기를 확보하지 못했습니다. "
            f"확보 분기 수: {len(available_periods)}"
        )

    if len(available_periods) < target_source_count:
        print(
            f"  → 계산용 buffer 일부 부족: "
            f"목표 {target_source_count}개 / 확보 {len(available_periods)}개"
        )

    calculation_df = pd.concat(
        yearly_frames,
        ignore_index=True,
    )

    calculation_df["_quarter_index"] = _quarter_index_series(
        calculation_df
    )

    source_periods = (
        calculation_df[
            ["year", "quarter_num", "period", "_quarter_index"]
        ]
        .drop_duplicates()
        .sort_values("_quarter_index")
        .tail(target_source_count)
    )

    keep_periods = source_periods["period"].tolist()
    calculation_df = calculation_df[
        calculation_df["period"].isin(keep_periods)
    ].copy()

    sort_columns = ["_quarter_index", "sj_div"]
    if "ord" in calculation_df.columns:
        sort_columns.append("ord")

    return (
        calculation_df
        .sort_values(sort_columns, na_position="last")
        .drop(columns=["_quarter_index"])
        .reset_index(drop=True)
    )


def collect_recent_quarterly_accounts(
    corp_code,
    company_name,
    count=DEFAULT_DISPLAY_QUARTERS,
    buffer_quarters=DEFAULT_BUFFER_QUARTERS,
    fs_div="AUTO",
    as_of_year=None,
    max_lookback_years=10,
):
    """
    계산용 buffer를 포함해 먼저 충분한 분기를 계산한 뒤,
    사용자에게는 최근 count개 분기만 반환한다.
    """

    calculation_df = collect_quarterly_calculation_window(
        corp_code=corp_code,
        company_name=company_name,
        display_count=count,
        buffer_quarters=buffer_quarters,
        fs_div=fs_div,
        as_of_year=as_of_year,
        max_lookback_years=max_lookback_years,
    )

    return select_recent_quarters(
        calculation_df,
        count=count,
    )

