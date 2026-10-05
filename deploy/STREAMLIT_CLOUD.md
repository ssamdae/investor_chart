# Streamlit Cloud 화면 + Oracle 데이터 조회

브라우저 → Streamlit Cloud(접속 비밀번호) → HTTPS/Bearer 토큰 → Oracle 조회 API → 키움.
키움 키는 Oracle의 기존 `.env`에만 둡니다. 주문·계좌 조회 API는 제공하지 않습니다.

## 빠른 설치

기존 Oracle 설치 경로와 ubuntu 사용자라면 서버에서 다음을 실행하면 API 설치·토큰 생성·서비스 등록·상태 확인을 수행합니다. 기존 .env의 키움 키는 보존합니다.

```bash
cd /home/ubuntu/apps/investor_chart
git pull --ff-only
bash deploy/install-data-api.sh
```

완료 후 아래 **2. HTTPS 연결**로 진행합니다. 다음 1번은 수동 설치 시 참고용입니다.

## 1. Oracle 준비

```bash
cd /home/ubuntu/apps/investor_chart
git pull --ff-only
.venv/bin/python -m pip install -r requirements-server.txt
```

다음 명령은 기존 키를 보존하면서 `.env`에 서버 간 인증 토큰을 추가합니다. 토큰은 출력하지 않습니다. 기존 토큰이 있으면 바꾸지 않습니다.

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
import secrets
p = Path('.env')
values = dotenv_values(p)
if not values.get('DATA_API_TOKEN'):
    with p.open('a') as f:
        f.write('\nDATA_API_TOKEN=' + secrets.token_urlsafe(48) + '\n')
p.chmod(0o600)
print('인증 토큰 준비 완료')
PY
```

포트 확인: `sudo ss -ltnp '( sport = :49300 )'`. 다른 서비스가 점유 중이면 종료하지 말고 서비스 파일과 Caddy 설정의 내부 포트를 함께 변경합니다.

```bash
sudo install -m 644 deploy/investor-data-api.service /etc/systemd/system/investor-data-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now investor-data-api
sudo systemctl status investor-data-api --no-pager
curl --fail http://127.0.0.1:49300/healthz
```

`{"status":"ok"}` 확인. 실패하면 `sudo journalctl -u investor-data-api -n 50 --no-pager`로 확인합니다. healthz는 프로세스 준비만 확인하며 키움 실제 조회 성공을 보증하지 않습니다.

기존 Streamlit 서비스를 중지하면 같은 키를 이용하는 별도 프로세스의 API 호출 중복을 피할 수 있습니다. 새 화면의 실데이터 검증 후 `sudo systemctl disable --now investor-chart`를 실행하세요. 복귀는 `sudo systemctl enable --now investor-chart`입니다.

## 2. HTTPS 연결

도메인 구매 없이 무료 DNS인 sslip.io의 `investor-api.134-185-103-144.sslip.io`를 사용합니다. 해당 이름이 서버 공인 IP로 연결되고, Caddy가 인증서를 발급·갱신합니다. 무료 DNS 서비스와 인증기관의 가용성/발급 제한에 의존합니다. 서버 IP가 바뀌면 주소와 설정도 바꿔야 합니다.

**먼저 기존 웹서버를 확인하세요. 다른 사이트가 실행 중이면 설정을 덮어쓰거나 서비스를 중지하지 않습니다.**

```bash
sudo ss -ltnp '( sport = :80 or sport = :443 )'
command -v caddy || true
```

- 기존 Nginx/Apache 등 사용 중: 해당 웹서버에 새 호스트의 HTTPS 프록시를 추가해야 합니다. 아래 신규 Caddy 설치는 진행하지 않습니다.
- 기존 Caddy 사용 중: 제공된 사이트 파일을 복사하고 기존 Caddyfile에 `import /etc/caddy/investor-api.caddy` 한 줄만 추가합니다. 기존 사이트/전역 설정은 유지합니다.
- 두 포트가 비어 있고 Caddy가 없다면 Ubuntu 패키지로 설치합니다:

```bash
sudo apt-get update
sudo apt-get install -y caddy
sudo install -m 644 deploy/Caddyfile.investor-api /etc/caddy/investor-api.caddy
sudo nano /etc/caddy/Caddyfile
```

`/etc/caddy/Caddyfile`의 **최상위**에 아래 한 줄을 추가합니다(기존 블록 내부가 아님). 기본 환영 페이지 설정은 남겨도 됩니다.

```caddy
import /etc/caddy/investor-api.caddy
```

Oracle Cloud의 해당 인스턴스에 적용되는 보안 목록/NSG에 TCP 80,443 인바운드를 허용합니다. UFW가 활성화되어 있다면 `sudo ufw allow 80/tcp`, `sudo ufw allow 443/tcp`도 적용합니다. 방화벽 전체를 비우거나 SSH 규칙을 변경하지 마세요. 다른 호스트 방화벽 규칙이 있다면 해당 규칙에서도 80,443을 허용해야 합니다. 내부 49300,49299 포트는 외부에 열지 않습니다.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl --fail https://investor-api.134-185-103-144.sslip.io/healthz
curl -s -o /dev/null -w '%{http_code}\n' https://investor-api.134-185-103-144.sslip.io/v1/stocks
```

첫 번째 응답은 `{"status":"ok"}`, 두 번째는 인증이 없어 `401`이어야 합니다. 초기 인증서 발급은 잠시 걸릴 수 있습니다. 실패 시 `sudo journalctl -u caddy -n 50 --no-pager`로 확인합니다. TLS 검증을 끄는 `-k`로 우회하지 마세요.

## 3. Streamlit Cloud 배포

https://share.streamlit.io → Create app → GitHub 저장소 선택:

- Repository: `ssamdae/investor_chart`
- Branch: `main`
- Main file path: `app.py`
- App URL: 원하는 사용 가능한 이름(예: `investor-chart-ssamdae`)
- Python: 3.12

Advanced settings → Secrets에 아래 TOML을 입력합니다.

```toml
DATA_API_URL = "https://investor-api.134-185-103-144.sslip.io"
DATA_API_TOKEN = "Oracle .env에 생성된 DATA_API_TOKEN 값"
CLOUD_APP_PASSWORD = "본인만 아는 12자 이상의 별도 비밀번호"
```

토큰은 서버에서 `nano .env`로 확인해 Cloud Secrets로 직접 복사합니다. 키움 App Key/Secret은 Cloud에 넣지 않습니다. 비밀번호와 토큰은 다르게 설정합니다. 비밀값이 들어간 화면이나 파일을 GitHub/채팅에 올리지 마세요.

Deploy 후 표시되는 `https://선택한이름.streamlit.app` 주소를 PC/태블릿에서 열고 접속 비밀번호를 입력합니다. `키움 실데이터` 선택 → 종목 목록 → GST / 통합 / 2026-08-27 조회로 기존 -87백만원(차트 -0.87억원)과 대조합니다. Cloud 앱은 유휴 상태에서 휴면에 들어갈 수 있으므로 첫 접속 시 재기동 대기가 생길 수 있습니다.

이 앱의 비밀번호는 간단한 개인 이용용 접근 제어입니다. 이용 가능한 경우 Streamlit의 Private 앱/허용 사용자 설정도 적용하세요. Cloud Secrets 변경 후 앱을 재부팅하면 기존 로그인 세션과 클라이언트 설정을 초기화할 수 있습니다.

## 업데이트/장애 확인

```bash
cd /home/ubuntu/apps/investor_chart
git pull --ff-only
.venv/bin/python -m pip install -r requirements-server.txt
sudo systemctl restart investor-data-api
```

Cloud는 연결한 GitHub 브랜치에서 코드를 반영합니다. API 토큰을 변경할 때는 Oracle `.env`와 Cloud Secrets 값을 맞추고 양쪽을 재시작합니다. 원격 오류 시 데모로 자동 대체하지 않습니다. 동시 조회는 한 건씩 처리하며 다른 요청에는 재시도 안내를 표시합니다. 한 번에 최대 10년을 조회할 수 있습니다.

검증: `python -m pip install httpx` 후 `python -m unittest discover -s tests -v`. 모의 API로 인증 차단, 입력 검증, 시장 전달, 음수/수급 누락 보존, 오류 비밀값 비노출을 확인합니다. 실제 Oracle HTTPS 발급, 방화벽, Cloud 배포, 키움 조회는 사용자 환경에서 별도로 확인해야 합니다.
