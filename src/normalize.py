import numpy as np
import pandas as pd

from config.accounts import STANDARD_ACCOUNTS


def clean_amount(value):
    """
    DART의 금액 문자열을 숫자로 변환한다.

    예:
    '2,450,000,000' -> 2450000000
    '(100,000)'     -> -100000
    ''              -> NaN
    """

    if value is None:
        return np.nan

    value = str(value).strip()

    if value in ["", "-", "None", "nan", "<NA>"]:
        return np.nan

    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]

    value = value.replace(",", "")

    return pd.to_numeric(
        value,
        errors="coerce",
    )


def normalize_all_accounts(df):
    """
    DART 전체 재무제표 계정을 최대한 그대로 보존하면서
    텍스트 공백과 금액 컬럼을 정리한다.
    """

    result = df.copy()

    text_columns = [
        "sj_div",
        "sj_nm",
        "account_id",
        "account_nm",
        "account_detail",
        "currency",
    ]

    for col in text_columns:
        if col in result.columns:
            result[col] = (
                result[col]
                .astype("string")
                .str.strip()
            )

    amount_columns = [
        "thstrm_amount",
        "thstrm_add_amount",
        "frmtrm_amount",
        "frmtrm_q_amount",
        "frmtrm_add_amount",
        "bfefrmtrm_amount",
    ]

    for col in amount_columns:
        if col in result.columns:
            result[col] = result[col].apply(clean_amount)

    return result


def extract_standard_accounts(df):
    """
    전체 계정 중 분석용 표준계정을 추출한다.

    우선순위는 account_id이고, account_nm은 보조 기준이다.
    계정명이 연도별로 달라져도 동일한 XBRL account_id라면
    같은 표준계정으로 인식한다.
    """

    if df.empty:
        return pd.DataFrame()

    if "sj_div" not in df.columns:
        raise ValueError(
            "표준계정 추출에는 sj_div 컬럼이 필요합니다."
        )

    results = []

    # 같은 회사·보고기간·재무제표 구분 안에서 표준계정 하나를
    # 선택한다. 존재하는 컬럼만 사용하므로 연간/분기 DataFrame에
    # 동일한 함수를 적용할 수 있다.
    group_columns = [
        col
        for col in [
            "company",
            "year",
            "quarter",
            "period",
            "fs_div_source",
        ]
        if col in df.columns
    ]

    for standard_name, config in STANDARD_ACCOUNTS.items():
        statement_types = config.get("statement", [])
        account_ids = config.get("account_ids", [])
        account_names = config.get("names", [])

        candidates = df[
            df["sj_div"].isin(statement_types)
        ].copy()

        if candidates.empty:
            continue

        if "account_id" in candidates.columns:
            id_priority = {
                account_id: rank
                for rank, account_id in enumerate(account_ids)
            }
            candidates["_id_rank"] = (
                candidates["account_id"]
                .map(id_priority)
            )
        else:
            candidates["_id_rank"] = pd.NA

        if "account_nm" in candidates.columns:
            name_priority = {
                account_name: rank
                for rank, account_name in enumerate(account_names)
            }
            candidates["_name_rank"] = (
                candidates["account_nm"]
                .map(name_priority)
            )
        else:
            candidates["_name_rank"] = pd.NA

        matched = candidates[
            candidates["_id_rank"].notna()
            | candidates["_name_rank"].notna()
        ].copy()

        if matched.empty:
            continue

        id_matched = matched["_id_rank"].notna()
        matched["standard_account_match"] = (
            "account_nm"
        )
        matched.loc[
            id_matched,
            "standard_account_match",
        ] = "account_id"

        matched["_match_source_rank"] = 1
        matched.loc[
            id_matched,
            "_match_source_rank",
        ] = 0
        matched["_mapping_rank"] = matched[
            "_name_rank"
        ]
        matched.loc[
            id_matched,
            "_mapping_rank",
        ] = matched.loc[
            id_matched,
            "_id_rank",
        ]

        sort_columns = (
            group_columns
            + ["_match_source_rank", "_mapping_rank"]
        )
        if "ord" in matched.columns:
            sort_columns.append("ord")

        matched = matched.sort_values(
            sort_columns,
            na_position="last",
        )

        if group_columns:
            matched = matched.drop_duplicates(
                subset=group_columns,
                keep="first",
            )
        else:
            matched = matched.head(1)

        matched["standard_account"] = standard_name
        matched = matched.drop(
            columns=[
                "_id_rank",
                "_name_rank",
                "_match_source_rank",
                "_mapping_rank",
            ]
        )
        results.append(matched)

    if not results:
        return pd.DataFrame()

    return pd.concat(
        results,
        ignore_index=True,
    )

