from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import re

import streamlit as st
from dotenv import load_dotenv

from chart import INVESTORS, demo_data, figure
from kiwoom_client import ApiError, KiwoomClient

load_dotenv(Path(__file__).with_name(".env"))
st.set_page_config(page_title="투자주체 수급 차트", layout="wide")
st.title("투자주체 수급 차트")
st.caption("수평선으로 가격대를 살펴보고, 같은 날 순매수한 주체를 확인하세요.")
today = datetime.now(ZoneInfo("Asia/Seoul")).date()


def client():
    if "client" not in st.session_state:
        st.session_state.client = KiwoomClient(os.getenv("KIWOOM_APP_KEY"), os.getenv("KIWOOM_SECRET_KEY"))
    return st.session_state.client


with st.sidebar:
    source = st.radio("데이터", ["데모 (가상 데이터)", "키움 실데이터"])
    if source == "키움 실데이터":
        if st.button("종목 목록 불러오기"):
            try:
                with st.spinner("코스피·코스닥 종목 조회 중…"):
                    st.session_state.stocks = client().stocks()
            except ApiError as exc:
                st.error(str(exc))
    stocks = st.session_state.get("stocks", {"083450": "GST", "005930": "삼성전자", "000660": "SK하이닉스"})
    picked = st.selectbox("종목명·코드 검색", list(stocks), format_func=lambda c: f"{stocks[c]} ({c})")
    manual = st.text_input("직접 종목코드 입력 (선택)", placeholder="6자리 숫자")
    code = manual.strip() or picked
    start = st.date_input("시작일", today - timedelta(days=180), max_value=today)
    end = st.date_input("종료일", today, max_value=today)
    adjusted = st.checkbox("수정주가", value=True)
    fetch = st.button("차트 조회", type="primary", width="stretch")
    st.divider()
    actors = st.multiselect("순매수 표시", list(INVESTORS), default=list(INVESTORS))
    mode = st.radio("표시 기준", ["순매수 > 0", "거래대금 대비 비율"])
    percent = mode == "거래대금 대비 비율"
    threshold = st.number_input("순매수 비율 이상 (%)", min_value=0.0, max_value=100.0,
                                value=5.0, step=1.0, disabled=not percent)
    averages = st.multiselect("이동평균선", [5, 20, 60, 120, 224], default=[])
    visible_bars = st.number_input("한 화면에 표시할 봉 개수", min_value=10, max_value=500,
                                   value=60, step=10)

requested = (source, code, start.isoformat(), end.isoformat(), adjusted)
if fetch or ("frame" not in st.session_state and source.startswith("데모")):
    if start > end or not re.fullmatch(r"\d{6}", code):
        st.error("조회기간과 6자리 종목코드를 확인하세요.")
    else:
        try:
            with st.spinner("일봉과 투자자별 수급을 조회하고 있습니다…"):
                df = demo_data(start, end) if source.startswith("데모") else client().chart(
                    code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), adjusted)
                if df.empty:
                    raise ApiError("선택한 기간에 데이터가 없습니다.")
                st.session_state.frame = df
                st.session_state.loaded = requested
        except ApiError as exc:
            st.error(str(exc))

if "frame" not in st.session_state:
    st.info("키움 키를 설정한 뒤 ‘차트 조회’를 누르세요. 데모는 키 없이 볼 수 있습니다.")
    st.stop()
loaded = st.session_state.loaded
df = st.session_state.frame
if requested != loaded:
    st.warning("조회 조건이 바뀌었습니다. 아래는 이전 조회 결과입니다. ‘차트 조회’를 눌러 갱신하세요.")
loaded_source, loaded_code = loaded[:2]
is_demo = loaded_source.startswith("데모")
title = f"{'가상 예시 · ' if is_demo else ''}{stocks.get(loaded_code, loaded_code)} ({loaded_code})"
if is_demo:
    st.info("가상 데이터로 기능을 확인하는 화면입니다. 실제 주가·수급과 관계가 없습니다.")
else:
    st.caption("KRX 일봉 · 수급 금액 기준 · 당일 값은 장중·장마감 집계 과정에서 변경될 수 있습니다.")
missing = int(df[["personal", "foreign", "institution"]].isna().any(axis=1).sum())
if missing:
    st.warning(f"{missing}거래일에 수급 일부 또는 전체가 미제공되어 해당 주체의 신호를 생략했습니다.")
st.caption(f"표시기간 {df.date.min():%Y-%m-%d} ~ {df.date.max():%Y-%m-%d} · {len(df)}거래일 · 개인 ▲ / 외국인 ● / 기관 ◆")

line_key = f"lines_{loaded_code}"
st.session_state.setdefault(line_key, [])
c1, c2, c3 = st.columns([2, 1, 3])
with c1:
    price = st.number_input("수평선 가격 (원)", min_value=1, value=max(1, int(df.close.iloc[-1])), step=100)
with c2:
    st.write("")
    if st.button("수평선 추가") and price not in st.session_state[line_key]:
        st.session_state[line_key].append(price)
with c3:
    remove = st.multiselect("삭제할 수평선", st.session_state[line_key], key=f"remove_{loaded_code}")
    if st.button("선택한 선 삭제"):
        st.session_state[line_key] = [p for p in st.session_state[line_key] if p not in remove]
        st.rerun()

count = min(int(visible_bars), len(df))
max_start = len(df) - count
navigation_key = f"window_{loaded}_{count}"
if max_start > 0:
    st.session_state.setdefault(navigation_key, max_start)
    def latest_window():
        st.session_state[navigation_key] = max_start
    nav, latest = st.columns([6, 1])
    with nav:
        window_start = st.slider("가로 이동 (왼쪽: 과거 / 오른쪽: 최근)",
            min_value=0, max_value=max_start, step=1, key=navigation_key,
            format="%d", help="표시할 봉 개수를 유지하며 시작 위치를 한 거래일씩 이동합니다.")
    with latest:
        st.button("최근으로", on_click=latest_window)
else:
    window_start = 0
st.caption(f"현재 화면: {df.date.iloc[window_start]:%Y-%m-%d} ~ {df.date.iloc[window_start + count - 1]:%Y-%m-%d} · {count}개 봉")
fig = figure(df, title, actors, threshold, percent, st.session_state[line_key], averages,
             visible_bars=count, window_start=window_start)
st.plotly_chart(fig, width="stretch", config={"scrollZoom": True, "displaylogo": False,
    "modeBarButtonsToAdd": ["drawline", "eraseshape"]})
st.caption("가로 이동 슬라이더로 봉 개수를 유지하며 이동할 수 있습니다. 차트 드래그: 이동 · 휠: 확대/축소. 순매수 기호는 봉 아래에 표시됩니다. 마커 또는 종가 위치에 마우스를 올리면 세 주체의 수급을 확인할 수 있습니다. 수평선은 이 브라우저 세션에서 종목별로 유지됩니다.")
with st.expander("일별 수급 표 / CSV 다운로드"):
    table = df.copy()
    table["date"] = table.date.dt.strftime("%Y-%m-%d")
    st.dataframe(table, width="stretch", hide_index=True)
    st.caption("personal·foreign·institution·trading_value: 원, *_pct: %. 미제공 값은 빈칸입니다.")
    st.download_button("CSV 다운로드", table.to_csv(index=False).encode("utf-8-sig"),
                       f"{'demo_' if is_demo else ''}{loaded_code}_investor_chart.csv", "text/csv")
