"""Offline tests: never call Kiwoom API or write to PostgreSQL."""
import unittest
import pandas as pd
from research.pre500 import build_observations, evaluate


def synthetic(days=75):
    dates = pd.bdate_range('2026-01-02', periods=days)
    data = []
    for i, day in enumerate(dates):
        data.append(dict(date=day, open=100.0, high=104.0, low=98.0, close=101.0,
                         volume=100000, trading_value=1_000_000_000,
                         foreign=float(i * 1000), personal=0, institution=0))
    return pd.DataFrame(data)


class Pre500Tests(unittest.TestCase):
    def test_event_criteria_match_existing_filter(self):
        df = synthetic()
        # prior close 101; high >= 116.15; high/low >=1.15, close/open >=1.09
        df.loc[40, ['open', 'high', 'low', 'close', 'trading_value']] = [100, 120, 100, 111, 50_000_000_000]
        o = build_observations(df)
        self.assertTrue(bool(o.loc[40, 'is_500eok_event']))
        self.assertTrue(bool(o.loc[37, 'future_event_in_horizon']))
        self.assertFalse(bool(o.loc[34, 'future_event_in_horizon']))
        self.assertFalse(bool(o.loc[40, 'eligible']))
        self.assertFalse(bool(o.loc[41, 'eligible']))

    def test_no_future_leakage_in_features(self):
        df = synthetic()
        original = build_observations(df)
        df.loc[45, ['high', 'close', 'trading_value']] = [160, 150, 60_000_000_000]
        changed = build_observations(df)
        for field in ('value_ratio_5_vs_prior20', 'higher_lows_5v5',
                      'foreign_net_5_krw', 'close_vs_high5_pct'):
            self.assertEqual(original.loc[39, field], changed.loc[39, field])

    def test_missing_future_amount_is_not_negative_label(self):
        df = synthetic()
        df.loc[50, 'trading_value'] = float('nan')
        o = build_observations(df)
        self.assertTrue(pd.isna(o.loc[49, 'future_event_in_horizon']))
        self.assertFalse(bool(o.loc[49, 'eligible']))
        self.assertTrue(pd.isna(o.loc[74, 'future_event_in_horizon']))

    def test_investor_gaps_preserved(self):
        df = synthetic()
        df.loc[30, 'foreign'] = float('nan')
        o = build_observations(df)
        self.assertTrue(pd.isna(o.loc[32, 'foreign_net_5_krw']))
        self.assertFalse(pd.isna(o.loc[35, 'foreign_net_5_krw']))

    def test_numeric_yyyymmdd_dates(self):
        df = synthetic()
        df["date"] = df["date"].dt.strftime("%Y%m%d").astype(int)
        o = build_observations(df)
        self.assertEqual(o.loc[0, "date"], pd.Timestamp("2026-01-02"))

    def test_summary_handles_no_signals(self):
        r = evaluate(build_observations(synthetic()))
        self.assertGreater(r['eligible_stock_days'], 0)
        self.assertEqual(r['future_event_stock_days'], 0)
        self.assertIsNone(r['lift_vs_baseline'])

    def test_no_duplicate_sessions(self):
        df = synthetic()
        df.loc[20, 'date'] = df.loc[19, 'date']
        with self.assertRaises(ValueError):
            build_observations(df)


if __name__ == '__main__':
    unittest.main()
