# 500억봉 사전 흔적 연구 — 1차 실험

이 폴더는 기존 투자주체 차트의 **운영 코드와 독립**된 읽기 전용 분석입니다. 주식 주문·DB 수정·실행 서비스 변경은 수행하지 않습니다.

## 출처·기준

- 가격/거래대금/개인·외국인·기관: 기존 [`kiwoom_client.py`](../kiwoom_client.py)의 `KiwoomClient.chart()` 호출 (ka10081 + ka10059)
- 거래대금은 ka10059 `acc_trde_prica`(백만원)를 기존 클라이언트가 원화로 변환한 값. 미수신 값은 `NaN`으로 유지
- 시장: `KRX` 기본. 동일 종목/날짜라도 `통합`, `NXT`는 별개 데이터이므로 혼합 비교 금지
- 500억봉 정의: `news_report/filter/signal_filter.py` (2026-10-21 확인) — 거래대금 ≥ 500억원, 고가 ≥ 전일 종가×1.15, 고가 ≥ 저가×1.15, 종가 ≥ 시가×1.09
- 기존 뉴스 리포트 수집기는 종가×거래량으로 거래대금을 추정하지만, **이번 연구에서는 키움의 실제 거래대금**을 기준으로 하므로 과거 이벤트 일치 여부 재검증 필요
- 배당/분할 등 수정주가 이력은 추가 검증 필요. API에서 `adjusted=True` 사용

## 설치 및 실행

기존 `investor_chart` 환경에서 별도 추가 패키지 없이 실행:

```bash
cd /home/ubuntu/apps/investor_chart
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_pre500.py' -v
python -m research.pre500 --code 083450 --start 20250101 --end 20261020 \
    --market KRX --output output/gst_pre500.csv
```

기존 `.env`의 `KIWOOM_APP_KEY`, `KIWOOM_SECRET_KEY`를 재사용합니다. 키는 저장소에 올리지 않습니다. 서버에 직접 접속할 수 없는 환경에서는 다음과 같이 **단일 종목** CSV로 실행할 수 있습니다.

```bash
python -m research.pre500 --input-csv data/my_stock_kiwoom.csv \
    --output output/offline_pre500.csv
```

CSV에는 `date,open,high,low,close,volume,trading_value`가 필수이며 `personal,foreign,institution`은 선택입니다. `date`는 거래일, 금액 단위는 원(KRW)입니다.

## 결과 해석

- `is_500eok_event`: 그날 기존 500억봉 조건 충족 여부
- `value_ratio_5_vs_prior20`: D-4~D 평균 거래대금 / D-24~D-5 평균 거래대금
- `higher_lows_5v5`: 최근 5일 최저가가 이전 5일 최저가보다 높은지
- `*_net_5_krw`: 최근 5일 투자주체 순매수 합계 (누락 있으면 `NaN`)
- `future_event_in_horizon`: 현재일 **이후** 1~5거래일 500억봉 존재 여부 (미래 데이터가 불완전하면 `NaN`)
- `eligible`: 직전 20거래일에 500억봉이 없으며 충분한 과거·미래 데이터가 있는 평가 대상일
- `candidate_exploratory`: 거래대금 비율 1.5배 이상 + 저점 상승이라는 **임시 연구 가설**. 검증된 매수 신호가 아님

출력된 발생률은 종목·날짜 단위 빈도이며 여러 날짜가 하나의 500억봉을 중복 예측할 수 있습니다. **전체 종목(미급등 대조군), 시계열 분리/검증, 종목별 중복 이벤트 처리 및 거래비용을 포함한 백테스트**를 마치기 전에는 예측률이나 수익률로 해석하면 안 됩니다.

## 후속 단계 (미구현)

1. 키움 과거 수급 데이터의 조회 가능 기간 및 결측 비율 검증
2. `news_report` 과거 `signal_event`와 이벤트 정의·시장 범위 일치 여부 비교
3. 다종목/대조군 일괄 수집기, 캐시 및 호출 제한 관리
4. 독립된 데이터베이스 테이블과 실험 리포트, 시계열 구간 외 검증

운영 중인 `investor_chart` 차트·FastAPI 서버와 `prebuy_screener`는 이 연구로 수정되지 않습니다.
