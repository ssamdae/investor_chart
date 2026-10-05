import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

INVESTORS = {
    "개인": ("personal", "triangle-up", "#f59e0b"),
    "외국인": ("foreign", "circle", "#14b8a6"),
    "기관": ("institution", "diamond", "#a78bfa"),
}


def demo_data(start, end):
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(42)
    close = 20000 * np.exp(np.cumsum(rng.normal(0, 0.015, len(dates))))
    op = close * np.exp(rng.normal(0, 0.008, len(dates)))
    df = pd.DataFrame({"date": dates, "open": op.round(), "close": close.round(),
                       "high": (np.maximum(op, close) * 1.02).round(),
                       "low": (np.minimum(op, close) * 0.98).round(),
                       "volume": rng.integers(200000, 2000000, len(dates))})
    df["trading_value"] = df.close * df.volume
    for who in ("personal", "foreign"):
        df[who] = df.trading_value * rng.uniform(-0.25, 0.25, len(df))
    df["institution"] = -df.personal - df.foreign
    for who in ("personal", "foreign", "institution"):
        df[who + "_pct"] = df[who] / df.trading_value * 100
    return df


def figure(df, title, investors, threshold=0, percent=False, lines=(), averages=(),
           visible_bars=None, window_start=None):
    count = min(len(df), visible_bars or len(df))
    start = max(0, min(len(df) - count, window_start if window_start is not None else len(df) - count))
    visible = df.iloc[start:start + count]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.78, 0.22], vertical_spacing=0.04)
    x = df.date.dt.strftime("%Y-%m-%d").tolist()
    fig.add_trace(go.Candlestick(x=x, open=df.open, high=df.high, low=df.low, close=df.close,
        increasing_line_color="#ef4444", decreasing_line_color="#3b82f6", name="일봉",
        hoverinfo="skip"), row=1, col=1)
    for period in averages:
        fig.add_trace(go.Scatter(x=x, y=df.close.rolling(period).mean(), mode="lines",
            line={"width": 1}, name=f"{period}일선", hoverinfo="skip"), row=1, col=1)
    tooltip = []
    for _, r in df.iterrows():
        text = f"{r.date:%Y-%m-%d}<br>시가 {r.open:,.0f} · 고가 {r.high:,.0f}<br>저가 {r.low:,.0f} · 종가 {r.close:,.0f}<br>거래량 {r.volume:,.0f}주"
        for label, (who, _, _) in INVESTORS.items():
            text += (f"<br>{label}: 수급 미제공" if pd.isna(r[who]) else
                     f"<br>{label}: {r[who]/1e8:+,.2f}억원 ({r[who+'_pct']:+.2f}%)")
        tooltip.append(text)
    # A hover target on every candle exposes ALL actors, including net sellers.
    fig.add_trace(go.Scatter(x=x, y=df.close, mode="markers",
        marker={"size": 10, "color": "rgba(255,255,255,0.01)"},
        text=tooltip, hovertemplate="%{text}<extra></extra>", showlegend=False), row=1, col=1)
    gap = max(float(visible.high.max() - visible.low.min()) * 0.025, float(visible.close.median()) * 0.008)
    for idx, (label, (who, symbol, color)) in enumerate(INVESTORS.items()):
        if label not in investors:
            continue
        mask = (df[who] > 0) & ((df[who+"_pct"] >= threshold) if percent else True)
        fig.add_trace(go.Scatter(x=[d for d, ok in zip(x, mask) if ok],
            y=df.loc[mask, "low"] - gap * (idx + 1), mode="markers",
            marker={"symbol": symbol, "size": 10, "color": color}, name=f"{label} 순매수",
            text=[t for t, ok in zip(tooltip, mask) if ok],
            hovertemplate="%{text}<extra></extra>"), row=1, col=1)
    for price in lines:
        fig.add_hline(y=price, line_dash="dash", line_color="#64748b",
                      annotation_text=f"{price:,.0f}원", row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=df.volume, name="거래량", showlegend=False,
        marker_color=np.where(df.close >= df.open, "#ef4444", "#3b82f6"),
        hovertemplate="%{x}<br>거래량 %{y:,.0f}주<extra></extra>"), row=2, col=1)
    fig.update_layout(title=title, height=800, template="plotly_white", dragmode="pan",
                      margin={"l": 30, "r": 60, "t": 70, "b": 30},
                      legend={"orientation": "h", "y": 1.04}, hovermode="closest",
                      xaxis_rangeslider_visible=False,
                      uirevision=f"{title}:{len(df)}:{start}:{count}")
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=x,
                      nticks=12, showgrid=False, range=[start - 0.5, start + count - 0.5])
    # Scale to the selected window so off-screen historical extremes do not
    # compress the candles. Leave enough space for the three signal rows.
    bottom, top = float(visible.low.min()) - gap * 4, float(visible.high.max()) + gap * 2
    fig.update_yaxes(title_text="가격 (원)", side="right", range=[bottom, top], row=1, col=1)
    fig.update_yaxes(title_text="거래량 (주)", side="right", range=[0, max(1, float(visible.volume.max()) * 1.1)], row=2, col=1)
    return fig
