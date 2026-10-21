"""Support-pool radar tests use local synthetic data only, no Kiwoom network."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.support_pool import read_support_pool, scan, score_stock


def fake_prices():
    dates = pd.bdate_range("2026-04-01", periods=65)
    data = []
    for i, date in enumerate(dates):
        price = 100.0 + max(0, i - 40) * 0.15
        data.append({"date": date, "open": price, "high": price * 1.025,
                     "low": price * 0.98, "close": price * 1.005,
                     "volume": 100000, "trading_value": 1_000_000_000,
                     "personal": -300000, "foreign": 300000,
                     "institution": 300000})
    return pd.DataFrame(data)


class PoolRadarTests(unittest.TestCase):
    def setUp(self):
        self.prices = fake_prices()
        self.asof = self.prices.iloc[-1]["date"].strftime("%Y%m%d")
        self.row = {"stock_code": "005930", "stock_name": "가상종목",
                    "support_type": "MA120", "support_price": 100.0,
                    "support_distance_pct": None}

    def test_load_legacy_screener_csv_and_leading_zeros(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.csv"
            pd.DataFrame([{"종목코드": 5930, "종목": "삼성전자",
                           "최우선지지선": "MA120", "최우선이격도(%)": 1.1}]).to_csv(
                path, index=False, encoding="utf-8-sig")
            pool = read_support_pool(path)
            self.assertEqual(pool.at[0, "stock_code"], "005930")
            self.assertEqual(pool.at[0, "support_type"], "MA120")
            self.assertAlmostEqual(pool.at[0, "support_distance_pct"], 1.1)
            self.assertTrue(pd.isna(pool.at[0, "support_price"]))

    def test_invalid_or_duplicate_codes_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.csv"
            pd.DataFrame({"stock_code": ["005930", "5930"]}).to_csv(path, index=False)
            with self.assertRaises(ValueError):
                read_support_pool(path)

    def test_no_future_leak_in_current_radar(self):
        a = score_stock(self.prices, self.asof, self.row)
        mutated = self.prices.copy()
        nextday = mutated.iloc[-1].copy()
        nextday["date"] = pd.Timestamp(self.asof) + pd.Timedelta(days=1)
        nextday["close"] = 500
        nextday["trading_value"] = 100_000_000_000
        mutated = pd.concat([mutated, pd.DataFrame([nextday])], ignore_index=True)
        b = score_stock(mutated, self.asof, self.row)
        self.assertEqual(a["status"], "OK")
        self.assertEqual(a["score"], b["score"])
        self.assertEqual(a["signal_level"], b["signal_level"])

    def test_numeric_kiwoom_csv_dates(self):
        data = self.prices.copy()
        data["date"] = data["date"].dt.strftime("%Y%m%d").astype(int)
        result = score_stock(data, self.asof, self.row)
        self.assertEqual(result["status"], "OK")

    def test_missing_institution_retains_unknown_netflow(self):
        data = self.prices.copy()
        data.loc[data.index[-2], "institution"] = float("nan")
        r = score_stock(data, self.asof, self.row)
        self.assertEqual(r["status"], "OK")
        self.assertIsNone(r["foreign_institution_net_5_pct"])

    def test_pool_without_support_price_does_not_invent_reclaim(self):
        row = dict(self.row, support_price=None, support_distance_pct=1.2)
        r = score_stock(self.prices, self.asof, row)
        self.assertAlmostEqual(r["support_distance_pct"], 1.2)
        self.assertNotIn("support_reclaim", r["signals"])

    def test_missing_asof_is_not_silently_filled(self):
        r = score_stock(self.prices.iloc[:-1], self.asof, self.row)
        self.assertEqual(r["status"], "MISSING_ASOF_PRICE")
        self.assertIsNone(r["score"])

    def test_scan_keeps_errors_visible(self):
        pool = pd.DataFrame([self.row, dict(self.row, stock_code="000001")])
        def get_frame(code):
            if code == "000001":
                raise RuntimeError("credential_should_never_be_echoed")
            return self.prices
        result = scan(pool, self.asof, get_frame)
        self.assertEqual(len(result), 2)
        self.assertIn("FETCH_OR_PARSE_ERROR", set(result["status"]))
        self.assertNotIn("credential_should_never_be_echoed", str(result.to_dict()))


if __name__ == "__main__":
    unittest.main()
