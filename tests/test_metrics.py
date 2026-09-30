import unittest

import numpy as np
import pandas as pd

from src.metrics import (
    CALCULATED_METRICS,
    build_annual_metrics,
    metric_dictionary,
)


ACCOUNT_ROWS = {
    "revenue": ("IS", "ifrs-full_Revenue", "매출액"),
    "operating_profit": (
        "IS",
        "dart_OperatingIncomeLoss",
        "영업이익",
    ),
    "net_income": (
        "IS",
        "ifrs-full_ProfitLoss",
        "당기순이익",
    ),
    "inventory": (
        "BS",
        "ifrs-full_Inventories",
        "재고자산",
    ),
    "contract_assets": (
        "BS",
        "ifrs-full_ContractAssets",
        "계약자산",
    ),
    "contract_liabilities": (
        "BS",
        "ifrs-full_ContractLiabilities",
        "계약부채",
    ),
    "operating_cash_flow": (
        "CF",
        "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        "영업활동현금흐름",
    ),
}


def annual_rows(values_by_year, company="테스트조선", corp_code="000001"):
    rows = []
    for year, values in values_by_year.items():
        for standard_account, amount in values.items():
            sj_div, account_id, account_nm = ACCOUNT_ROWS[
                standard_account
            ]
            rows.append(
                {
                    "company": company,
                    "corp_code": corp_code,
                    "year": year,
                    "period": "FY",
                    "fs_div_source": "CFS",
                    "rcept_no": f"{year}0001",
                    "sj_div": sj_div,
                    "account_id": account_id,
                    "account_nm": account_nm,
                    "thstrm_amount": amount,
                    "currency": "KRW",
                }
            )
    return pd.DataFrame(rows)


class AnnualMetricsTests(unittest.TestCase):
    def test_builds_generic_and_shipbuilding_metrics(self):
        data = annual_rows(
            {
                2024: {
                    "revenue": 1000,
                    "operating_profit": 50,
                    "net_income": 25,
                    "inventory": 200,
                    "contract_assets": 40,
                    "contract_liabilities": 100,
                    "operating_cash_flow": 75,
                },
                2025: {
                    "revenue": 1200,
                    "operating_profit": 120,
                    "net_income": 60,
                    "inventory": 240,
                    "contract_assets": 60,
                    "contract_liabilities": 180,
                    "operating_cash_flow": 180,
                },
            }
        )

        result = build_annual_metrics(data)
        current = result.loc[result["year"].eq(2025)].iloc[0]

        self.assertEqual(result.shape[0], 2)
        self.assertEqual(current["metric_status"], "COMPLETE")
        self.assertAlmostEqual(current["revenue_growth_yoy"], 0.2)
        self.assertAlmostEqual(current["operating_margin"], 0.1)
        self.assertAlmostEqual(
            current["operating_cash_flow_margin"],
            0.15,
        )
        self.assertAlmostEqual(current["contract_net_position"], -120)
        self.assertAlmostEqual(
            current["contract_net_position_to_revenue"],
            -0.1,
        )
        self.assertAlmostEqual(current["earnings_cash_gap"], -60)
        self.assertTrue(np.isnan(result.iloc[0]["revenue_growth_yoy"]))

    def test_missing_account_is_explicit_and_zero_denominator_is_nan(self):
        data = annual_rows(
            {
                2025: {
                    "revenue": 0,
                    "operating_profit": 10,
                    "net_income": 5,
                    "contract_assets": 20,
                    "contract_liabilities": 30,
                    "operating_cash_flow": 15,
                }
            }
        )
        result = build_annual_metrics(data)
        row = result.iloc[0]

        self.assertEqual(row["metric_status"], "PARTIAL_MISSING_ACCOUNT")
        self.assertIn("inventory", row["missing_accounts"])
        self.assertTrue(np.isnan(row["operating_margin"]))
        self.assertTrue(np.isnan(row["contract_assets_to_revenue"]))

    def test_duplicate_statement_source_is_not_silently_combined(self):
        data = annual_rows(
            {
                2025: {
                    "revenue": 1000,
                    "operating_profit": 100,
                    "net_income": 50,
                    "inventory": 200,
                    "contract_assets": 20,
                    "contract_liabilities": 30,
                    "operating_cash_flow": 120,
                }
            }
        )
        duplicate = data.iloc[[0]].copy()
        duplicate["fs_div_source"] = "OFS"
        data = pd.concat([data, duplicate], ignore_index=True)

        with self.assertRaisesRegex(ValueError, "중복"):
            build_annual_metrics(data)

    def test_metric_dictionary_is_portfolio_documentation(self):
        dictionary = metric_dictionary()

        self.assertEqual(
            set(dictionary["metric"]),
            set(CALCULATED_METRICS),
        )
        self.assertTrue(dictionary["formula"].notna().all())
        self.assertTrue(dictionary["audit_relevance"].notna().all())


if __name__ == "__main__":
    unittest.main()

