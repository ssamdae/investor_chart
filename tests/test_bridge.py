import unittest
from unittest.mock import patch, Mock
import pandas as pd
from fastapi.testclient import TestClient
from data_api import create_app
from remote_client import RemoteClient
from kiwoom_client import ApiError

TOKEN = 'test-token-' * 4

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.stocks.return_value = {'083450': 'GST'}
        self.backend.chart.return_value = pd.DataFrame([dict(date=pd.Timestamp('2026-08-27'),
            open=1, high=2, low=1, close=2, volume=10, personal=-87000000,
            foreign=float('nan'), institution=1, trading_value=100000000,
            personal_pct=-87, foreign_pct=float('nan'), institution_pct=.000001)])
        self.http = TestClient(create_app(self.backend, TOKEN))
        self.headers = {'Authorization': 'Bearer ' + TOKEN}
        self.params = dict(code='083450', start='20260801', end='20260831', market='통합')

    def test_auth_and_read_only(self):
        self.assertEqual(self.http.get('/v1/stocks').status_code, 401)
        self.assertEqual(self.http.get('/v1/stocks', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        self.assertEqual(self.http.post('/v1/chart', headers=self.headers).status_code, 405)
        self.backend.stocks.assert_not_called()
        self.assertEqual(self.http.get('/v1/stocks', headers=self.headers).json()['stocks']['083450'], 'GST')

    def test_validation(self):
        for changes in [dict(start='20260230'), dict(end='20200101'), dict(code='invalid'), dict(market='OTHER'), dict(start='20000101')]:
            self.assertEqual(self.http.get('/v1/chart', params=self.params | changes, headers=self.headers).status_code, 422)
        self.backend.chart.assert_not_called()

    def test_roundtrip(self):
        response = self.http.get('/v1/chart', params=self.params, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        row = response.json()['rows'][0]
        self.assertEqual(row['personal'], -87000000)
        self.assertIsNone(row['foreign'])
        self.backend.chart.assert_called_once_with('083450', '20260801', '20260831', True, market='통합')
        with patch('remote_client.requests.get', return_value=response) as get:
            result = RemoteClient('https://example.com', TOKEN).chart('083450','20260801','20260831')
            self.assertEqual(result.personal.iloc[0], -87000000)
            self.assertTrue(pd.isna(result.foreign.iloc[0]))
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_error_does_not_leak(self):
        self.backend.stocks.side_effect = ApiError('sensitive upstream response')
        response = self.http.get('/v1/stocks', headers=self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('sensitive', response.text)
        with patch('remote_client.requests.get', return_value=response):
            with self.assertRaises(ApiError):
                RemoteClient('https://example.com', TOKEN).stocks()

    def test_reject_plaintext_and_short_token(self):
        with self.assertRaises(ApiError):
            RemoteClient('http://example.com', TOKEN)
        with self.assertRaises(RuntimeError):
            create_app(self.backend, 'short')

if __name__ == '__main__':
    unittest.main()
