"""Offline backtest contract tests. No credentials or live order flow."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.backtest_support import dated_snapshots, future_outcomes, replay, summarize


def days(n=50):
    dates = pd.bdate_range("2026-01-02", periods=n)
    return pd.DataFrame({
        "date": dates, "open": [100.0] * n, "high": [102.0] * n,
        "low": [99.0] * n, "close": [100.0] * n,
        "volume": [100000] * n, "trading_value": [1_000_000_000] * n,
        "foreign": [0] * n, "institution": [0] * n, "personal": [0] * n,
    })


class ReplayTests(unittest.TestCase):
    def test_d1_open_entry_and_5day_labels(self):
        x = days()
        asof = x.at[30, "date"].strftime("%Y%m%d")
        x.loc[31, ["open", "high", "low", "close"]] = [105, 111, 101, 109]
        x.loc[34, ["open", "high", "low", "close"]] = [100, 120, 90, 115]
        r = future_outcomes(x, asof)
        self.assertEqual([a["horizon"] for a in r], [1, 3, 5])
        self.assertTrue(all(a["matured"] for a in r))
        self.assertEqual(r[0]["entry_open"], 105)
        self.assertAlmostEqual(r[0]["close_return_pct"], (109/105 - 1)*100)
        self.assertTrue(r[0]["hit_5pct"])
        self.assertTrue(r[2]["hit_10pct"])
        self.assertAlmostEqual(r[2]["max_adverse_excursion_pct"], (90/105 - 1)*100)

    def test_unmatured_is_not_negative_label(self):
        x = days()
        asof = x.at[47, "date"].strftime("%Y%m%d")
        r = future_outcomes(x, asof)
        self.assertTrue(r[0]["matured"])
        self.assertFalse(r[2]["matured"])
        self.assertIsNone(r[2]["hit_5pct"])
        self.assertIsNone(r[2]["future_500eok"])

    def test_missing_amount_makes_500eok_label_unknown(self):
        x = days()
        asof = x.at[30, "date"].strftime("%Y%m%d")
        x.loc[31, "trading_value"] = None
        r = future_outcomes(x, asof)
        self.assertIsNone(r[0]["future_500eok"])
        self.assertTrue(r[0]["matured"])

    def test_summary_does_not_count_unmatured_or_failures(self):
        frame = pd.DataFrame([
            {"stock_code": "000001", "status": "OK", "signal_level": "관찰",
             "horizon": 1, "matured": True, "hit_5pct": True, "hit_10pct": False,
             "close_return_pct": 2, "max_adverse_excursion_pct": -1},
            {"stock_code": "000002", "status": "OK", "signal_level": "관찰",
             "horizon": 1, "matured": False, "hit_5pct": None, "hit_10pct": None,
             "close_return_pct": None, "max_adverse_excursion_pct": None},
            {"stock_code": "000003", "status": "REPLAY_ERROR", "signal_level": "데이터확인",
             "horizon": None, "matured": False},
        ])
        s = summarize(frame)
        self.assertEqual(len(s), 1)
        self.assertEqual(int(s.iloc[0]["observations"]), 1)
        self.assertEqual(float(s.iloc[0]["hit5_rate"]), 1.0)

    def test_archive_date_selection_excludes_latest_file(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            for name in ("선취매_지지수급_20261007.xlsx",
                         "선취매_지지수급_20261008.xlsx",
                         "선취매_지지수급_최신.xlsx"):
                (d / name).touch()
            r = dated_snapshots(d)
            self.assertEqual([d for d, _ in r], ["20261007", "20261008"])


if __name__ == "__main__":
    unittest.main()
