"""Read-only, bearer-authenticated stock data service. Run ONE worker."""
import hmac
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from dotenv import load_dotenv
from kiwoom_client import ApiError, KiwoomClient


def create_app(client=None, token=None):
    load_dotenv(Path(__file__).with_name('.env'))
    token = token if token is not None else os.getenv('DATA_API_TOKEN', '')
    if len(token) < 32:
        raise RuntimeError('DATA_API_TOKEN must contain at least 32 characters.')
    client = client if client is not None else KiwoomClient(os.getenv('KIWOOM_APP_KEY'), os.getenv('KIWOOM_SECRET_KEY'))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()

    def authorize(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization.encode(), ('Bearer ' + token).encode()):
            raise HTTPException(401, 'Unauthorized')

    def run(fn):
        # One shared client serializes token refresh and Kiwoom request pacing.
        if not lock.acquire(blocking=False):
            raise HTTPException(429, 'Busy', headers={'Retry-After': '10'})
        try:
            return fn()
        except ApiError:
            raise HTTPException(502, 'Upstream data unavailable') from None
        finally:
            lock.release()

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/v1/stocks', dependencies=[Depends(authorize)])
    def stocks():
        return {'stocks': run(client.stocks)}

    @app.get('/v1/chart', dependencies=[Depends(authorize)])
    def chart(code: str = Query(pattern=r'^\d{6}$'),
              start: str = Query(pattern=r'^\d{8}$'), end: str = Query(pattern=r'^\d{8}$'),
              adjusted: bool = True, market: Literal['통합', 'KRX', 'NXT'] = '통합'):
        try:
            first, last = (datetime.strptime(x, '%Y%m%d') for x in (start, end))
            if not 0 <= (last - first).days <= 3660:
                raise ValueError('date range')
        except ValueError:
            raise HTTPException(422, 'Invalid date range') from None
        frame = run(lambda: client.chart(code, start, end, adjusted, market=market))
        # pandas emits null for missing investor rows, never a fabricated zero.
        return {'rows': json.loads(frame.to_json(orient='records', date_format='iso'))}

    return app
