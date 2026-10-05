"""HTTPS-only client for the read-only Oracle data service."""
from urllib.parse import urlsplit
import pandas as pd
import requests
from kiwoom_client import ApiError


class RemoteClient:
    def __init__(self, url, token):
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ApiError('DATA_API_URL에 올바른 HTTPS 주소를 설정하세요.')
        if len(token or '') < 32:
            raise ApiError('DATA_API_TOKEN 설정을 확인하세요.')
        self.url, self.token = url.rstrip('/'), token

    def _get(self, path, params=None):
        try:
            r = requests.get(self.url + path, params=params,
                             headers={'Authorization': 'Bearer ' + self.token},
                             timeout=(10, 240), allow_redirects=False)
            if r.status_code in (401, 403):
                raise ApiError('조회 서버 인증에 실패했습니다. DATA_API_TOKEN을 확인하세요.')
            if r.status_code == 429:
                raise ApiError('다른 조회가 진행 중입니다. 잠시 후 다시 조회하세요.')
            if r.status_code == 422:
                raise ApiError('조회 조건을 확인하세요. 최대 조회기간은 10년입니다.')
            if r.status_code != 200:
                raise ApiError('조회 서버 오류입니다. Oracle 서버의 서비스 상태를 확인하세요.')
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            raise ApiError('조회 서버에 연결하지 못했습니다. HTTPS 주소와 서버 상태를 확인하세요.') from exc

    def stocks(self):
        data = self._get('/v1/stocks')
        if not isinstance(data, dict) or not isinstance(data.get('stocks'), dict):
            raise ApiError('조회 서버의 종목 목록 형식이 올바르지 않습니다.')
        return data['stocks']

    def chart(self, code, start, end, adjusted=True, market='통합'):
        data = self._get('/v1/chart', dict(code=code, start=start, end=end, adjusted=adjusted, market=market))
        try:
            df = pd.DataFrame(data['rows'])
            required = {'date', 'open', 'high', 'low', 'close', 'volume', 'personal', 'foreign', 'institution',
                        'trading_value', 'personal_pct', 'foreign_pct', 'institution_pct'}
            if df.empty or not required.issubset(df.columns):
                raise ValueError('schema')
            df['date'] = pd.to_datetime(df['date'], errors='raise')
            for col in required - {'date'}:
                df[col] = pd.to_numeric(df[col], errors='raise')
            return df
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError('조회 서버의 차트 형식이 올바르지 않습니다.') from exc
