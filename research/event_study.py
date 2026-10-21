"""Inductive D-10..D0 event study (read-only, no heuristic scoring).

Positive cases come from news_report.signal_event (its original Naver
close*volume proxy). Revalidate each D0 against Kiwoom's reported turnover.
D0 is an outcome, NEVER an input to a pre-event prediction signal.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from research.pre500 import TRADING_VALUE_MIN_KRW


RAW_COLS = ("open", "high", "low", "close", "volume", "trading_value")
FEATURE_COLS = (
    "daily_close_return_pct", "daily_range_pct", "value_to_prev20",
    "volume_to_prev20", "close_vs_ma20_pct", "close_vs_ma60_pct",
    "foreign_net_pct_of_value", "institution_net_pct_of_value",
    "foreign_net_5_krw", "institution_net_5_krw",
)


def parse_date(value: object) -> pd.Timestamp:
    if isinstance(value, (int, float)) and not pd.isna(value):
        text = str(int(value))
    else:
        text = str(value).strip()
    return pd.to_datetime(text, errors="raise").normalize()


def load_cases_csv(path: Path, start: str, end: str, limit: int) -> pd.DataFrame:
    cases = pd.read_csv(path, dtype={"stock_code": str})
    if not {"stock_code", "signal_date"}.issubset(cases.columns):
        raise ValueError("event CSV must have stock_code and signal_date")
    return _clean_cases(cases, start, end, limit)


def load_cases_db(db_env: Path | None, start: str, end: str, limit: int) -> pd.DataFrame:
    try:
        from dotenv import load_dotenv
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install python-dotenv and psycopg[binary] for DB mode") from exc
    if db_env is not None:
        if not db_env.is_file():
            raise FileNotFoundError("DB environment file not found")
        load_dotenv(db_env, override=True)
    # Only SELECT: never modify news_report production data.
    conn_kw = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "dbname": os.getenv("DB_NAME", "stock_research"),
        "user": os.getenv("DB_USER", "stock_user"),
        "password": os.getenv("DB_PASSWORD", ""),
        "connect_timeout": 10,
    }
    query = """
        SELECT se.stock_code, sm.stock_name, se.signal_date,
               se.signal_name, se.condition_version,
               se.trading_value AS source_trading_value_krw,
               se.created_at AS event_record_created_at,
               sm.market
          FROM signal_event se
          LEFT JOIN stock_master sm ON sm.stock_code = se.stock_code
         WHERE se.signal_name LIKE %s
           AND se.signal_date BETWEEN %s AND %s
         ORDER BY se.signal_date DESC, se.stock_code
         LIMIT %s
    """
    with psycopg.connect(**conn_kw) as conn:
        with conn.cursor() as cur:
            cur.execute(query, ("%500억%", start, end, limit))
            names = [col.name for col in cur.description]
            rows = cur.fetchall()
    return _clean_cases(pd.DataFrame(rows, columns=names), start, end, limit)


def _clean_cases(cases: pd.DataFrame, start: str, end: str, limit: int) -> pd.DataFrame:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if cases.empty:
        return cases
    df = cases.copy()
    df["stock_code"] = df["stock_code"].astype(str).str.strip().str.zfill(6)
    if not df["stock_code"].str.fullmatch(r"\d{6}").all():
        raise ValueError("stock_code must have six digits")
    df["signal_date"] = df["signal_date"].map(parse_date)
    df = df.loc[df["signal_date"].between(parse_date(start), parse_date(end))].copy()
    df = df.drop_duplicates(["stock_code", "signal_date"])
    df = df.sort_values(["signal_date", "stock_code"], ascending=[False, True])
    return df.head(limit).reset_index(drop=True)


def prepare_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Compute descriptive trailing features; NEVER use future or D0 on earlier rows."""
    missing = set(("date",) + RAW_COLS) - set(frame.columns)
    if missing:
        raise ValueError(f"Kiwoom price input missing: {sorted(missing)}")
    df = frame.copy()
    df["date"] = df["date"].map(parse_date)
    df = df.sort_values("date").reset_index(drop=True)
    if df["date"].duplicated().any():
        raise ValueError("duplicate trading date; do not mix markets")
    for col in RAW_COLS:
        df[col] = pd.to_numeric(df[col], errors="raise")
    if df[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("missing OHLC")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("non-positive OHLC")
    if (df["volume"] < 0).any() or (df["trading_value"].dropna() < 0).any():
        raise ValueError("negative volume/trading value")

    prev_close = df["close"].shift(1)
    known = prev_close.gt(0) & df["trading_value"].notna()
    criteria = (
        df["trading_value"].ge(TRADING_VALUE_MIN_KRW)
        & df["high"].ge(prev_close * 1.15)
        & df["high"].ge(df["low"] * 1.15)
        & df["close"].ge(df["open"] * 1.09)
    )
    df["is_500eok_kiwoom"] = criteria.where(known).astype("boolean")
    df["daily_close_return_pct"] = (df["close"].div(prev_close) - 1) * 100
    df["daily_range_pct"] = (df["high"].div(df["low"]) - 1) * 100
    df["value_to_prev20"] = df["trading_value"].div(
        df["trading_value"].shift(1).rolling(20, min_periods=20).mean().replace(0, float("nan"))
    )
    df["volume_to_prev20"] = df["volume"].div(
        df["volume"].shift(1).rolling(20, min_periods=20).mean().replace(0, float("nan"))
    )
    for period in (5, 20, 60, 120, 224):
        df[f"ma{period}"] = df["close"].rolling(period, min_periods=period).mean()
        df[f"close_vs_ma{period}_pct"] = (df["close"].div(df[f"ma{period}"]) - 1) * 100

    for who in ("personal", "foreign", "institution"):
        if who not in df:
            df[who] = float("nan")
        else:
            df[who] = pd.to_numeric(df[who], errors="raise")
        df[f"{who}_net_pct_of_value"] = (
            df[who].div(df["trading_value"].where(df["trading_value"].gt(0))) * 100
        )
        df[f"{who}_net_5_krw"] = df[who].rolling(5, min_periods=5).sum()
    return df


def extract_window(history: pd.DataFrame, event_date: object) -> pd.DataFrame:
    """Return 11 actual trading sessions indexed D-10..D0, or reject."""
    when = parse_date(event_date)
    match = history.index[history["date"].eq(when)]
    if len(match) != 1:
        raise ValueError("D0 trading date absent in OHLCV")
    index = int(match[0])
    if index < 10:
        raise ValueError("fewer than 10 sessions before D0")
    out = history.iloc[index - 10:index + 1].copy()
    out.insert(0, "relative_day", range(-10, 1))
    return out


def descriptive_profile(windows: pd.DataFrame) -> pd.DataFrame:
    """Descriptive distributions; exclude D0 from predictive-feature analysis."""
    if windows.empty:
        return pd.DataFrame()
    rows = []
    prior = windows.loc[windows["relative_day"] < 0]
    for lag, chunk in prior.groupby("relative_day", sort=True):
        for feature in FEATURE_COLS:
            values = pd.to_numeric(chunk[feature], errors="coerce").dropna()
            rows.append({
                "relative_day": lag, "feature": feature,
                "n_events": len(chunk), "n_valid": len(values),
                "mean": values.mean() if len(values) else float("nan"),
                "median": values.median() if len(values) else float("nan"),
                "p25": values.quantile(.25) if len(values) else float("nan"),
                "p75": values.quantile(.75) if len(values) else float("nan"),
            })
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> dict:
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    cases = (load_cases_db(args.db_env, args.start_date, args.end_date, args.limit)
             if args.from_db else
             load_cases_csv(args.events_csv, args.start_date, args.end_date, args.limit))
    if cases.empty:
        raise ValueError("No matching 500eok cases in requested range")
    cases.to_csv(folder / "event_catalog.csv", index=False, encoding="utf-8-sig")
    if args.catalog_only:
        return {"events": len(cases), "output": str(folder / "event_catalog.csv"),
                "note": "Original news_report event labels; NOT yet Kiwoom-confirmed."}

    client = None
    if args.price_dir is None:
        from dotenv import load_dotenv
        from kiwoom_client import KiwoomClient
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        client = KiwoomClient(os.getenv("KIWOOM_APP_KEY"), os.getenv("KIWOOM_SECRET_KEY"))
    windows, checks, failures = [], [], []
    history_cache = {}
    for row in cases.itertuples(index=False):
        code = row.stock_code
        d0 = row.signal_date
        try:
            if code not in history_cache:
                if args.price_dir:
                    input_path = Path(args.price_dir) / f"{code}.csv"
                    prices = pd.read_csv(input_path, dtype={"stock_code": str})
                else:
                    rows_of_code = cases.loc[cases["stock_code"] == code, "signal_date"]
                    start = (rows_of_code.min() - timedelta(days=args.history_days)).strftime("%Y%m%d")
                    end = rows_of_code.max().strftime("%Y%m%d")
                    prices = client.chart(code, start, end, adjusted=True, market=args.market)
                history_cache[code] = prepare_history(prices)
            window = extract_window(history_cache[code], d0)
            window.insert(0, "event_date", d0.strftime("%Y-%m-%d"))
            window.insert(0, "stock_name", getattr(row, "stock_name", "") or "")
            window.insert(0, "stock_code", code)
            window.insert(0, "event_key", code + "_" + d0.strftime("%Y%m%d"))
            window["market_source"] = args.market
            d0check = window.iloc[-1]
            checks.append({
                "event_key": window.iloc[0]["event_key"],
                "stock_code": code, "stock_name": getattr(row, "stock_name", ""),
                "event_date": d0.strftime("%Y-%m-%d"),
                "original_event_name": getattr(row, "signal_name", "user_supplied"),
                "original_proxy_value_krw": getattr(row, "source_trading_value_krw", None),
                "kiwoom_actual_value_krw": d0check["trading_value"],
                "kiwoom_reconfirmed": d0check["is_500eok_kiwoom"],
                "source_record_created_at": getattr(row, "event_record_created_at", None),
                "pre_d0_sessions": 10,
            })
            windows.append(window)
        except Exception as exc:
            failures.append({
                "stock_code": code, "event_date": d0.strftime("%Y-%m-%d"),
                "error_type": type(exc).__name__, "reason": str(exc)[:140],
            })

    if windows:
        panel = pd.concat(windows, ignore_index=True)
        panel.to_csv(folder / "dminus10_to_d0.csv", index=False, encoding="utf-8-sig")
        descriptive_profile(panel).to_csv(
            folder / "pre_event_profile.csv", index=False, encoding="utf-8-sig"
        )
    if checks:
        pd.DataFrame(checks).to_csv(
            folder / "event_revalidation.csv", index=False, encoding="utf-8-sig"
        )
    pd.DataFrame(failures, columns=["stock_code", "event_date", "error_type", "reason"]).to_csv(
        folder / "failures.csv", index=False, encoding="utf-8-sig"
    )
    n_true = sum(item["kiwoom_reconfirmed"] is True or
                 str(item["kiwoom_reconfirmed"]) == "True" for item in checks)
    return {
        "original_cases": len(cases), "windows_collected": len(checks),
        "kiwoom_d0_reconfirmed": n_true, "failures": len(failures),
        "output_dir": str(folder),
        "warning": "Pre-event descriptive profiles are NOT predictive conditions. "
                   "Add time/mkt/liquidity-matched nonevent controls before inference.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="500억봉 실제 발생 사례 D-10~D0 귀납 분석")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-db", action="store_true", help="Read news_report signal_event (SELECT only)")
    source.add_argument("--events-csv", type=Path, help="CSV with stock_code, signal_date")
    parser.add_argument("--db-env", type=Path, help="news_report .env for DB_* settings")
    parser.add_argument("--catalog-only", action="store_true", help="Export D0 dates, no Kiwoom calls")
    parser.add_argument("--price-dir", type=Path, help="Offline code.csv directory; otherwise use Kiwoom")
    parser.add_argument("--market", choices=["KRX", "통합", "NXT"], default="KRX")
    parser.add_argument("--start-date", default="20250101")
    parser.add_argument("--end-date", default="20261020")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--history-days", type=int, default=450,
                        help="Calendar days of backfill; for MA224 coverage")
    parser.add_argument("--output-dir", default="output/pre500_inductive")
    args = parser.parse_args()
    if args.history_days < 30:
        parser.error("--history-days must be >= 30")
    print(json.dumps(run(args), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
