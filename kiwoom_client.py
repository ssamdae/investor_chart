"""Read-only Kiwoom REST adapter. Amount fields in ka10059 are million KRW."""
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests


class ApiError(RuntimeError):
    pass


def number(value, absolute=False):
    if value is None or str(value).strip() == "":
        return float("nan")
    s = str(value).strip().replace(",", "")
    # Some documented examples have repeated minus signs (e.g. --28837).
    if not re.fullmatch(r"[+-]*\d+(\.\d+)?", s):
        raise ApiError("API 숫자 형식을 확인할 수 없습니다.")
    n = float(s.lstrip("+-")) * (-1 if s.startswith("-") else 1)
    return abs(n) if absolute else n


class KiwoomClient:
    def __init__(self, appkey, secretkey):
        if not appkey or not secretkey:
            raise ApiError(".env에 KIWOOM_APP_KEY와 KIWOOM_SECRET_KEY를 입력하세요.")
        self.appkey, self.secretkey = appkey, secretkey
        self.session = requests.Session()
        self.token = None
        self.expires = datetime.min.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        self.last_request = 0.0

    def _post(self, path, body, headers=None):
        # This application's calls are paced below five per second.
        time.sleep(max(0, 0.3 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        try:
            r = self.session.post("https://api.kiwoom.com" + path,
                                  json=body, headers=headers, timeout=(10, 30))
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            raise ApiError("키움 연결 실패: 네트워크·접속 IP·API 서비스 상태를 확인하세요.") from exc
        if str(data.get("return_code", "0")) != "0":
            # Do not echo raw responses which may contain sensitive data.
            raise ApiError(f"키움 API 오류(코드 {data.get('return_code')}). 키·접속 IP·조회 권한을 확인하세요.")
        return data, r.headers

    def _token(self):
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        if not self.token or now >= self.expires - timedelta(minutes=2):
            data, _ = self._post("/oauth2/token", {
                "grant_type": "client_credentials", "appkey": self.appkey,
                "secretkey": self.secretkey})
            self.token = data.get("token")
            if not self.token:
                raise ApiError("접근토큰 발급에 실패했습니다.")
            self.expires = datetime.strptime(data["expires_dt"], "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Asia/Seoul"))
        return self.token

    def pages(self, api_id, path, body, list_key, start=None):
        rows, next_key, seen = [], "", set()
        for _ in range(100):
            headers = {"Content-Type": "application/json;charset=UTF-8",
                       "authorization": f"Bearer {self._token()}", "api-id": api_id,
                       "cont-yn": "Y" if next_key else "N", "next-key": next_key}
            data, response_headers = self._post(path, body, headers)
            if list_key not in data or not isinstance(data[list_key], list):
                raise ApiError(f"{api_id} 응답 목록이 없습니다. API 사양을 확인하세요.")
            batch = data[list_key]
            rows.extend(batch)
            if start and any(x.get("dt", "99999999") <= start for x in batch):
                return rows
            if response_headers.get("cont-yn", "N") != "Y":
                return rows
            next_key = response_headers.get("next-key", "")
            if not next_key or next_key in seen or not batch:
                raise ApiError("연속조회가 진행되지 않아 중단했습니다. 일부 데이터만 표시하지 않습니다.")
            seen.add(next_key)
        raise ApiError("연속조회 한도를 초과했습니다. 조회기간을 줄여주세요.")

    def stocks(self):
        rows = []
        for market in ("0", "10"):
            rows.extend(self.pages("ka10099", "/api/dostk/stkinfo", {"mrkt_tp": market}, "list"))
        return {x["code"]: x["name"] for x in rows if re.fullmatch(r"\d{6}", x.get("code", ""))}

    def chart(self, code, start, end, adjusted=True):
        if not re.fullmatch(r"\d{6}", code):
            raise ApiError("종목코드는 6자리 숫자로 입력하세요.")
        price = self.pages("ka10081", "/api/dostk/chart", {
            "stk_cd": code, "base_dt": end, "upd_stkpc_tp": "1" if adjusted else "0"},
            "stk_dt_pole_chart_qry", start)
        flow = self.pages("ka10059", "/api/dostk/stkinfo", {
            "stk_cd": code, "dt": end, "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"},
            "stk_invsr_orgn", start)
        return normalize(price, flow, start, end)


def normalize(price, flow, start, end):
    p = pd.DataFrame([{ "date": x["dt"], **{
        name: number(x.get(field), absolute=True) for name, field in {
            "open": "open_pric", "high": "high_pric", "low": "low_pric",
            "close": "cur_prc", "volume": "trde_qty"}.items()}} for x in price])
    if p.empty:
        raise ApiError("조회기간에 일봉 데이터가 없습니다.")
    p = p.drop_duplicates("date").query("@start <= date <= @end").sort_values("date")
    if p.empty:
        raise ApiError("선택한 기간에 일봉 데이터가 없습니다.")
    if p[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ApiError("가격 또는 거래량이 누락되어 차트를 표시할 수 없습니다.")
    f = pd.DataFrame([{"date": x["dt"], **{
        name: number(x.get(field)) * 1_000_000 for name, field in {
            "personal": "ind_invsr", "foreign": "frgnr_invsr", "institution": "orgn",
            "trading_value": "acc_trde_prica"}.items()}} for x in flow],
        columns=["date", "personal", "foreign", "institution", "trading_value"])
    df = p.merge(f.drop_duplicates("date"), on="date", how="left", validate="one_to_one")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for who in ("personal", "foreign", "institution"):
        df[who + "_pct"] = df[who] / df["trading_value"].where(df["trading_value"] > 0) * 100
    return df.reset_index(drop=True)
