import unittest

import pandas as pd

from src.notion import build_dashboard_blocks


class NotionPayloadTests(unittest.TestCase):
    def test_dashboard_blocks_include_latest_company_kpis(self):
        metrics = pd.DataFrame(
            [
                {
                    "company": "테스트조선",
                    "year": 2024,
                    "operating_margin": 0.05,
                    "operating_cash_flow_margin": 0.10,
                    "contract_assets_to_revenue": 0.20,
                    "contract_liabilities_to_revenue": 0.30,
                    "earnings_cash_gap_to_revenue": -0.05,
                },
                {
                    "company": "테스트조선",
                    "year": 2025,
                    "operating_margin": 0.10,
                    "operating_cash_flow_margin": 0.15,
                    "contract_assets_to_revenue": 0.25,
                    "contract_liabilities_to_revenue": 0.35,
                    "earnings_cash_gap_to_revenue": -0.02,
                },
            ]
        )

        blocks = build_dashboard_blocks(
            metrics,
            generated_at="2026-09-30T00:00:00+00:00",
        )
        text = " ".join(
            rich_text["text"]["content"]
            for block in blocks
            for rich_text in block.get(
                block["type"], {}
            ).get("rich_text", [])
        )

        self.assertIn("테스트조선 (2025)", text)
        self.assertIn("영업이익률 10.0%", text)
        self.assertNotIn("테스트조선 (2024)", text)

    def test_missing_kpi_column_is_rejected(self):
        metrics = pd.DataFrame(
            [{
                "company": "테스트조선",
                "year": 2025,
            }]
        )

        with self.assertRaisesRegex(ValueError, "필요한 KPI"):
            build_dashboard_blocks(metrics)


if __name__ == "__main__":
    unittest.main()

