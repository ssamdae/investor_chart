"""Point-in-time replay of dated stage-1 support pools and stage-2 pressure scores.

Read-only research. For a historical date, stage-1 membership MUST come from its
own archived snapshot rather than today's universe. No automatic stock orders.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd

from research.pre500 import build_observations
from research.support_pool import read_support_pool, score_stock, validate_snapshot_date


HORIZONS = (1, 3, 5)
ARCHIVE_NAME = re.compile(r"^선취매_지지수급_(20\d{6})\.xlsx$")


def normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    raw = x["date"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    parsed = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    x["date"] = parsed if parsed.notna().all() else pd.to_datetime(x["date"], errors="raise")
    if x["date"].duplicated().any():
        raise ValueError("Duplicate sessions in price history")
    return x.sort_values("date").reset_index(drop=True)


def future_outcomes(frame: pd.DataFrame, asof: str) -> list[dict]:
    """Next-session open entry; next 1/3/5 trading-day realized price paths.

    A horizon with fewer than N following *sessions* is explicitly unmatured.
    No partial 5-day result is treated as a 5-day outcome.
    """
    x = normalize_dates(frame)
    target = pd.to_datetime(asof, format="%Y%m%d", errors="raise")
    idx = x.index[x["date"].eq(target)]
    if len(idx) != 1:
        raise ValueError("As-of session missing from price history")
    pos = int(idx[0])
    labels = build_observations(x)["is_500eok_event"]
    outcome_rows = []
    for h in HORIZONS:
        next_sessions = x.iloc[pos + 1:pos + 1 + h]
        row = {"horizon": h, "matured": len(next_sessions) == h}
        if len(next_sessions) != h:
            row.update({k: None for k in
                        ("entry_date", "entry_open", "max_high_return_pct",
                         "close_return_pct", "max_adverse_excursion_pct",
                         "hit_5pct", "hit_10pct", "future_500eok")})
            outcome_rows.append(row)
            continue
        entry = float(next_sessions.iloc[0]["open"])
        if entry <= 0 or next_sessions[["high", "low", "close"]].isna().any().any():
            raise ValueError("Invalid or missing OHLC in future price sessions")
        maximum = (float(next_sessions["high"].max()) / entry - 1) * 100
        minimum = (float(next_sessions["low"].min()) / entry - 1) * 100
        last_close = (float(next_sessions.iloc[-1]["close"]) / entry - 1) * 100
        trade_value_ok = next_sessions["trading_value"].notna().all()
        next_events = labels.iloc[pos + 1:pos + h + 1]
        row.update({
            "entry_date": next_sessions.iloc[0]["date"].strftime("%Y%m%d"),
            "entry_open": entry,
            "max_high_return_pct": maximum,
            "close_return_pct": last_close,
            "max_adverse_excursion_pct": minimum,
            "hit_5pct": maximum >= 5.0,
            "hit_10pct": maximum >= 10.0,
            "future_500eok": bool(next_events.any()) if trade_value_ok else None,
        })
        outcome_rows.append(row)
    return outcome_rows


def dated_snapshots(directory: Path) -> list[tuple[str, Path]]:
    if not directory.is_dir():
        raise ValueError("Snapshots directory does not exist")
    valid = []
    for path in directory.iterdir():
        m = ARCHIVE_NAME.fullmatch(path.name)
        if m:
            valid.append((m.group(1), path))
    if not valid:
        raise ValueError("No dated 선취매_지지수급_YYYYMMDD.xlsx snapshots found")
    return sorted(valid)


def replay(snapshots: list[tuple[str, Path]], get_frame, limit: int | None = None):
    """Return comparable outcomes exclusively for members of each dated pool."""
    rows = []
    for asof, path in snapshots:
        pool = read_support_pool(path)
        validate_snapshot_date(pool, asof)
        for _, item in pool.head(limit).iterrows() if limit else pool.iterrows():
            details = item.to_dict()
            code = details["stock_code"]
            try:
                prices = get_frame(code)
                signal = score_stock(prices, asof, details)
                if signal["status"] != "OK":
                    rows.append({**signal, "horizon": None, "matured": False})
                    continue
                for outcome in future_outcomes(prices, asof):
                    rows.append({**signal, **outcome})
            except Exception as exc:
                # Error category only; API message may contain account details.
                rows.append({"stock_code": code, "stock_name": details["stock_name"],
                             "snapshot_date": asof, "status": "REPLAY_ERROR",
                             "reason": type(exc).__name__, "score": None,
                             "signal_level": "데이터확인", "horizon": None, "matured": False})
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    columns = ["horizon", "signal_level", "observations", "hit5_rate",
               "hit10_rate", "avg_close_return_pct", "avg_max_adverse_pct"]
    if results.empty or "matured" not in results:
        return pd.DataFrame(columns=columns)
    valid = results.loc[results["matured"].eq(True) & results["status"].eq("OK")].copy()
    if valid.empty:
        return pd.DataFrame(columns=columns)
    return (valid.groupby(["horizon", "signal_level"], dropna=False)
            .agg(observations=("stock_code", "size"),
                 hit5_rate=("hit_5pct", "mean"),
                 hit10_rate=("hit_10pct", "mean"),
                 avg_close_return_pct=("close_return_pct", "mean"),
                 avg_max_adverse_pct=("max_adverse_excursion_pct", "mean"))
            .reset_index()[columns])


def main():
    ap = argparse.ArgumentParser(description="과거 지지점 후보 풀 내 전조 신호 비교 (연구용)")
    ap.add_argument("--snapshots-dir", required=True, type=Path)
    ap.add_argument("--price-dir", type=Path, help="Local code.csv cache; default: Kiwoom REST")
    ap.add_argument("--market", choices=["KRX", "통합", "NXT"], default="KRX")
    ap.add_argument("--limit", type=int, help="Max stage-1 rows per snapshot for trial")
    ap.add_argument("--output-dir", type=Path, default=Path("output/pre500_backtest"))
    args = ap.parse_args()
    if args.limit is not None and args.limit <= 0:
        ap.error("--limit must be positive")
    try:
        snapshots = dated_snapshots(args.snapshots_dir)
        if args.price_dir:
            def fetch(code):
                return pd.read_csv(args.price_dir / f"{code}.csv")
        else:
            from dotenv import load_dotenv
            from kiwoom_client import KiwoomClient
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
            client = KiwoomClient(os.getenv("KIWOOM_APP_KEY"), os.getenv("KIWOOM_SECRET_KEY"))
            earliest = (pd.to_datetime(snapshots[0][0], format="%Y%m%d")
                        - pd.Timedelta(days=150)).strftime("%Y%m%d")
            latest = min(pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize(),
                         pd.to_datetime(snapshots[-1][0], format="%Y%m%d")
                         + pd.Timedelta(days=15)).strftime("%Y%m%d")
            def fetch(code):
                return client.chart(code, earliest, latest, adjusted=True, market=args.market)
        cache = {}
        def get_frame(code):
            if code not in cache:
                cache[code] = fetch(code)
            return cache[code]
        results = replay(snapshots, get_frame, args.limit)
        summary = summarize(results)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output_dir / "observations.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(args.output_dir / "summary.csv", index=False, encoding="utf-8-sig")
        print(json.dumps({
            "snapshot_count": len(snapshots),
            "candidate_records": len(results),
            "matured_horizon_records": int(results["matured"].eq(True).sum()) if not results.empty else 0,
            "results": str(args.output_dir),
            "warning": "Historical snapshots must have been created at the specified date; "
                       "scores are exploratory, not verified trading forecasts.",
        }, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
