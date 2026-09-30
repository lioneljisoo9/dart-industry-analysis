import numpy as np
import pandas as pd

from src.normalize import extract_standard_accounts


FLOW_ACCOUNTS = (
    "revenue",
    "operating_profit",
    "net_income",
    "operating_cash_flow",
)

STOCK_ACCOUNTS = (
    "inventory",
    "contract_assets",
    "contract_liabilities",
)

EXPECTED_QUARTERS = ("Q1", "Q2", "Q3", "Q4")

INVALID_ACCOUNT_IDS = {
    "",
    "-표준계정코드 미사용-",
    "<NA>",
    "nan",
    "None",
}

HARD_FAILURE_STATUSES = {
    "FAIL_DIFFERENCE",
    "FS_DIV_MISMATCH",
    "CURRENCY_MISMATCH",
    "CALCULATION_ERROR",
    "CORE_DUPLICATE",
    "AMOUNT_MISSING",
}


def _require_columns(df, columns, dataset_name):
    missing = set(columns).difference(df.columns)

    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            f"{dataset_name}에 필요한 컬럼이 없습니다: "
            f"{missing_text}"
        )


def _text_values(df, column):
    if df.empty or column not in df.columns:
        return []

    values = (
        df[column]
        .dropna()
        .astype(str)
        .str.strip()
    )

    return sorted(
        value
        for value in values.unique().tolist()
        if value
    )


def _joined_values(df, column):
    return ", ".join(_text_values(df, column))


def _account_id_status(annual_rows, quarter_rows):
    account_ids = set(
        _text_values(annual_rows, "account_id")
        + _text_values(quarter_rows, "account_id")
    )
    valid_ids = sorted(
        account_id
        for account_id in account_ids
        if account_id not in INVALID_ACCOUNT_IDS
    )

    if not valid_ids:
        return "MISSING"
    if len(valid_ids) == 1:
        return "CONSISTENT"
    return "CHANGED"


def _dimension_status(annual_rows, quarter_rows, column):
    values = set(
        _text_values(annual_rows, column)
        + _text_values(quarter_rows, column)
    )

    if not values:
        return "MISSING"
    if len(values) == 1:
        return "CONSISTENT"
    return "MISMATCH"


def _numeric_value(rows, column):
    if rows.empty or column not in rows.columns:
        return np.nan

    values = pd.to_numeric(
        rows[column],
        errors="coerce",
    ).dropna()

    if values.empty:
        return np.nan

    return float(values.iloc[0])


def _base_result(
    company,
    year,
    standard_account,
    validation_rule,
    comparison_basis,
    rounding_tolerance,
    annual_rows,
    quarter_rows,
):
    return {
        "company": company,
        "year": int(year),
        "standard_account": standard_account,
        "validation_rule": validation_rule,
        "comparison_basis": comparison_basis,
        "annual_amount": np.nan,
        "comparison_amount": np.nan,
        "difference": np.nan,
        "absolute_difference": np.nan,
        "tolerance": float(rounding_tolerance),
        "within_tolerance": False,
        "validation_status": "NOT_TESTABLE",
        "validation_message": "검증 조건을 확인하지 못했습니다.",
        "hard_failure": False,
        "quarters_found": _joined_values(
            quarter_rows,
            "quarter",
        ),
        "calculation_statuses": _joined_values(
            quarter_rows,
            "calculation_status",
        ),
        "annual_account_ids": _joined_values(
            annual_rows,
            "account_id",
        ),
        "quarter_account_ids": _joined_values(
            quarter_rows,
            "account_id",
        ),
        "account_id_status": _account_id_status(
            annual_rows,
            quarter_rows,
        ),
        "annual_match_method": _joined_values(
            annual_rows,
            "standard_account_match",
        ),
        "quarter_match_methods": _joined_values(
            quarter_rows,
            "standard_account_match",
        ),
        "annual_fs_div": _joined_values(
            annual_rows,
            "fs_div_source",
        ),
        "quarter_fs_div": _joined_values(
            quarter_rows,
            "fs_div_source",
        ),
        "fs_div_status": _dimension_status(
            annual_rows,
            quarter_rows,
            "fs_div_source",
        ),
        "annual_currency": _joined_values(
            annual_rows,
            "currency",
        ),
        "quarter_currency": _joined_values(
            quarter_rows,
            "currency",
        ),
        "currency_status": _dimension_status(
            annual_rows,
            quarter_rows,
            "currency",
        ),
    }


def _set_status(result, status, message):
    result["validation_status"] = status
    result["validation_message"] = message
    result["hard_failure"] = status in HARD_FAILURE_STATUSES
    return result


def _validate_common_conditions(
    result,
    annual_rows,
    comparison_rows,
):
    if annual_rows.empty:
        return _set_status(
            result,
            "NOT_TESTABLE_ANNUAL_MISSING",
            "연간 Core 계정이 없습니다.",
        )

    if len(annual_rows) > 1:
        return _set_status(
            result,
            "CORE_DUPLICATE",
            "같은 연도에 연간 Core 계정이 여러 개입니다.",
        )

    if result["fs_div_status"] == "MISMATCH":
        return _set_status(
            result,
            "FS_DIV_MISMATCH",
            "연간과 분기의 CFS/OFS 구분이 일치하지 않습니다.",
        )

    if result["currency_status"] == "MISMATCH":
        return _set_status(
            result,
            "CURRENCY_MISMATCH",
            "연간과 분기의 통화 단위가 일치하지 않습니다.",
        )

    if (
        "calculation_status" in comparison_rows.columns
        and not comparison_rows.empty
    ):
        calculation_statuses = set(
            _text_values(
                comparison_rows,
                "calculation_status",
            )
        )
        if calculation_statuses.difference({"OK"}):
            return _set_status(
                result,
                "CALCULATION_ERROR",
                "비교 대상 분기에 OK가 아닌 계산 상태가 있습니다.",
            )

    return None


def _complete_numeric_result(
    result,
    annual_amount,
    comparison_amount,
):
    result["annual_amount"] = annual_amount
    result["comparison_amount"] = comparison_amount

    if pd.isna(annual_amount) or pd.isna(comparison_amount):
        return _set_status(
            result,
            "AMOUNT_MISSING",
            "연간 또는 비교 금액이 없습니다.",
        )

    difference = comparison_amount - annual_amount
    absolute_difference = abs(difference)

    result["difference"] = difference
    result["absolute_difference"] = absolute_difference
    result["within_tolerance"] = (
        absolute_difference <= result["tolerance"]
    )

    if absolute_difference == 0:
        status = "PASS_EXACT"
        message = "연간 금액과 비교 금액이 정확히 일치합니다."
    elif result["within_tolerance"]:
        status = "WARN_ROUNDING"
        message = (
            "차이가 허용오차 이내입니다. "
            "공시 간 반올림 또는 정정 여부를 확인하세요."
        )
    else:
        status = "FAIL_DIFFERENCE"
        message = "연간 금액과 비교 금액의 차이가 허용오차를 초과합니다."

    if status == "PASS_EXACT" and result["account_id_status"] == "CHANGED":
        status = "WARN_ACCOUNT_ID_CHANGED"
        message = (
            "금액은 일치하지만 기간 중 account_id가 변경되었습니다."
        )

    return _set_status(result, status, message)


def _validate_flow_account(
    company,
    year,
    standard_account,
    annual_rows,
    quarter_rows,
    rounding_tolerance,
):
    result = _base_result(
        company=company,
        year=year,
        standard_account=standard_account,
        validation_rule="FLOW_ANNUAL_EQUALS_FOUR_QUARTERS",
        comparison_basis="sum_q1_q4",
        rounding_tolerance=rounding_tolerance,
        annual_rows=annual_rows,
        quarter_rows=quarter_rows,
    )

    if annual_rows.empty:
        return _set_status(
            result,
            "NOT_TESTABLE_ANNUAL_MISSING",
            "연간 Core 계정이 없습니다.",
        )

    if len(annual_rows) > 1:
        return _set_status(
            result,
            "CORE_DUPLICATE",
            "같은 연도에 연간 Core 계정이 여러 개입니다.",
        )

    quarter_counts = (
        quarter_rows["quarter"].value_counts()
        if "quarter" in quarter_rows.columns
        else pd.Series(dtype="int64")
    )
    missing_quarters = [
        quarter
        for quarter in EXPECTED_QUARTERS
        if quarter not in quarter_counts.index
    ]

    if missing_quarters:
        return _set_status(
            result,
            "NOT_TESTABLE_MISSING_QUARTER",
            "비교에 필요한 분기가 없습니다: "
            + ", ".join(missing_quarters),
        )

    if any(
        quarter_counts.get(quarter, 0) != 1
        for quarter in EXPECTED_QUARTERS
    ):
        return _set_status(
            result,
            "CORE_DUPLICATE",
            "같은 분기의 Core 계정이 여러 개입니다.",
        )

    comparison_rows = quarter_rows[
        quarter_rows["quarter"].isin(EXPECTED_QUARTERS)
    ]
    common_error = _validate_common_conditions(
        result,
        annual_rows,
        comparison_rows,
    )
    if common_error is not None:
        return common_error

    annual_amount = _numeric_value(
        annual_rows,
        "thstrm_amount",
    )
    quarterly_amounts = pd.to_numeric(
        comparison_rows["quarter_amount"],
        errors="coerce",
    )
    comparison_amount = (
        float(quarterly_amounts.sum())
        if quarterly_amounts.notna().all()
        else np.nan
    )

    return _complete_numeric_result(
        result,
        annual_amount,
        comparison_amount,
    )


def _validate_stock_account(
    company,
    year,
    standard_account,
    annual_rows,
    quarter_rows,
    rounding_tolerance,
):
    q4_rows = (
        quarter_rows[quarter_rows["quarter"].eq("Q4")]
        if "quarter" in quarter_rows.columns
        else pd.DataFrame()
    )
    result = _base_result(
        company=company,
        year=year,
        standard_account=standard_account,
        validation_rule="STOCK_ANNUAL_EQUALS_Q4",
        comparison_basis="q4_point_in_time",
        rounding_tolerance=rounding_tolerance,
        annual_rows=annual_rows,
        quarter_rows=q4_rows,
    )

    if annual_rows.empty:
        return _set_status(
            result,
            "NOT_TESTABLE_ANNUAL_MISSING",
            "연간 Core 계정이 없습니다.",
        )

    if len(annual_rows) > 1:
        return _set_status(
            result,
            "CORE_DUPLICATE",
            "같은 연도에 연간 Core 계정이 여러 개입니다.",
        )

    if q4_rows.empty:
        return _set_status(
            result,
            "NOT_TESTABLE_Q4_MISSING",
            "Q4 Core 계정이 없습니다.",
        )

    if len(q4_rows) > 1:
        return _set_status(
            result,
            "CORE_DUPLICATE",
            "Q4 Core 계정이 여러 개입니다.",
        )

    common_error = _validate_common_conditions(
        result,
        annual_rows,
        q4_rows,
    )
    if common_error is not None:
        return common_error

    annual_amount = _numeric_value(
        annual_rows,
        "thstrm_amount",
    )
    q4_amount = _numeric_value(
        q4_rows,
        "quarter_amount",
    )

    return _complete_numeric_result(
        result,
        annual_amount,
        q4_amount,
    )


def build_financial_validation_report(
    annual_df,
    quarterly_df,
    flow_accounts=FLOW_ACCOUNTS,
    stock_accounts=STOCK_ACCOUNTS,
    rounding_tolerance=1000,
):
    """
    Annual/Quarterly Master Data의 회계적 일치 여부를 검증한다.

    Flow 계정은 FY와 Q1~Q4 합계를 비교하고,
    Stock 계정은 FY와 Q4 시점잔액을 비교한다.
    """

    if rounding_tolerance < 0:
        raise ValueError(
            "rounding_tolerance는 0 이상이어야 합니다."
        )

    _require_columns(
        annual_df,
        ["company", "year", "period", "sj_div", "thstrm_amount"],
        "Annual Master",
    )
    _require_columns(
        quarterly_df,
        [
            "company",
            "year",
            "quarter",
            "period",
            "sj_div",
            "quarter_amount",
            "calculation_status",
        ],
        "Quarterly Master",
    )

    annual_core = extract_standard_accounts(annual_df)
    quarterly_core = extract_standard_accounts(quarterly_df)

    if annual_core.empty:
        annual_core = annual_df.head(0).copy()
        annual_core["standard_account"] = pd.Series(
            dtype="string"
        )
        annual_core["standard_account_match"] = pd.Series(
            dtype="string"
        )

    if quarterly_core.empty:
        quarterly_core = quarterly_df.head(0).copy()
        quarterly_core["standard_account"] = pd.Series(
            dtype="string"
        )
        quarterly_core["standard_account_match"] = pd.Series(
            dtype="string"
        )

    company_values = sorted(
        set(_text_values(annual_df, "company"))
        | set(_text_values(quarterly_df, "company"))
    )
    company = ", ".join(company_values)

    years = sorted(
        pd.to_numeric(
            annual_df["year"],
            errors="coerce",
        )
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )

    records = []

    for year in years:
        annual_year = annual_core[
            pd.to_numeric(
                annual_core["year"],
                errors="coerce",
            ).eq(year)
        ]
        quarter_year = quarterly_core[
            pd.to_numeric(
                quarterly_core["year"],
                errors="coerce",
            ).eq(year)
        ]

        for standard_account in flow_accounts:
            records.append(
                _validate_flow_account(
                    company=company,
                    year=year,
                    standard_account=standard_account,
                    annual_rows=annual_year[
                        annual_year["standard_account"].eq(
                            standard_account
                        )
                    ],
                    quarter_rows=quarter_year[
                        quarter_year["standard_account"].eq(
                            standard_account
                        )
                    ],
                    rounding_tolerance=rounding_tolerance,
                )
            )

        for standard_account in stock_accounts:
            records.append(
                _validate_stock_account(
                    company=company,
                    year=year,
                    standard_account=standard_account,
                    annual_rows=annual_year[
                        annual_year["standard_account"].eq(
                            standard_account
                        )
                    ],
                    quarter_rows=quarter_year[
                        quarter_year["standard_account"].eq(
                            standard_account
                        )
                    ],
                    rounding_tolerance=rounding_tolerance,
                )
            )

    return pd.DataFrame(records)


def validation_summary(report_df):
    """검증 상태별 건수와 hard failure 수를 반환한다."""

    if report_df.empty:
        return {
            "total": 0,
            "hard_failures": 0,
            "status_counts": {},
        }

    return {
        "total": int(len(report_df)),
        "hard_failures": int(
            report_df["hard_failure"].fillna(False).sum()
        ),
        "status_counts": {
            str(status): int(count)
            for status, count in report_df[
                "validation_status"
            ].value_counts().items()
        },
    }

