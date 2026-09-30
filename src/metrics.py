import numpy as np
import pandas as pd

from config.accounts import STANDARD_ACCOUNTS
from src.normalize import extract_standard_accounts


AMOUNT_ACCOUNTS = tuple(STANDARD_ACCOUNTS)

BASE_COLUMNS = (
    "company",
    "corp_code",
    "year",
    "fs_div_source",
    "currency",
    "rcept_no",
    "available_account_count",
    "required_account_count",
    "account_completeness",
    "missing_accounts",
    "metric_status",
    "account_id_match_count",
    "account_nm_match_count",
)

CALCULATED_METRICS = (
    "revenue_growth_yoy",
    "operating_margin",
    "net_margin",
    "operating_cash_flow_margin",
    "operating_cash_flow_to_operating_profit",
    "inventory_growth_yoy",
    "inventory_to_revenue",
    "contract_assets_growth_yoy",
    "contract_assets_to_revenue",
    "contract_liabilities_growth_yoy",
    "contract_liabilities_to_revenue",
    "contract_net_position",
    "contract_net_position_to_revenue",
    "earnings_cash_gap",
    "earnings_cash_gap_to_revenue",
)

METRIC_DEFINITIONS = (
    {
        "metric": "revenue_growth_yoy",
        "label_ko": "매출액 전년 대비 증감률",
        "formula": "매출액 / 전기 매출액 - 1",
        "audit_relevance": "공사 진행과 매출인식 추세 검토",
    },
    {
        "metric": "operating_margin",
        "label_ko": "영업이익률",
        "formula": "영업이익 / 매출액",
        "audit_relevance": "예정원가 변경과 손실충당 추세 검토",
    },
    {
        "metric": "net_margin",
        "label_ko": "순이익률",
        "formula": "당기순이익 / 매출액",
        "audit_relevance": "영업외손익을 포함한 최종 수익성 검토",
    },
    {
        "metric": "operating_cash_flow_margin",
        "label_ko": "영업현금흐름률",
        "formula": "영업활동현금흐름 / 매출액",
        "audit_relevance": "인식 매출의 현금 전환 추세 검토",
    },
    {
        "metric": "operating_cash_flow_to_operating_profit",
        "label_ko": "영업이익 현금전환비율",
        "formula": "영업활동현금흐름 / 영업이익",
        "audit_relevance": "이익과 현금흐름의 괴리 검토",
    },
    {
        "metric": "inventory_growth_yoy",
        "label_ko": "재고자산 전년 대비 증감률",
        "formula": "재고자산 / 전기 재고자산 - 1",
        "audit_relevance": "재고 증가와 평가손실 위험 검토",
    },
    {
        "metric": "inventory_to_revenue",
        "label_ko": "매출액 대비 재고자산",
        "formula": "재고자산 / 매출액",
        "audit_relevance": "매출 규모 대비 재고 부담 검토",
    },
    {
        "metric": "contract_assets_growth_yoy",
        "label_ko": "계약자산 전년 대비 증감률",
        "formula": "계약자산 / 전기 계약자산 - 1",
        "audit_relevance": "미청구공사 증가와 매출인식 위험 검토",
    },
    {
        "metric": "contract_assets_to_revenue",
        "label_ko": "매출액 대비 계약자산",
        "formula": "계약자산 / 매출액",
        "audit_relevance": "수익 인식액 대비 미청구 잔액 검토",
    },
    {
        "metric": "contract_liabilities_growth_yoy",
        "label_ko": "계약부채 전년 대비 증감률",
        "formula": "계약부채 / 전기 계약부채 - 1",
        "audit_relevance": "선수금과 향후 수행의무 추세 검토",
    },
    {
        "metric": "contract_liabilities_to_revenue",
        "label_ko": "매출액 대비 계약부채",
        "formula": "계약부채 / 매출액",
        "audit_relevance": "매출 규모 대비 선수금 잔액 검토",
    },
    {
        "metric": "contract_net_position",
        "label_ko": "순계약자산",
        "formula": "계약자산 - 계약부채",
        "audit_relevance": "계약 관련 순자산·순부채 포지션 검토",
    },
    {
        "metric": "contract_net_position_to_revenue",
        "label_ko": "매출액 대비 순계약자산",
        "formula": "(계약자산 - 계약부채) / 매출액",
        "audit_relevance": "기업 간 계약 포지션 비교",
    },
    {
        "metric": "earnings_cash_gap",
        "label_ko": "영업이익-영업현금흐름 차이",
        "formula": "영업이익 - 영업활동현금흐름",
        "audit_relevance": "발생이익과 영업현금의 절대 차이 검토",
    },
    {
        "metric": "earnings_cash_gap_to_revenue",
        "label_ko": "매출액 대비 이익-현금흐름 차이",
        "formula": "(영업이익 - 영업활동현금흐름) / 매출액",
        "audit_relevance": "기업 규모를 조정한 이익·현금 괴리 비교",
    },
)


def metric_dictionary():
    """KPI 이름, 산식, 조선업 감사 관점의 해석 근거를 반환한다."""

    return pd.DataFrame(METRIC_DEFINITIONS)


def _require_columns(df, columns):
    missing = set(columns).difference(df.columns)
    if missing:
        raise ValueError(
            "연간 KPI 계산에 필요한 컬럼이 없습니다: "
            + ", ".join(sorted(missing))
        )


def _join_unique(values):
    unique_values = (
        values.dropna().astype(str).str.strip()
    )
    unique_values = sorted(
        value
        for value in unique_values.unique().tolist()
        if value and value not in {"<NA>", "nan", "None"}
    )
    return ", ".join(unique_values)


def _safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    valid = numerator.notna() & denominator.notna() & denominator.ne(0)
    result = pd.Series(np.nan, index=numerator.index, dtype="float64")
    result.loc[valid] = numerator.loc[valid] / denominator.loc[valid]
    return result


def _growth_rate(values, groups):
    previous = values.groupby(groups, sort=False).shift(1)
    return _safe_divide(values, previous) - 1


def _empty_metrics_frame():
    columns = list(BASE_COLUMNS) + list(AMOUNT_ACCOUNTS)
    columns += list(CALCULATED_METRICS)
    return pd.DataFrame(columns=columns)


def build_annual_metrics(annual_df):
    """
    DART 연간 전체계정 Master를 기업·연도별 비교 KPI로 변환한다.

    계산은 표준계정 Core에서 수행하며, 분모가 0이거나 계정이
    없으면 0으로 대체하지 않고 NaN으로 남긴다. 위험 판정은
    이 함수에서 하지 않아 산업별 기준과 재무 수치를 분리한다.
    """

    if annual_df is None or annual_df.empty:
        return _empty_metrics_frame()

    _require_columns(
        annual_df,
        {"company", "year", "sj_div", "thstrm_amount"},
    )

    core = extract_standard_accounts(annual_df)
    if core.empty:
        return _empty_metrics_frame()

    _require_columns(
        core,
        {
            "company",
            "year",
            "standard_account",
            "standard_account_match",
            "thstrm_amount",
        },
    )

    core = core.copy()
    if "corp_code" not in core.columns:
        core["corp_code"] = ""
    core["corp_code"] = core["corp_code"].fillna("").astype(str)
    core["year"] = pd.to_numeric(core["year"], errors="coerce")
    core["thstrm_amount"] = pd.to_numeric(
        core["thstrm_amount"],
        errors="coerce",
    )
    core = core[core["year"].notna()].copy()
    core["year"] = core["year"].astype(int)

    entity_columns = ["company", "corp_code", "year"]
    duplicate_mask = core.duplicated(
        entity_columns + ["standard_account"],
        keep=False,
    )
    if duplicate_mask.any():
        duplicate_rows = core.loc[
            duplicate_mask,
            entity_columns
            + ["standard_account", "fs_div_source"],
        ].drop_duplicates()
        raise ValueError(
            "동일 기업·연도·표준계정이 중복되어 KPI를 계산할 수 "
            "없습니다. CFS/OFS 선택을 확인하세요: "
            + duplicate_rows.to_dict(orient="records").__str__()
        )

    amounts = (
        core.pivot(
            index=entity_columns,
            columns="standard_account",
            values="thstrm_amount",
        )
        .reindex(columns=AMOUNT_ACCOUNTS)
        .reset_index()
    )
    amounts.columns.name = None

    for optional_column in ["fs_div_source", "currency", "rcept_no"]:
        if optional_column not in core.columns:
            core[optional_column] = ""

    metadata = (
        core.groupby(entity_columns, dropna=False)
        .agg(
            fs_div_source=("fs_div_source", _join_unique),
            currency=("currency", _join_unique),
            rcept_no=("rcept_no", _join_unique),
            available_account_count=("standard_account", "nunique"),
            account_id_match_count=(
                "standard_account_match",
                lambda values: int(values.eq("account_id").sum()),
            ),
            account_nm_match_count=(
                "standard_account_match",
                lambda values: int(values.eq("account_nm").sum()),
            ),
        )
        .reset_index()
    )

    result = metadata.merge(
        amounts,
        on=entity_columns,
        how="outer",
        validate="one_to_one",
    )
    result["required_account_count"] = len(AMOUNT_ACCOUNTS)
    result["account_completeness"] = _safe_divide(
        result["available_account_count"],
        result["required_account_count"],
    )
    result["missing_accounts"] = result.apply(
        lambda row: ", ".join(
            account
            for account in AMOUNT_ACCOUNTS
            if pd.isna(row[account])
        ),
        axis=1,
    )
    result["metric_status"] = np.where(
        result["missing_accounts"].eq(""),
        "COMPLETE",
        "PARTIAL_MISSING_ACCOUNT",
    )

    result = result.sort_values(
        ["company", "corp_code", "year"]
    ).reset_index(drop=True)
    company_groups = [result["company"], result["corp_code"]]

    result["revenue_growth_yoy"] = _growth_rate(
        result["revenue"], company_groups
    )
    result["operating_margin"] = _safe_divide(
        result["operating_profit"], result["revenue"]
    )
    result["net_margin"] = _safe_divide(
        result["net_income"], result["revenue"]
    )
    result["operating_cash_flow_margin"] = _safe_divide(
        result["operating_cash_flow"], result["revenue"]
    )
    result["operating_cash_flow_to_operating_profit"] = _safe_divide(
        result["operating_cash_flow"], result["operating_profit"]
    )
    result["inventory_growth_yoy"] = _growth_rate(
        result["inventory"], company_groups
    )
    result["inventory_to_revenue"] = _safe_divide(
        result["inventory"], result["revenue"]
    )
    result["contract_assets_growth_yoy"] = _growth_rate(
        result["contract_assets"], company_groups
    )
    result["contract_assets_to_revenue"] = _safe_divide(
        result["contract_assets"], result["revenue"]
    )
    result["contract_liabilities_growth_yoy"] = _growth_rate(
        result["contract_liabilities"], company_groups
    )
    result["contract_liabilities_to_revenue"] = _safe_divide(
        result["contract_liabilities"], result["revenue"]
    )
    result["contract_net_position"] = (
        result["contract_assets"] - result["contract_liabilities"]
    )
    result["contract_net_position_to_revenue"] = _safe_divide(
        result["contract_net_position"], result["revenue"]
    )
    result["earnings_cash_gap"] = (
        result["operating_profit"]
        - result["operating_cash_flow"]
    )
    result["earnings_cash_gap_to_revenue"] = _safe_divide(
        result["earnings_cash_gap"], result["revenue"]
    )

    ordered_columns = list(BASE_COLUMNS) + list(AMOUNT_ACCOUNTS)
    ordered_columns += list(CALCULATED_METRICS)
    return result.loc[:, ordered_columns]

