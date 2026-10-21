"""Synthetic offline tests for D-10..D0 inductive event study."""
import unittest

import pandas as pd

from research.event_study import (
    FEATURE_COLS,
    descriptive_profile,
    extract_window,
    prepare_history,
)


def synthetic(count=255, event_index=250):
    dates = pd.bdate_range("2025-01-02", periods=count)
    df = pd.DataFrame({
        "date": dates, "open": [100.0] * count, "high": [104.0] * count,
        "low": [98.0] * count, "close": [100.0] * count,
        "volume": [1_000_000] * count, "trading_value": [1_000_000_000.0] * count,
        "foreign": [200_000_000.0] * count,
        "institution": [-100_000_000.0] * count,
    })
    df.loc[event_index, ["open", "high", "low", "close", "trading_value"]] = [
        100.0, 120.0, 100.0, 111.0, 60_000_000_000.0
    ]
    return df


class EventStudyTests(unittest.TestCase):
    def test_reconfirm_d0_original_four_conditions(self):
        df = synthetic()
        history = prepare_history(df)
        self.assertTrue(bool(history.loc[250, "is_500eok_kiwoom"]))
        self.assertFalse(bool(history.loc[249, "is_500eok_kiwoom"]))
        window = extract_window(history, df.loc[250, "date"])
        self.assertEqual(window["relative_day"].tolist(), list(range(-10, 1)))
        self.assertEqual(window.iloc[-1]["date"], df.loc[250, "date"])
        self.assertEqual(len(window), 11)

    def test_no_d0_leakage_into_prior_features(self):
        df = synthetic()
        before = prepare_history(df)
        df.loc[250, ["close", "high", "volume", "trading_value", "foreign"]] = [
            300, 350, 2_000_000, 100_000_000_000, -500_000_000
        ]
        after = prepare_history(df)
        for field in FEATURE_COLS:
            self.assertEqual(before.loc[249, field], after.loc[249, field])

    def test_missing_turnover_is_unknown_not_false(self):
        df = synthetic()
        df.loc[250, "trading_value"] = float("nan")
        history = prepare_history(df)
        self.assertTrue(pd.isna(history.loc[250, "is_500eok_kiwoom"]))

    def test_early_event_rejected(self):
        df = synthetic()
        with self.assertRaisesRegex(ValueError, "fewer than 10"):
            extract_window(prepare_history(df), df.loc[5, "date"])

    def test_pre_event_profile_excludes_d0(self):
        df = synthetic()
        history = prepare_history(df)
        window = extract_window(history, df.loc[250, "date"])
        result = descriptive_profile(window)
        self.assertEqual(result["relative_day"].max(), -1)
        self.assertEqual(result["relative_day"].min(), -10)
        self.assertEqual(len(result), 10 * len(FEATURE_COLS))

    def test_duplicate_trading_date_rejected(self):
        df = synthetic()
        df.loc[4, "date"] = df.loc[3, "date"]
        with self.assertRaisesRegex(ValueError, "duplicate trading date"):
            prepare_history(df)


if __name__ == "__main__":
    unittest.main()
