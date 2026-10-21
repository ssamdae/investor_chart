"""Support-pool early-pressure radar. Research-only; never places orders.

Consumes dated screener snapshots rather than selecting stocks from the entire market.
Uses KiwoomClient.chart from the existing investor_chart application.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd

from research.pre500 import build_observations


def _col(columns, choices):
    return next((c for c in choices if c in columns), None)


def _code(value):
    s = str(value).strip()
    if re.fullmatch(r"\d{1,6}(?:\.0)?", s):
        return s.split(".")[0].zfill(6)
    raise ValueError("Invalid stock code in pool (six numeric digits expected)")


def read_support_pool(path: Path, sheet: str | None = None) -> pd.DataFrame:
    """Accept historical prebuy_screener files and the 우선검토40 sheet.

    For custom support files, override the input columns in the exported CSV:
    stock_code, stock_name, support_price, support_distance_pct, support_type.
    Missing support information stays unknown; it is not inferred from a name.
    """
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        xl = pd.ExcelFile(path)
        if sheet is None:
            sheet = next((x for x in ("우선검토40", "1차필터결과") if x in xl.sheet_names), None)
            if sheet is None:
                # Some support workbooks use customized sheet labels. Detect
                # candidate sheets by the actual columns instead of guessing.
                candidates = []
                for name in xl.sheet_names:
                    columns = set(pd.read_excel(xl, sheet_name=name, nrows=0).columns)
                    if "종목코드" in columns and (
                        {"최인접지지", "최인접지지가격"}.issubset(columns)
                        or "최우선지지선" in columns
                    ):
                        candidates.append(name)
                if not candidates:
                    raise ValueError(f"No compatible support candidate sheet found among {xl.sheet_names}")
                sheet = next((name for name in candidates if "우선" in name or "검토" in name), candidates[0])
        pool = pd.read_excel(xl, sheet_name=sheet, dtype=object)
    elif path.suffix.lower() == ".csv":
        pool = pd.read_csv(path, dtype=object, encoding="utf-8-sig")
    else:
        raise ValueError("Only .xlsx/.xlsm/.csv support snapshots are accepted")
    code_col = _col(pool.columns, ("종목코드", "stock_code", "code"))
    if code_col is None:
        raise ValueError("Missing stock code column: 종목코드 / stock_code")
    name_col = _col(pool.columns, ("종목", "종목명", "stock_name"))
    type_col = _col(pool.columns, ("최인접지지", "최우선지지선", "지지선", "support_type"))
    support_col = _col(pool.columns, ("최인접지지가격", "support_price", "지지점가격", "지지선가격", "지지가격"))
    dist_col = _col(pool.columns, ("최인접이격도(%)", "support_distance_pct", "지지점이격도(%)", "최우선이격도(%)"))
    date_col = _col(pool.columns, ("기준일", "snapshot_date"))

    # The existing screener owns the stage-1 decisions. Do not reconstruct its
    # moving-average/V-low support logic or extend the pool with other stocks.
    if "우선검토군" in pool.columns:
        flag = pool["우선검토군"].fillna("").astype(str).str.upper().str.strip()
        pool = pool.loc[flag.isin(("Y", "YES", "TRUE", "1"))].copy()
    if pool.empty:
        raise ValueError("Stage-1 support pool has no eligible rows")
    pool = pool.reset_index(drop=True)
    out = pd.DataFrame(index=pool.index)
    out["stock_code"] = pool[code_col].map(_code)
    out["stock_name"] = (pool[name_col].fillna("").astype(str) if name_col else "")
    out["support_type"] = pool[type_col].fillna("").astype(str) if type_col else ""
    out["support_price"] = (pd.to_numeric(pool[support_col], errors="coerce")
                            if support_col else pd.Series(float("nan"), index=pool.index))
    out["support_distance_pct"] = (pd.to_numeric(pool[dist_col], errors="coerce")
                                   if dist_col else pd.Series(float("nan"), index=pool.index))
    out["source_row_date"] = (pool[date_col].astype(str).str.strip() if date_col else "")
    # Retain the stage-1 context for interpretable stage-2 ranking.
    for src, dst in (
        ("우선검토순위", "stage1_rank"),
        ("우선검토점수", "stage1_score"),
        ("검토등급", "stage1_grade"),
        ("대표테마", "theme"),
        ("접촉지지", "support_contacts"),
        ("지지개수", "support_count"),
        ("시장", "market"),
    ):
        if src in pool:
            out[dst] = pool[src].values
    if "stage1_rank" in out:
        out["stage1_rank"] = pd.to_numeric(out["stage1_rank"], errors="coerce")
        out = out.sort_values("stage1_rank", na_position="last", kind="stable")
    if (out["support_price"].isna() & out["support_distance_pct"].isna()).any():
        raise ValueError("Stage-1 support price/distance missing: verify the input sheet and columns")
    if out["stock_code"].duplicated().any():
        raise ValueError("Duplicate stock codes in snapshot")
    if out["source_row_date"].ne("").any():
        dates = pd.to_datetime(out["source_row_date"], errors="coerce")
        if dates.isna().any() or dates.dt.normalize().nunique() != 1:
            raise ValueError("Snapshot contains invalid or mixed trade dates")
        out["source_row_date"] = dates.dt.strftime("%Y%m%d")
    if (out["support_price"].dropna() <= 0).any():
        raise ValueError("Invalid non-positive support price")
    return out.reset_index(drop=True)


def validate_snapshot_date(pool: pd.DataFrame, asof: str) -> None:
    """Reject attempts to use a later/earlier stage-1 file at this as-of date."""
    target = pd.to_datetime(asof, format="%Y%m%d", errors="raise")
    if "source_row_date" in pool and pool["source_row_date"].astype(str).ne("").any():
        observed = pd.to_datetime(pool["source_row_date"], format="%Y%m%d", errors="raise")
        if observed.dt.normalize().ne(target).any():
            raise ValueError("Stage-1 snapshot date does not match --asof; using it would bias the analysis")


def score_stock(frame: pd.DataFrame, asof: str, pool_row: dict) -> dict:
    """Evaluate available signals as of YYYYMMDD. No future labels are used."""
    dt = pd.to_datetime(asof, format="%Y%m%d", errors="raise")
    x = frame.copy()
    # CSV readers may infer YYYYMMDD as integer: do not parse it as epoch nanoseconds.
    raw_date = x["date"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    compact = pd.to_datetime(raw_date, format="%Y%m%d", errors="coerce")
    x["date"] = compact if compact.notna().all() else pd.to_datetime(x["date"], errors="raise")
    x = x.loc[x["date"] <= dt]
    base = {"stock_code": pool_row["stock_code"], "stock_name": pool_row["stock_name"],
            "snapshot_date": asof, "support_type": pool_row.get("support_type", ""),
            "support_price": pool_row.get("support_price"),
            "stage1_rank": pool_row.get("stage1_rank"),
            "stage1_score": pool_row.get("stage1_score"),
            "stage1_grade": pool_row.get("stage1_grade"),
            "theme": pool_row.get("theme"),
            "support_count": pool_row.get("support_count"),
            "support_contacts": pool_row.get("support_contacts"),
            "market": pool_row.get("market")}
    if x.empty or x["date"].max() != dt:
        return {**base, "status": "MISSING_ASOF_PRICE", "score": None,
                "signal_level": "데이터확인", "reason": "기준일 일봉 없음"}
    if len(x) < 26:
        return {**base, "status": "SHORT_HISTORY", "score": None,
                "signal_level": "데이터확인", "reason": "최소 26거래일 필요"}

    feat = build_observations(x).iloc[-1]
    if pd.isna(feat["value_ratio_5_vs_prior20"]):
        return {**base, "status": "MISSING_TURNOVER", "score": None,
                "signal_level": "데이터확인", "reason": "키움 거래대금 누락 또는 기준 거래대금 0"}

    close = float(feat["close"])
    support = pool_row.get("support_price")
    if support is not None and pd.notna(support):
        dist = (close / float(support) - 1.0) * 100.0
        # A stored distance may be stale; real support price always wins.
    else:
        dist = pool_row.get("support_distance_pct")
        dist = float(dist) if dist is not None and pd.notna(dist) else None

    recent = x.tail(11).copy()
    up = recent.loc[recent["close"].diff().gt(0), "trading_value"].dropna()
    down = recent.loc[recent["close"].diff().lt(0), "trading_value"].dropna()
    ratio = (float(up.mean() / down.mean()) if len(up) >= 2 and len(down) >= 2
             and down.mean() > 0 and recent["trading_value"].notna().all() else None)

    five_turnover = float(x["trading_value"].tail(5).sum())
    foreign = feat["foreign_net_5_krw"]
    inst = feat["institution_net_5_krw"]
    net_ratio = (float((foreign + inst) / five_turnover * 100)
                 if pd.notna(foreign) and pd.notna(inst) and five_turnover > 0 else None)

    ratio_5 = float(feat["value_ratio_5_vs_prior20"])
    higher = bool(feat["higher_lows_5v5"])
    # Exploratory score, NOT an estimated probability.
    signals = {
        "turnover_expansion": ratio_5 >= 1.5,
        "up_day_turnover_dominance": ratio is not None and ratio >= 1.25,
        "higher_lows": higher,
        "joint_foreign_institution_inflow": net_ratio is not None and net_ratio >= 1.0,
    }
    if support is not None and pd.notna(support):
        lows = x["low"].tail(5)
        signals["support_reclaim"] = (
            bool(lows.le(float(support) * 1.015).any())
            and close >= float(support)
            and bool(lows.ge(float(support) * 0.97).all())
        )
    score = sum(signals.values())
    ret5 = (close / float(x["close"].iloc[-6]) - 1.0) * 100
    if bool(feat["is_500eok_event"]):
        level = "이미500억봉"
    elif ret5 > 25:
        level = "과열제외"
    elif score >= 3:
        level = "집중관찰"
    elif score >= 2:
        level = "관찰"
    else:
        level = "변화미약"

    return {**base, "status": "OK", "score": int(score),
            "signal_level": level, "support_distance_pct": dist,
            "trading_value_5v20_ratio": ratio_5,
            "up_down_turnover_ratio_10d": ratio,
            "higher_lows_5v5": higher,
            "foreign_net_5_krw": float(foreign) if pd.notna(foreign) else None,
            "institution_net_5_krw": float(inst) if pd.notna(inst) else None,
            "foreign_institution_net_5_pct": net_ratio,
            "return_5d_pct": ret5,
            "signals": json.dumps(signals, ensure_ascii=False),
            "reason": ", ".join(k for k, v in signals.items() if v) or "탐색 신호 없음"}


def scan(pool: pd.DataFrame, asof: str, get_frame, limit: int | None = None) -> pd.DataFrame:
    rows = []
    for _, item in pool.head(limit).iterrows() if limit else pool.iterrows():
        row = item.to_dict()
        try:
            frame = get_frame(row["stock_code"])
            result = score_stock(frame, asof, row)
        except Exception as exc:
            # Never include raw upstream/API exceptions, which may expose credentials.
            result = {"stock_code": row["stock_code"], "stock_name": row["stock_name"],
                      "snapshot_date": asof, "support_type": row["support_type"],
                      "status": "FETCH_OR_PARSE_ERROR", "score": None,
                      "signal_level": "데이터확인", "reason": type(exc).__name__}
        rows.append(result)
    output = pd.DataFrame(rows)
    if not output.empty:
        priority = {"집중관찰": 0, "관찰": 1, "변화미약": 2, "과열제외": 3,
                    "이미500억봉": 4, "데이터확인": 5}
        output["_sort"] = output["signal_level"].map(priority).fillna(9)
        output = output.sort_values(["_sort", "score"], ascending=[True, False], na_position="last")
        output = output.drop(columns="_sort")
    return output.reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="지지점 종목 풀 기반 상승 전조 연구 (읽기 전용)")
    ap.add_argument("--pool", type=Path, required=True, help="Dated screener XLSX/CSV snapshot")
    ap.add_argument("--sheet", help="Defaults to 우선검토40, otherwise 1차필터결과")
    ap.add_argument("--asof", required=True, help="Snapshot and completed session date YYYYMMDD")
    ap.add_argument("--market", default="KRX", choices=["KRX", "통합", "NXT"])
    ap.add_argument("--validate-only", action="store_true", help="Validate stage-1 snapshot; do not call Kiwoom")
    ap.add_argument("--price-dir", type=Path, help="Offline code.csv files instead of live Kiwoom")
    ap.add_argument("--start", help="Historical lookup start YYYYMMDD; default asof - 120 calendar days")
    ap.add_argument("--limit", type=int, help="Fetch at most N rows for a small trial")
    ap.add_argument("--output", type=Path, default=Path("output/support_pool_radar.csv"))
    args = ap.parse_args()
    try:
        asof_dt = pd.to_datetime(args.asof, format="%Y%m%d", errors="raise")
        start = args.start or (asof_dt - pd.Timedelta(days=120)).strftime("%Y%m%d")
        if pd.to_datetime(start, format="%Y%m%d") > asof_dt:
            ap.error("--start after --asof")
        if args.limit is not None and args.limit < 1:
            ap.error("--limit must be positive")
        pool = read_support_pool(args.pool, args.sheet)
        validate_snapshot_date(pool, args.asof)
        if args.validate_only:
            cols = [c for c in ("stock_code", "stock_name", "support_type", "support_price",
                                "support_distance_pct", "stage1_rank") if c in pool]
            print(json.dumps({
                "status": "VALIDATED_WITHOUT_API",
                "asof": args.asof,
                "pool_size": len(pool),
                "with_support_price": int(pool["support_price"].notna().sum()),
                "support_types": pool["support_type"].value_counts(dropna=False).to_dict(),
                "sample": pool[cols].head(5).where(pd.notna(pool[cols]), None).to_dict(orient="records"),
            }, indent=2, ensure_ascii=False, default=str))
            return
        if args.price_dir:
            def get_frame(code):
                return pd.read_csv(args.price_dir / f"{code}.csv")
        else:
            from dotenv import load_dotenv
            from kiwoom_client import KiwoomClient
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
            kiwoom = KiwoomClient(os.getenv("KIWOOM_APP_KEY"), os.getenv("KIWOOM_SECRET_KEY"))
            def get_frame(code):
                return kiwoom.chart(code, start, args.asof, adjusted=True, market=args.market)
        result = scan(pool, args.asof, get_frame, args.limit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(json.dumps({"asof": args.asof, "pool": str(args.pool),
                          "total": len(result),
                          "by_level": result["signal_level"].value_counts().to_dict()
                                      if not result.empty else {},
                          "output": str(args.output)}, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
