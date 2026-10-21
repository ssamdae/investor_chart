"""Read-only pre-500eok research using investor_chart.KiwoomClient.chart frames.

No live orders, database writes or look-ahead features. All amounts are KRW.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd


REQUIRED = {"date", "open", "high", "low", "close", "volume", "trading_value"}
TRADING_VALUE_MIN_KRW = 50_000_000_000


def build_observations(frame: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
    """Build features known at t and whether a 500eok event occurs at t+1..t+horizon.

    Event conditions match news_report/filter/signal_filter.py (as inspected
    2026-10-21), but use Kiwoom's *actual* trading_value instead of close*volume.
    Missing trading value makes a day's event status unknown, not False.
    """
    if not 1 <= horizon <= 20:
        raise ValueError("horizon must be between 1 and 20 trading days")
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    df = frame.copy()
    if pd.api.types.is_numeric_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"].astype("Int64").astype(str),
                                    format="%Y%m%d", errors="raise")
    else:
        df["date"] = pd.to_datetime(df["date"], errors="raise")
    if df["date"].duplicated().any():
        raise ValueError("Duplicate trading dates: resolve market/date duplicates first")
    df = df.sort_values("date").reset_index(drop=True)
    for col in (REQUIRED - {"date"}) | {"personal", "foreign", "institution"}.intersection(df.columns):
        df[col] = pd.to_numeric(df[col], errors="raise")
    if (df[["open", "high", "low", "close", "volume"]] <= 0).any().any():
        raise ValueError("Non-positive OHLCV value")
    if (df["trading_value"].dropna() < 0).any():
        raise ValueError("Negative trading value")

    prev_close = df["close"].shift(1)
    observable = (prev_close.gt(0) & df["trading_value"].notna()
                  & df["open"].gt(0) & df["low"].gt(0))
    event = (observable & df["trading_value"].ge(TRADING_VALUE_MIN_KRW)
             & df["high"].ge(prev_close * 1.15)
             & df["high"].ge(df["low"] * 1.15)
             & df["close"].ge(df["open"] * 1.09))
    df["is_500eok_event"] = event

    # At time t, comparisons only use data on or before t.
    prior_20 = df["trading_value"].shift(5).rolling(20, min_periods=20).mean()
    recent_5 = df["trading_value"].rolling(5, min_periods=5).mean()
    df["value_ratio_5_vs_prior20"] = recent_5.div(prior_20.where(prior_20.gt(0)))
    recent_low = df["low"].rolling(5, min_periods=5).min()
    previous_low = df["low"].shift(5).rolling(5, min_periods=5).min()
    df["higher_lows_5v5"] = recent_low.gt(previous_low).where(previous_low.notna()).astype("boolean")
    df["close_vs_high5_pct"] = (df["close"].div(df["high"].rolling(5).max()) - 1) * 100

    for who in ("personal", "foreign", "institution"):
        if who not in df:
            df[who + "_net_5_krw"] = float("nan")
        else:
            df[who + "_net_5_krw"] = df[who].rolling(5, min_periods=5).sum()

    # Require every future day's event status to be observable to label negatives.
    future_events = pd.concat([event.shift(-k) for k in range(1, horizon + 1)], axis=1)
    future_known = pd.concat([observable.shift(-k) for k in range(1, horizon + 1)], axis=1)
    has_full_future = future_known.eq(True).all(axis=1)
    df["future_event_in_horizon"] = future_events.eq(True).any(axis=1).where(has_full_future).astype("boolean")

    recent_event = event.shift(1).rolling(20, min_periods=20).max()
    df["eligible"] = (observable & ~event & recent_event.eq(0)
                      & df["value_ratio_5_vs_prior20"].notna()
                      & df["higher_lows_5v5"].notna()
                      & df["future_event_in_horizon"].notna())
    # Exploratory heuristic only; NOT a validated buy signal.
    df["candidate_exploratory"] = (df["eligible"]
                                   & df["value_ratio_5_vs_prior20"].ge(1.5)
                                   & df["higher_lows_5v5"].fillna(False))
    return df


def evaluate(df: pd.DataFrame) -> dict:
    """Report sample-day rates, not independently validated stock-level accuracy."""
    v = df.loc[df["eligible"]].copy()
    baseline_n = len(v)
    baseline_hit = int(v["future_event_in_horizon"].sum())
    flagged = v.loc[v["candidate_exploratory"]]
    flagged_n = len(flagged)
    flagged_hit = int(flagged["future_event_in_horizon"].sum())
    baseline_rate = baseline_hit / baseline_n if baseline_n else None
    flagged_rate = flagged_hit / flagged_n if flagged_n else None
    return {
        "eligible_stock_days": baseline_n,
        "future_event_stock_days": baseline_hit,
        "baseline_rate": baseline_rate,
        "candidate_stock_days": flagged_n,
        "candidate_future_event_stock_days": flagged_hit,
        "candidate_rate": flagged_rate,
        "lift_vs_baseline": (flagged_rate / baseline_rate if baseline_rate and flagged_rate is not None else None),
        "note": "Overlapping stock-days are dependent; no performance claim without chronological out-of-sample test.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="500억봉 선행 특징 연구 (읽기 전용)")
    parser.add_argument("--code", help="Six-digit stock code for Kiwoom mode")
    parser.add_argument("--start", help="YYYYMMDD")
    parser.add_argument("--end", help="YYYYMMDD")
    parser.add_argument("--market", choices=["KRX", "통합", "NXT"], default="KRX")
    parser.add_argument("--input-csv", type=Path, help="Offline CSV instead of Kiwoom")
    parser.add_argument("--output", type=Path, default=Path("output/pre500_observations.csv"))
    parser.add_argument("--horizon", type=int, default=5)
    args = parser.parse_args()
    if args.input_csv:
        frame = pd.read_csv(args.input_csv, dtype={"stock_code": str})
        if "stock_code" in frame and frame["stock_code"].nunique() != 1:
            parser.error("CSV mode expects one stock; analyze stocks separately")
    else:
        if not all([args.code, args.start, args.end]):
            parser.error("Provide --code, --start and --end, or --input-csv")
        from dotenv import load_dotenv
        from kiwoom_client import KiwoomClient
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        client = KiwoomClient(os.getenv("KIWOOM_APP_KEY"), os.getenv("KIWOOM_SECRET_KEY"))
        frame = client.chart(args.code, args.start, args.end, adjusted=True, market=args.market)
    observations = build_observations(frame, horizon=args.horizon)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    observations.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(json.dumps(evaluate(observations), indent=2, ensure_ascii=False))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
