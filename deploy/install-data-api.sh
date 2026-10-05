#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /home/ubuntu/apps/investor_chart
if [[ $(id -un) != ubuntu ]]; then
    echo 'ubuntu 사용자로 실행하세요 (스크립트 전체에 sudo를 붙이지 마세요).' >&2
    exit 1
fi
if [[ ! -x .venv/bin/python || ! -f .env ]]; then
    echo '기존 .venv와 키움 키를 저장한 .env가 필요합니다.' >&2
    exit 1
fi
if ss -H -ltn '( sport = :49300 )' | grep -q .; then
    if ! systemctl is-active --quiet investor-data-api; then
        echo '49300 포트가 사용 중입니다. 기존 서비스를 확인하세요.' >&2
        exit 1
    fi
fi
.venv/bin/python -m pip install -r requirements-server.txt
.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
import secrets
p = Path('.env')
p.chmod(0o600)
values = dotenv_values(p)
if not values.get('KIWOOM_APP_KEY') or not values.get('KIWOOM_SECRET_KEY'):
    raise SystemExit('.env의 키움 키 설정을 확인하세요.')
if not values.get('DATA_API_TOKEN'):
    with p.open('a') as f:
        f.write('\nDATA_API_TOKEN=' + secrets.token_urlsafe(48) + '\n')
elif len(values['DATA_API_TOKEN']) < 32:
    raise SystemExit('기존 DATA_API_TOKEN이 너무 짧습니다. 32자 이상으로 설정하세요.')
print('인증 토큰 준비 완료 (비밀값은 출력하지 않습니다)')
PY
sudo install -m 644 deploy/investor-data-api.service /etc/systemd/system/investor-data-api.service
sudo systemctl daemon-reload
sudo systemctl enable investor-data-api
sudo systemctl restart investor-data-api
for attempt in {1..20}; do
    if curl --silent --fail http://127.0.0.1:49300/healthz >/dev/null; then
        echo '조회 API 준비 완료. 다음 단계는 HTTPS 연결 설정입니다.'
        exit 0
    fi
    sleep 1
done
echo '시작 확인 실패: sudo journalctl -u investor-data-api -n 50 --no-pager 로 확인하세요.' >&2
exit 1
