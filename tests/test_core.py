import unittest
import pandas as pd
from chart import figure, demo_data
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

    def test_bands_and_line_scope(self):
        d = normalize(self.price, self.flow, "20260901", "20260930")
        fig = figure(d, "test", ["개인", "외국인", "기관"], lines=[20000])
        self.assertEqual(next(s for s in fig.layout.shapes if s.type == "line").yref, "y")
        bands = [s for s in fig.layout.shapes if s.type == "rect"]
        self.assertEqual(len(bands), 2)
        self.assertEqual([s.name for s in bands], ["개인 순매수", "기관 순매수"])
        self.assertEqual(bands[0].x1, bands[1].x0)
        self.assertEqual(bands[0].x0, -0.45)
        self.assertEqual(bands[1].x1, 0.45)
        self.assertTrue(all(s.yref == "y domain" and s.y0 == 0 and s.y1 == 1 and s.layer == "below" for s in bands))
        fig = figure(d, "test", ["개인"], threshold=5, percent=True)
        self.assertFalse(any(s.type == "rect" for s in fig.layout.shapes))

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

    def test_fixed_window_with_background_bands(self):
        d = demo_data("20260101", "20260401")
        for start in (0, len(d) - 20):
            fig = figure(d, "test", ["개인", "외국인", "기관"], visible_bars=20, window_start=start)
            self.assertEqual(tuple(fig.layout.xaxis.range), (start - 0.5, start + 19.5))
            self.assertEqual(fig.layout.xaxis.range, fig.layout.xaxis2.range)
            self.assertTrue(all(s.yref == "y domain" for s in fig.layout.shapes))
            self.assertEqual(fig.data[0].increasing.fillcolor, "#ef4444")
            self.assertEqual(fig.data[0].decreasing.fillcolor, "#3b82f6")


if __name__ == "__main__":
    unittest.main()
