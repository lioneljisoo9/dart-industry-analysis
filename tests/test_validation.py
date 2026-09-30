import unittest

import pandas as pd

from src.validation import (
    build_financial_validation_report,
    validation_summary,
)


def _annual_row(
    *,
    account_id,
    account_name,
    statement,
    amount,
    fs_div="CFS",
):
    return {
        "company": "테스트기업",
        "year": 2025,
        "period": "2025 FY",
        "fs_div_source": fs_div,
        "sj_div": statement,
        "account_id": account_id,
        "account_nm": account_name,
        "account_detail": "-",
        "currency": "KRW",
        "thstrm_amount": amount,
    }


def _quarter_rows(
    *,
    account_id,
    account_name,
    statement,
    amounts,
    fs_div="CFS",
):
    rows = []

    for quarter_num, (quarter, amount) in enumerate(
        zip(("Q1", "Q2", "Q3", "Q4"), amounts),
        start=1,
    ):
        rows.append(
            {
                "company": "테스트기업",
                "year": 2025,
                "quarter": quarter,
                "quarter_num": quarter_num,
                "period": f"2025 {quarter}",
                "fs_div_source": fs_div,
                "sj_div": statement,
                "account_id": account_id,
                "account_nm": account_name,
                "account_detail": "-",
                "currency": "KRW",
                "quarter_amount": amount,
                "calculation_status": "OK",
            }
        )

    return rows


class FlowValidationTests(unittest.TestCase):
    def _report(self, annual_amount, quarter_amounts, tolerance=1000):
        annual = pd.DataFrame(
            [
                _annual_row(
                    account_id="ifrs-full_Revenue",
                    account_name="매출액",
                    statement="IS",
                    amount=annual_amount,
                )
            ]
        )
        quarterly = pd.DataFrame(
            _quarter_rows(
                account_id="ifrs-full_Revenue",
                account_name="매출액",
                statement="IS",
                amounts=quarter_amounts,
            )
        )

        return build_financial_validation_report(
            annual,
            quarterly,
            flow_accounts=("revenue",),
            stock_accounts=(),
            rounding_tolerance=tolerance,
        )

    def test_exact_flow_reconciliation(self):
        row = self._report(
            annual_amount=100,
            quarter_amounts=(10, 20, 30, 40),
        ).iloc[0]

        self.assertEqual(row["validation_status"], "PASS_EXACT")
        self.assertEqual(row["difference"], 0)
        self.assertFalse(row["hard_failure"])

    def test_rounding_difference_is_warning(self):
        row = self._report(
            annual_amount=101000,
            quarter_amounts=(25000, 25000, 25000, 25000),
        ).iloc[0]

        self.assertEqual(row["difference"], -1000)
        self.assertEqual(row["validation_status"], "WARN_ROUNDING")
        self.assertFalse(row["hard_failure"])

    def test_difference_above_tolerance_is_failure(self):
        report = self._report(
            annual_amount=101001,
            quarter_amounts=(25000, 25000, 25000, 25000),
        )
        row = report.iloc[0]

        self.assertEqual(row["validation_status"], "FAIL_DIFFERENCE")
        self.assertTrue(row["hard_failure"])
        self.assertEqual(validation_summary(report)["hard_failures"], 1)

    def test_missing_quarter_is_not_testable(self):
        annual = pd.DataFrame(
            [
                _annual_row(
                    account_id="ifrs-full_Revenue",
                    account_name="매출액",
                    statement="IS",
                    amount=60,
                )
            ]
        )
        quarterly = pd.DataFrame(
            _quarter_rows(
                account_id="ifrs-full_Revenue",
                account_name="매출액",
                statement="IS",
                amounts=(10, 20, 30, 40),
            )[:3]
        )

        row = build_financial_validation_report(
            annual,
            quarterly,
            flow_accounts=("revenue",),
            stock_accounts=(),
        ).iloc[0]

        self.assertEqual(
            row["validation_status"],
            "NOT_TESTABLE_MISSING_QUARTER",
        )
        self.assertFalse(row["hard_failure"])

    def test_fs_div_mismatch_is_failure(self):
        annual = pd.DataFrame(
            [
                _annual_row(
                    account_id="ifrs-full_Revenue",
                    account_name="매출액",
                    statement="IS",
                    amount=100,
                    fs_div="CFS",
                )
            ]
        )
        quarterly = pd.DataFrame(
            _quarter_rows(
                account_id="ifrs-full_Revenue",
                account_name="매출액",
                statement="IS",
                amounts=(10, 20, 30, 40),
                fs_div="OFS",
            )
        )

        row = build_financial_validation_report(
            annual,
            quarterly,
            flow_accounts=("revenue",),
            stock_accounts=(),
        ).iloc[0]

        self.assertEqual(row["validation_status"], "FS_DIV_MISMATCH")
        self.assertTrue(row["hard_failure"])

    def test_unmapped_account_returns_not_testable(self):
        annual = pd.DataFrame(
            [
                _annual_row(
                    account_id="custom_Unmapped",
                    account_name="미매핑계정",
                    statement="IS",
                    amount=100,
                )
            ]
        )
        quarterly = pd.DataFrame(
            _quarter_rows(
                account_id="custom_Unmapped",
                account_name="미매핑계정",
                statement="IS",
                amounts=(10, 20, 30, 40),
            )
        )

        row = build_financial_validation_report(
            annual,
            quarterly,
            flow_accounts=("revenue",),
            stock_accounts=(),
        ).iloc[0]

        self.assertEqual(
            row["validation_status"],
            "NOT_TESTABLE_ANNUAL_MISSING",
        )
        self.assertFalse(row["hard_failure"])


class StockValidationTests(unittest.TestCase):
    def test_stock_account_matches_annual_to_q4(self):
        annual = pd.DataFrame(
            [
                _annual_row(
                    account_id="ifrs-full_Inventories",
                    account_name="재고자산",
                    statement="BS",
                    amount=400,
                )
            ]
        )
        quarterly = pd.DataFrame(
            _quarter_rows(
                account_id="ifrs-full_Inventories",
                account_name="재고자산",
                statement="BS",
                amounts=(100, 200, 300, 400),
            )
        )

        row = build_financial_validation_report(
            annual,
            quarterly,
            flow_accounts=(),
            stock_accounts=("inventory",),
        ).iloc[0]

        self.assertEqual(row["comparison_amount"], 400)
        self.assertEqual(row["validation_status"], "PASS_EXACT")


if __name__ == "__main__":
    unittest.main()

