"""Integration-contract tests for real 2026-10-08 support workbook headers.

Small synthetic rows mirror the actual connected Drive file's column *names*,
not its market data; these tests do not produce trading conclusions.
"""
from pathlib import Path
import tempfile
import unittest
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

from research.support_pool import read_support_pool, validate_snapshot_date, scan, main


def actual_header_rows():
    return pd.DataFrame([
        {
            "검토등급": "A", "후보구분": "주요지지", "우선검토순위": 2, "우선검토군": "Y",
            "우선검토점수": 93.87, "대표테마": "로봇", "기준일": "2026-10-08",
            "종목코드": "058610", "종목": "테스트A", "시장": "KOSDAQ", "종가": 97300,
            "지지개수": 5, "접촉지지": "MA120|MA224|VLOW_2026-08-07",
            "최인접지지": "VLOW_2026-08-07",
            "최인접지지가격": 98400, "최인접이격도(%)": -1.12,
        },
        {
            "검토등급": "A", "후보구분": "주요지지", "우선검토순위": 1, "우선검토군": "Y",
            "우선검토점수": 93.90, "대표테마": "전력", "기준일": "2026-10-08",
            "종목코드": "010120", "종목": "테스트B", "시장": "KOSPI", "종가": 197200,
            "지지개수": 4, "접촉지지": "MA60|VLOW_2026-06-08",
            "최인접지지": "VLOW_2026-06-08",
            "최인접지지가격": 197600, "최인접이격도(%)": -0.20,
        },
        {
            "검토등급": "C", "후보구분": "주요지지", "우선검토순위": None, "우선검토군": "N",
            "우선검토점수": 10, "대표테마": "기타", "기준일": "2026-10-08",
            "종목코드": "005930", "종목": "제외종목", "시장": "KOSPI", "종가": 100,
            "지지개수": 1, "접촉지지": "MA20", "최인접지지": "MA20",
            "최인접지지가격": 100, "최인접이격도(%)": 0,
        },
    ])


class ActualWorkbookSchemaTests(unittest.TestCase):
    def test_default_sheet_and_40_flag_preserved_with_nearest_support(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "선취매_지지수급_20261008.xlsx"
            with pd.ExcelWriter(path) as writer:
                # Should prefer first existing matching support-priority sheet, not
                # infer positions from arbitrary first sheet or recalculate support.
                actual_header_rows().to_excel(writer, sheet_name="우선검토40", index=False)
                actual_header_rows().to_excel(writer, sheet_name="전체", index=False)
            pool = read_support_pool(path)
            self.assertEqual(pool["stock_code"].tolist(), ["010120", "058610"])
            self.assertEqual(pool["support_type"].tolist(),
                             ["VLOW_2026-06-08", "VLOW_2026-08-07"])
            self.assertEqual(pool["support_price"].tolist(), [197600, 98400])
            self.assertEqual(pool["support_distance_pct"].tolist(), [-.2, -1.12])
            self.assertEqual(pool["stage1_rank"].tolist(), [1, 2])
            self.assertEqual(pool["source_row_date"].tolist(), ["20261008", "20261008"])
            self.assertEqual(pool["support_contacts"].iloc[0], "MA60|VLOW_2026-06-08")
            validate_snapshot_date(pool, "20261008")
            with self.assertRaisesRegex(ValueError, "snapshot date"):
                validate_snapshot_date(pool, "20261009")

    def test_validate_only_cli_reads_real_schema_without_kiwoom(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "선취매_지지수급_20261008.xlsx"
            with pd.ExcelWriter(path) as w:
                actual_header_rows().to_excel(w, sheet_name="우선검토40", index=False)
            output = io.StringIO()
            with patch("sys.argv", ["support_pool", "--pool", str(path),
                                    "--asof", "20261008", "--validate-only"]), redirect_stdout(output):
                main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "VALIDATED_WITHOUT_API")
            self.assertEqual(result["pool_size"], 2)
            self.assertEqual(result["with_support_price"], 2)

    def test_missing_support_fields_fail_instead_of_silent_guess(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "input.csv"
            df = actual_header_rows()
            df.loc[1, ["최인접지지가격", "최인접이격도(%)"]] = [None, None]
            df.to_csv(path, encoding="utf-8-sig", index=False)
            with self.assertRaisesRegex(ValueError, "support"):
                read_support_pool(path)

    def test_no_eligible_1st_stage_no_2nd_stage_execution(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "input.csv"
            df = actual_header_rows()
            df["우선검토군"] = "N"
            df.to_csv(path, encoding="utf-8-sig", index=False)
            with self.assertRaisesRegex(ValueError, "no eligible"):
                read_support_pool(path)


if __name__ == "__main__":
    unittest.main()
