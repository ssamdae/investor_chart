import unittest
import pandas as pd
from chart import figure
from kiwoom_client import normalize, number, KiwoomClient, ApiError


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.price = [{"dt": "20260903", "open_pric": "-20000", "high_pric": "22000",
                       "low_pric": "19000", "cur_prc": "+21000", "trde_qty": "1000000"},
                      {"dt": "20260904", "open_pric": "21000", "high_pric": "22000",
                       "low_pric": "20000", "cur_prc": "21500", "trde_qty": "900000"}]
        self.flow = [{"dt": "20260903", "ind_invsr": "1584", "frgnr_invsr": "-61779",
                      "orgn": "60195", "acc_trde_prica": "1105968"}]

    def test_amounts_and_missing_day(self):
        d = normalize(self.price, self.flow, "20260901", "20260930")
        self.assertEqual(d.personal.iloc[0], 1_584_000_000)
        self.assertEqual(d.foreign.iloc[0], -61_779_000_000)
        self.assertEqual(d.open.iloc[0], 20000)
        self.assertTrue(pd.isna(d.personal.iloc[1]))
        self.assertAlmostEqual(d.personal_pct.iloc[0], 1584 / 1105968 * 100)
        self.assertEqual(number("--28837"), -28837)

    def test_zero_denominator(self):
        self.flow[0]["acc_trde_prica"] = "0"
        d = normalize(self.price, self.flow, "20260901", "20260930")
        self.assertTrue(pd.isna(d.personal_pct.iloc[0]))

    def test_markers_and_line_scope(self):
        d = normalize(self.price, self.flow, "20260901", "20260930")
        fig = figure(d, "test", ["개인", "외국인", "기관"], lines=[20000])
        self.assertEqual(fig.layout.shapes[0].yref, "y")
        self.assertEqual(len(next(t for t in fig.data if t.name == "개인 순매수").x), 1)
        self.assertEqual(len(next(t for t in fig.data if t.name == "외국인 순매수").x), 0)
        fig = figure(d, "test", ["개인"], threshold=5, percent=True)
        self.assertEqual(len(next(t for t in fig.data if t.name == "개인 순매수").x), 0)

    def test_pagination_headers_and_stop(self):
        class Fake(KiwoomClient):
            def __init__(self): self.calls = []
            def _token(self): return "fake"
            def _post(self, path, body, headers=None):
                self.calls.append(headers)
                return ({"rows": [{"dt": "20260903" if len(self.calls) == 1 else "20260801"}]},
                        {"cont-yn": "Y", "next-key": "next"})
        client = Fake()
        self.assertEqual(len(client.pages("id", "path", {}, "rows", "20260901")), 2)
        self.assertEqual(client.calls[1]["next-key"], "next")
        self.assertEqual(client.calls[1]["cont-yn"], "Y")


if __name__ == "__main__":
    unittest.main()
