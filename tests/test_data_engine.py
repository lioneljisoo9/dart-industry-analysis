import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from config import settings
from src import financials, storage
from src.normalize import extract_standard_accounts
from src.quarterly import _quarterize_frame
from src.storage import _quarter_period_changed


def _account_frame(
    *,
    statement,
    account_id,
    account_name,
    amount,
    cumulative=None,
    fs_div="CFS",
    account_detail="-",
):
    return pd.DataFrame(
        [
            {
                "sj_div": statement,
                "account_id": account_id,
                "account_nm": account_name,
                "account_detail": account_detail,
                "currency": "KRW",
                "thstrm_amount": amount,
                "thstrm_add_amount": cumulative,
                "fs_div_source": fs_div,
            }
        ]
    )


class CoreAccountMappingTests(unittest.TestCase):
    def test_account_id_wins_and_name_fallback_is_per_period(self):
        source = pd.DataFrame(
            [
                {
                    "company": "테스트",
                    "year": 2025,
                    "period": "2025 FY",
                    "sj_div": "IS",
                    "account_id": "ifrs-full_Revenue",
                    "account_nm": "매출액",
                    "thstrm_amount": 100,
                },
                {
                    "company": "테스트",
                    "year": 2025,
                    "period": "2025 FY",
                    "sj_div": "IS",
                    "account_id": "custom_Revenue",
                    "account_nm": "매출액",
                    "thstrm_amount": 999,
                },
                {
                    "company": "테스트",
                    "year": 2024,
                    "period": "2024 FY",
                    "sj_div": "IS",
                    "account_id": "custom_Revenue",
                    "account_nm": "매출액",
                    "thstrm_amount": 80,
                },
            ]
        )

        core = extract_standard_accounts(source)
        revenue = core[
            core["standard_account"].eq("revenue")
        ].sort_values("year")

        self.assertEqual(len(revenue), 2)

        current = revenue[revenue["year"].eq(2025)].iloc[0]
        previous = revenue[revenue["year"].eq(2024)].iloc[0]

        self.assertEqual(current["thstrm_amount"], 100)
        self.assertEqual(
            current["standard_account_match"],
            "account_id",
        )
        self.assertEqual(
            previous["standard_account_match"],
            "account_nm",
        )

    def test_net_income_is_available_as_a_core_account(self):
        source = pd.DataFrame(
            [
                {
                    "year": 2025,
                    "period": "2025 FY",
                    "sj_div": "IS",
                    "account_id": "ifrs-full_ProfitLoss",
                    "account_nm": "당기순이익(손실)",
                    "thstrm_amount": 50,
                }
            ]
        )

        core = extract_standard_accounts(source)

        self.assertEqual(len(core), 1)
        self.assertEqual(
            core.iloc[0]["standard_account"],
            "net_income",
        )


class QuarterlyCalculationTests(unittest.TestCase):
    def test_balance_sheet_uses_point_in_time_amount(self):
        current = _account_frame(
            statement="BS",
            account_id="ifrs-full_Inventories",
            account_name="재고자산",
            amount=100,
        )

        row = _quarterize_frame(current, "Q2").iloc[0]

        self.assertEqual(row["quarter_amount"], 100)
        self.assertEqual(row["quarter_amount_basis"], "point_in_time")
        self.assertEqual(row["calculation_status"], "OK")

    def test_q2_income_uses_dart_three_month_amount(self):
        current = _account_frame(
            statement="IS",
            account_id="ifrs-full_Revenue",
            account_name="매출액",
            amount=30,
            cumulative=70,
        )

        row = _quarterize_frame(current, "Q2").iloc[0]

        self.assertEqual(row["quarter_amount"], 30)
        self.assertEqual(
            row["quarter_amount_basis"],
            "dart_3month_amount",
        )

    def test_q4_income_matches_account_id_across_label_changes(self):
        previous = _account_frame(
            statement="CIS",
            account_id="ifrs-full_Revenue",
            account_name="매출액",
            amount=70,
            cumulative=70,
            account_detail="이전 상세표기",
        )
        current = _account_frame(
            statement="IS",
            account_id="ifrs-full_Revenue",
            account_name="수익",
            amount=100,
            cumulative=100,
            account_detail="변경 상세표기",
        )

        row = _quarterize_frame(
            current,
            "Q4",
            previous,
        ).iloc[0]

        self.assertEqual(row["quarter_amount"], 30)
        self.assertEqual(row["calculation_status"], "OK")

    def test_q4_income_falls_back_when_previous_account_id_is_missing(self):
        previous = _account_frame(
            statement="CIS",
            account_id="-표준계정코드 미사용-",
            account_name="분기순이익(손실)",
            amount=70,
            cumulative=70,
        )
        current = _account_frame(
            statement="CIS",
            account_id="ifrs-full_ProfitLoss",
            account_name="당기순이익(손실)",
            amount=100,
            cumulative=100,
        )

        row = _quarterize_frame(
            current,
            "Q4",
            previous,
        ).iloc[0]

        self.assertEqual(row["quarter_amount"], 30)
        self.assertEqual(row["calculation_status"], "OK")

    def test_cash_flow_subtracts_previous_cumulative_amount(self):
        previous = _account_frame(
            statement="CF",
            account_id="ifrs-full_CashFlowsFromUsedInOperatingActivities",
            account_name="영업활동현금흐름",
            amount=30,
            cumulative=30,
        )
        current = _account_frame(
            statement="CF",
            account_id="ifrs-full_CashFlowsFromUsedInOperatingActivities",
            account_name="영업활동현금흐름",
            amount=80,
            cumulative=80,
        )

        row = _quarterize_frame(
            current,
            "Q2",
            previous,
        ).iloc[0]

        self.assertEqual(row["quarter_amount"], 50)
        self.assertEqual(
            row["quarter_amount_basis"],
            "h1_ytd_minus_q1_ytd",
        )
        self.assertEqual(row["calculation_status"], "OK")

    def test_fs_div_mismatch_never_creates_a_number(self):
        previous = _account_frame(
            statement="CF",
            account_id="ifrs-full_CashFlowsFromUsedInOperatingActivities",
            account_name="영업활동현금흐름",
            amount=30,
            cumulative=30,
            fs_div="OFS",
        )
        current = _account_frame(
            statement="CF",
            account_id="ifrs-full_CashFlowsFromUsedInOperatingActivities",
            account_name="영업활동현금흐름",
            amount=80,
            cumulative=80,
            fs_div="CFS",
        )

        row = _quarterize_frame(
            current,
            "Q2",
            previous,
        ).iloc[0]

        self.assertTrue(pd.isna(row["quarter_amount"]))
        self.assertEqual(
            row["calculation_status"],
            "FS_DIV_MISMATCH",
        )


class IncrementalStorageTests(unittest.TestCase):
    def test_same_receipt_with_changed_calculation_is_detected(self):
        existing = pd.DataFrame(
            [
                {
                    "period": "2025 Q2",
                    "rcept_no": "A",
                    "account_id": "revenue",
                    "quarter_amount": 10,
                }
            ]
        )
        incoming = existing.copy()
        incoming["quarter_amount"] = 20

        self.assertTrue(
            _quarter_period_changed(
                existing,
                incoming,
                "2025 Q2",
            )
        )

    def test_row_order_and_numeric_dtype_do_not_create_false_change(self):
        existing = pd.DataFrame(
            [
                {
                    "period": "2025 Q2",
                    "account_id": "a",
                    "quarter_amount": 10,
                },
                {
                    "period": "2025 Q2",
                    "account_id": "b",
                    "quarter_amount": 20,
                },
            ]
        )
        incoming = existing.iloc[::-1].copy()
        incoming["quarter_amount"] = incoming[
            "quarter_amount"
        ].astype(float)

        self.assertFalse(
            _quarter_period_changed(
                existing,
                incoming,
                "2025 Q2",
            )
        )

    def test_engine_version_change_requires_rebuild(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            master_directory = Path(temp_directory)

            with patch.object(
                storage,
                "MASTER_DIRECTORY",
                master_directory,
            ):
                paths = storage.get_storage_paths(
                    stock_code="010140"
                )
                paths["annual"].touch()
                paths["quarterly"].touch()

                self.assertTrue(
                    storage.storage_needs_rebuild(
                        stock_code="010140"
                    )
                )

                paths["metadata"].write_text(
                    json.dumps(
                        {
                            "data_engine_version": (
                                storage.DATA_ENGINE_VERSION
                            )
                        }
                    ),
                    encoding="utf-8",
                )

                self.assertFalse(
                    storage.storage_needs_rebuild(
                        stock_code="010140"
                    )
                )


class SettingsTests(unittest.TestCase):
    def test_missing_key_is_checked_only_when_requested(self):
        with patch.object(settings, "DART_API_KEY", ""):
            with self.assertRaises(ValueError):
                settings.get_dart_api_key()


class RawPreservationTests(unittest.TestCase):
    def test_raw_response_is_versioned_without_api_key(self):
        first_response = {
            "status": "000",
            "message": "정상",
            "list": [
                {
                    "rcept_no": "20250318000123",
                    "account_id": "ifrs-full_Revenue",
                    "thstrm_amount": "100",
                }
            ],
        }
        corrected_response = {
            **first_response,
            "list": [
                {
                    "rcept_no": "20250401000456",
                    "account_id": "ifrs-full_Revenue",
                    "thstrm_amount": "101",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_directory:
            with patch.object(
                financials,
                "RAW_FINANCIAL_DIRECTORY",
                Path(temp_directory),
            ):
                first_path = financials._save_raw_financial_response(
                    data=first_response,
                    corp_code="00126478",
                    year=2025,
                    report_code="11011",
                    fs_div="CFS",
                )
                corrected_path = financials._save_raw_financial_response(
                    data=corrected_response,
                    corp_code="00126478",
                    year=2025,
                    report_code="11011",
                    fs_div="CFS",
                )

                self.assertTrue(first_path.exists())
                self.assertTrue(corrected_path.exists())
                self.assertNotEqual(first_path, corrected_path)

                payload = json.loads(
                    first_path.read_text(encoding="utf-8")
                )
                self.assertNotIn("crtfc_key", payload["request"])
                self.assertEqual(
                    payload["response"],
                    first_response,
                )


if __name__ == "__main__":
    unittest.main()

