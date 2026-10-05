# 투자주체 수급 차트 v1

내가 선택한 종목의 일봉과 거래량을 보고, 직접 그은 수평선 부근에서 그날 순매수한 주체를 확인하는 Streamlit 앱입니다.

## 구현 내용

- 종목명·코드 선택, 코스피·코스닥 목록 조회, 6자리 코드 직접 입력
- 기간 선택, 수정주가 선택, 조회 시장 선택(통합 기본값 / KRX / NXT)
- 캔들 아래 거래량 표시: 양봉 빨강, 음봉 파랑
- 순매수 날짜의 봉 뒤에 연한 세로 띠 표시: 개인 분홍, 외국인 민트, 기관 보라
- 한 화면 봉 개수 설정(기본 60개), 차트 드래그로 과거·최근 이동
- 처음에는 최근 구간을 설정한 봉 개수로 표시
- 순매수 > 0 또는 거래대금 대비 순매수 비율 임계값 선택
- 같은 날 여러 주체가 순매수하면 하루 폭을 좌우로 분할해 색이 섞이지 않도록 표시
- 종가 위치에 마우스를 올려 세 주체의 순매수·순매도 금액과 비율 확인
- 가격 입력으로 여러 수평선 추가·삭제, 종목별 브라우저 세션 유지
- 선택적인 이동평균선, 확대·축소·이동, 일별 표와 CSV 다운로드
- API 키 없이 사용할 수 있는 명확하게 표시된 가상 데이터 데모

지지대 자동 판별이나 기준봉 조건은 적용하지 않습니다. 일별 수급은 하루 전체의 순매수이며 특정 가격에서 매수된 물량을 의미하지 않습니다.

## 어디서든 접속하는 Streamlit Cloud 배포

화면은 Streamlit Cloud, 키움 조회는 Oracle 서버에서 실행할 수 있습니다.
[서버 API·HTTPS·Cloud 설정 안내](deploy/STREAMLIT_CLOUD.md)를 따라 설정하세요.
기존 Oracle 단독 실행도 그대로 지원합니다.

## Ubuntu 설치

서버에 접속한 뒤 GitHub에서 코드를 받아 실행하세요.

```bash
mkdir -p /home/ubuntu/apps
cd /home/ubuntu/apps
git clone https://github.com/ssamdae/investor_chart.git
cd investor_chart
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

`.env`에 **실전 환경의 키움 REST API 키**를 입력합니다.

```dotenv
KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
```

키움 포털에서 REST API 사용 신청과 앱 등록/키 발급을 진행하고, 접속 IP 등록이 필요한 경우 API를 호출하는 Oracle 서버의 공인 IP를 등록하세요. 현재 포털의 안내를 기준으로 설정하세요. 키는 채팅에 보낼 필요 없이 서버 `.env`에 직접 입력하면 됩니다. `.env`는 Git 제외 파일입니다.

API 키가 아직 없어도 바로 데모 실행이 가능합니다.

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port 49299
```

현재 사용 중인 서버 포트 49299를 예시로 사용합니다. 사용 중이면 빈 포트로 바꾸고 SSH 터널의 원격 포트도 맞춰주세요. 이 프로세스는 터미널을 닫으면 종료됩니다.

## 상시 실행 설정 (최초 1회)

Ubuntu 사용자 `ubuntu`, 설치 경로 `/home/ubuntu/apps/investor_chart`, 포트 `49299` 기준 systemd 서비스 파일을 제공합니다. 다른 경로라면 서비스 파일의 User, Group, WorkingDirectory, ExecStart를 먼저 수정하세요.

기존에 직접 실행한 Streamlit 터미널에서 Ctrl+C로 종료한 다음 서버에서 실행합니다. 다른 앱의 프로세스는 종료하지 마세요.

```bash
cd /home/ubuntu/apps/investor_chart
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
sudo install -m 644 deploy/investor-chart.service /etc/systemd/system/investor-chart.service
sudo systemctl daemon-reload
sudo systemctl enable --now investor-chart
sudo systemctl status investor-chart --no-pager
curl --fail http://127.0.0.1:49299/_stcore/health
```

상태가 `active (running)`이고 상태 확인 응답이 `ok`이면 실행된 것입니다. 시작 직후 응답이 없으면 잠시 뒤 상태 확인을 다시 실행하세요. SSH를 끊어도 앱이 실행되며, 서버가 재부팅되면 자동 시작하고 앱 프로세스가 종료되면 10초 후 재시작합니다. Oracle 서버 자체는 켜져 있어야 합니다. API 키는 기존 `.env`를 앱이 읽으며 서비스 파일에 복사하지 않습니다.

로그와 관리 명령:

```bash
sudo journalctl -u investor-chart -n 50 --no-pager
sudo systemctl restart investor-chart
# 의도적으로 중지 (자동 재시작하지 않음)
sudo systemctl stop investor-chart
# 자동 시작 해제 및 중지
sudo systemctl disable --now investor-chart
```

포트 사용 중 오류가 나면 기존에 수동 실행한 앱이 남아 있는지 확인하세요. 서비스와 수동 실행을 동시에 사용하지 마세요.

## 맥에서 서버 화면 보기

앱 상시 실행과 맥의 접속 터널은 별개입니다. 아래 명령은 서버 앱을 켜는 명령이 아니라 접속 통로를 여는 명령입니다. 맥 터미널에서 키 파일이 있는 폴더에서 실행하고 유지하세요.

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -i main_server.key -L 8504:127.0.0.1:49299 ubuntu@134.185.103.144
```

맥 브라우저에서 http://localhost:8504 를 엽니다. 연결 후 터미널에 아무 출력이 없어도 정상입니다. 맥을 재시작하거나 터널이 끊기면 이 명령만 다시 실행하면 됩니다. 서버에 로그인해 Streamlit을 다시 실행할 필요는 없습니다. 외부 포트 개방은 필요 없습니다.

## 이후 업데이트 받기

서비스 설치 후 서버에서 다음 명령으로 업데이트합니다. `.env`는 Git에서 제외되므로 키 설정은 유지됩니다.

```bash
cd /home/ubuntu/apps/investor_chart
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart investor-chart
sudo systemctl status investor-chart --no-pager
```

서비스 파일 자체가 변경된 경우에는 최초 설정의 `sudo install`과 `sudo systemctl daemon-reload`도 다시 실행한 뒤 재시작하세요.

## 사용 순서

1. 데모 상태로 기능을 먼저 확인합니다. 데모는 실제 GST 주가가 아닙니다.
2. 키 설정 후 사이드바에서 ‘키움 실데이터’를 선택합니다.
3. ‘종목 목록 불러오기’로 전체 종목 목록을 받고 종목을 검색하거나 코드를 직접 입력합니다.
4. 영웅문과 같은 조회 시장 및 기간을 정하고 ‘차트 조회’를 누릅니다.
5. 원하는 가격을 입력하고 ‘수평선 추가’를 누릅니다.
6. 순매수 표시 주체와 기준을 선택하고 차트의 종가 위치에 마우스를 올립니다.

수평선·주체·임계값 변경은 가져온 데이터로 다시 그리며 API를 재조회하지 않습니다. 조회 조건을 바꾸면 ‘차트 조회’를 다시 눌러야 합니다. 그전에는 이전 조회 결과임을 알리는 메시지가 표시됩니다.

차트 도구막대의 선 그리기로 임시 선을 직접 그릴 수도 있으나, 이 선은 설정 변경 시 사라질 수 있습니다. 유지할 수평선은 가격 입력으로 추가하세요. 입력한 수평선도 브라우저 세션을 종료하면 사라집니다.

## 데이터 처리

- `ka10081 /api/dostk/chart`: 일봉 OHLCV
- `ka10059 /api/dostk/stkinfo`: 일별 투자자 수급, `amt_qty_tp=1`(금액), `trde_tp=0`(순매수)
- `ka10099 /api/dostk/stkinfo`: 코스피·코스닥 종목 목록
- 금액 응답 단위는 **백만원**. 코드에서는 1,000,000을 곱해 원으로 저장하고 화면에서는 억원으로 표시합니다.
- 순매수 비율은 `해당 주체 순매수금액 / 같은 수급 응답의 일별 거래대금 × 100`. 거래대금과 수급의 시장 범위를 맞추기 위해 같은 응답의 `acc_trde_prica`를 사용합니다.
- 가격에 포함된 등락 부호는 절댓값으로 처리하고, 순매수 부호는 유지합니다.
- 가격은 보존하면서 일자로 수급을 병합합니다. 미제공 수급은 빈칸이며 신호에서 제외합니다.
- 연속조회 키를 이어받아 시작일까지 수집합니다. 반복 키나 조회 한도 초과 시 부분 데이터를 정상 결과처럼 표시하지 않습니다.
- 가격·거래량·수급을 동일 시장으로 조회합니다. 통합은 `_AL`, KRX는 접미사 없음, NXT는 `_NX`를 사용합니다. 지원되지 않는 종목/시장 조회를 다른 시장으로 자동 대체하지 않습니다.
- 시장 변경 후 ‘차트 조회’를 눌러야 새 데이터가 적용됩니다. 그전에는 이전 결과의 시장명이 유지됩니다. CSV에도 시장이 기록됩니다.
- 이동평균은 조회한 기간 내 데이터로 계산하므로 앞부분에는 해당 기간만큼의 값이 비어 있습니다.
- 장중/장마감 집계 과정에서 당일 수급이 변경되거나 아직 없을 수 있습니다.

개인·외국인·기관 외에도 기타법인 등 주체가 있으므로 세 주체의 합계가 항상 0일 필요는 없습니다.

## 확인 및 다음 검증

Python 실행 및 Streamlit 데모 UI, 순매수 마커, 가격 차트의 수평선, 금액 변환·음수 부호·수급 누락·연속조회 로직을 검증했습니다. 테스트는 다음 명령으로 재실행할 수 있습니다.

```bash
python -m pip install -r requirements-server.txt httpx
python -m unittest discover -s tests -v
```

사용자 서버에서 실데이터 조회 및 GST 2026-08-27 개인 KRX 순매수 +285백만원을 영웅문과 대조했습니다. 통합시장 조회도 같은 날짜의 -87백만원과 일치함을 사용자가 확인했습니다. 최초 실데이터 연결 시 GST(083450)의 최근 완료된 거래일을 HTS와 대조해 개인·외국인·기관 금액 및 거래량을 확인하세요. 동일한 시장·금액 단위·조회일·집계시점을 맞춰 비교해야 합니다.

연결 실패 시 먼저 `.env` 키, 실전/모의 키 구분, 서버 접속 IP, REST API 서비스 등록을 확인하세요. 응답을 임의로 예시 데이터로 바꾸지 않습니다.

## 공식 참고 자료

2026-10-05 확인:

- API 포털: https://openapi.kiwoom.com/m/guide/apiguide
- 키움 공식 REST API 저장소: https://github.com/Kiwoom-Securities/Kiwoom-REST-API
- 구현 시 확인한 공식 명세: https://github.com/Kiwoom-Securities/Kiwoom-REST-API/blob/main/kiwoom/_data/kiwoom_api_spec.json

공식 저장소의 CLI는 Python 3.13+를 요구하지만, 이 앱은 CLI 패키지를 사용하지 않고 requests로 REST를 호출하므로 Python 3.12 환경에서 실행할 수 있습니다.
