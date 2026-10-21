# 500억봉 선행 특징 귀납 연구 — D-10 ~ D0

> 연구 순서는 실제 급등 이벤트 수집 → 발생 전 원자료 관찰 → 비발생 대조군과 비교 → 조건 도출 → 시간 외 검증이다. 선행 신호를 미리 정하거나 임의 점수로 등급화하지 않는다.

## 출처와 주의사항

- 기존 이벤트: news_report PostgreSQL의 signal_event (signal_name LIKE '%500억%')
- 기존 정의: 거래대금 >= 500억원, 고가 >= 직전 종가 x 1.15, 고가 >= 당일 저가 x 1.15, 종가 >= 시가 x 1.09 (news_report/filter/signal_filter.py)
- news_report 거래대금은 종가 x 거래량 추정치이다. 키움 ka10059 실제 거래대금과 다를 수 있으므로 D0 조건을 독립 재검증하고 일치/불일치를 보관한다.
- 실제 일봉과 수급은 연구용 KiwoomClient.chart()의 KRX 자료를 사용한다. KRX/통합/NXT를 혼합하지 않는다.
- DB SELECT만 실행하며 주식 주문, 운영 서비스 변경, DB 수정은 없다.

## 실행: 기존 별도 research worktree

~~~bash
cd /home/ubuntu/apps/pre500_research
git status --short
git fetch origin research/pre500-kiwoom-baseline-20261021
git switch --detach origin/research/pre500-kiwoom-baseline-20261021
source .venv/bin/activate
python -m pip install "psycopg[binary]>=3,<4"
python -m unittest discover -s tests -p 'test_event_study.py' -v
~~~

기존 worktree에 미커밋 변경이 있다면 git switch를 강행하지 않는다.
news_report DB에 접속할 .env의 실제 경로를 사용한다. 파일 내용은 출력하거나 공유하지 않는다.

### A. 실제 D0 발생 목록 먼저 10건 확인: 키움 호출 없음

~~~bash
python -m research.event_study \
  --from-db \
  --db-env /home/ubuntu/apps/news_report/.env \
  --start-date 20220101 --end-date 20261008 \
  --limit 10 --catalog-only \
  --output-dir output/pre500_inductive/pilot
~~~

위 news_report/.env는 예시 경로이다. 서버에 존재하는 실제 DB 설정 파일 경로로 교체한다.
DB_* 환경변수가 이미 설정되어 있다면 --db-env는 생략할 수 있다.

### B. 발생 사례 5건의 D-10~D0 키움 일봉·수급 가져오기

~~~bash
python -m research.event_study \
  --from-db \
  --db-env /home/ubuntu/apps/news_report/.env \
  --start-date 20220101 --end-date 20261008 \
  --limit 5 --market KRX --history-days 450 \
  --output-dir output/pre500_inductive/pilot5
~~~

DB 접근이 불가능하면 종목코드·발생일을 포함한 실제 이벤트 CSV로 대체할 수 있다:

~~~bash
python -m research.event_study \
  --events-csv /path/to/event_catalog.csv \
  --limit 5 --market KRX \
  --output-dir output/pre500_inductive/pilot5
~~~

--price-dir /path/to/csv_directory 옵션은 오프라인 종목코드별 가격 CSV(005930.csv 등)를 사용한다.

## 결과 파일

- event_catalog.csv: 원본 D0 종목·일자·이벤트 기준과 추정 거래대금
- dminus10_to_d0.csv: 이벤트별 거래일 D-10~D0의 원자료와 연속형 관찰 변수
- pre_event_profile.csv: D-10~D-1별 연속형 변수의 관측 수, 평균, 중앙값, 사분위수 (D0 제외)
- event_revalidation.csv: 실제 키움 거래대금과 500억봉 원래 조건 재확인
- failures.csv: 누락된 D0, 히스토리 부족, 기타 데이터 품질 오류

## 해석 제한

- D0은 결과 라벨이다. D-1 이전에 D0 값을 사용하지 않는다.
- 이 파일에는 500억봉 발생 사례만 있다. 비급등 대조군의 동일 기간 자료와 비교하기 전에는 어떤 변수도 검증된 상승 전조라고 주장할 수 없다.
- 가장 최근 5개 이벤트는 코드·데이터 흐름을 확인하는 소규모 시험이다. 대표 표본으로 추론하지 않는다.
- 동일 종목 연속 이벤트·같은 날짜의 종목간 상관·테마 군집 효과는 추가 통제가 필요하다.
- 500억봉은 최초 학습 사례다. 향후 1~5일 +5%/+10% 상승 목표와 별도로 구별해 연구한다.
- 기존 support_pool.py의 임의 5개 조건과 집중관찰 등급은 **귀납 연구의 기준으로 사용하지 않는다**.

## 후속 작업

전체 상장 종목을 대상으로 날짜·시장·사전 유동성·지지점 상태가 유사한 비발생 대조군을 자동으로 뽑아 D-10~D-1 변수를 비교한다. 매칭 시 D0 거래대금/당일 상승폭을 사용하면 미래정보 누수이다. 이후 학습·검증 기간을 분리해 발견된 특징만 별도로 평가한다.
