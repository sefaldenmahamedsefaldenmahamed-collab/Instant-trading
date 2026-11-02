"""Market scanner: pulls Binance 24h tickers, builds candidates, deep-dives the top N with klines
(1m & 15m) to compute short-term momentum, 5m volume spike and RSI(14)."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from app.config import CFG
from app.exchange.binance_client import BinanceClient

log = logging.getLogger("scanner")

# symbol → rolling window of recent scan snapshots (for spike fallback)
_vol_hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=12))


def _pct(a: float, b: float) -> float:
    if b <= 0:
        return 0.0
    return (a / b - 1.0) * 100.0


def rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains, losses = 0.0, 0.0
    period = 14
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(d for d in deltas[:period] if d > 0) / period
    avg_loss = sum(-d for d in deltas[:period] if d < 0) / period
    for d in deltas[period:]:
        g, l = (d, 0.0) if d > 0 else (0.0, -d)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


async def fetch_universe(client: BinanceClient) -> dict[str, dict]:
    """All TRADING */USDT spot symbols (minus blacklist/leveraged) → ticker dict."""
    exinfo = await client.exchange_info()
    tickers = {t["symbol"]: t for t in await client.tickers_all()}
    universe: dict[str, dict] = {}
    for sym, info in exinfo.items():
        if info.get("quoteAsset") != CFG.quote_asset or info.get("status") != "TRADING":
            continue
        base = info.get("baseAsset", "")
        if sym in CFG.blacklist or any(sym.endswith(p) for p in CFG.leveraged_patterns):
            continue
        t = tickers.get(sym)
        if not t:
            continue
        try:
            universe[sym] = {
                "symbol": sym,
                "base": base,
                "price": float(t["lastPrice"]),
                "change_24h": float(t.get("priceChangePercent", 0.0)),
                "quote_volume_24h": float(t.get("quoteVolume", 0.0)),
                "trades_24h": int(t.get("count", 0)),
                "high_24h": float(t.get("highPrice", 0.0)),
                "low_24h": float(t.get("lowPrice", 0.0)),
            }
        except (ValueError, KeyError):
            continue
    return universe


async def deep_dive(client: BinanceClient, sym: str) -> dict:
    """Kline-based micro-momentum for a single candidate. Never raises."""
    out: dict = {"mom_5m": 0.0, "mom_15m": 0.0, "mom_1h": 0.0, "mom_4h": 0.0,
                 "rsi_15m": None, "spike_5m": 0.0, "buy_pressure": 0.5, "klines_ok": False}
    try:
        k1 = await client.klines(sym, "1m", 61)
        if len(k1) >= 20:
            closes = [float(k[4]) for k in k1]
            qvols = [float(k[7]) for k in k1]
            trades = [int(k[8]) for k in k1]
            tb = [float(k[10]) for k in k1]
            out["mom_5m"] = _pct(closes[-1], closes[-6])
            out["mom_15m"] = _pct(closes[-1], closes[-16])
            out["mom_1h"] = _pct(closes[-1], closes[-61]) if len(closes) >= 61 else 0.0
            last5 = sum(qvols[-5:])
            prev55 = qvols[-60:-5]
            if prev55:
                baseline = (sum(prev55) / len(prev55)) * 5
                out["spike_5m"] = round(last5 / baseline, 2) if baseline > 0 else 0.0
            qv5 = sum(qvols[-5:])
            if qv5 > 0:
                out["buy_pressure"] = round(sum(tb[-5:]) / qv5, 3)
            out["trades_1m_avg"] = round(sum(trades[-15:]) / 15.0, 1)
            out["klines_ok"] = True
    except Exception as e:
        log.debug("klines 1m %s failed: %s", sym, e)
    try:
        k15 = await client.klines(sym, "15m", 30)
        if len(k15) >= 17:
            closes = [float(k[4]) for k in k15]
            out["mom_4h"] = _pct(closes[-1], closes[-17])
            out["rsi_15m"] = round(rsi14(closes), 1) if len(closes) >= 15 else None
    except Exception as e:
        log.debug("klines 15m %s failed: %s", sym, e)
    return out


async def scan(client: BinanceClient, max_candidates: int | None = None) -> list[dict]:
    """Full scan pass: universe → pre-filter → pre-score → deep dive top N → final candidate list."""
    n = max_candidates or CFG.deep_dive_top_n
    universe = await fetch_universe(client)
    if not universe:
        return []

    # liquidity floor
    liquid = [u for u in universe.values() if u["quote_volume_24h"] >= CFG.min_quote_volume_24h]
    # hot list by 24h change & volume momentum — keep a wide net, sort later
    hot = sorted(liquid, key=lambda u: u["change_24h"], reverse=True)[: max(n * 4, 40)]

    for u in hot:
        _vol_hist[u["symbol"]].append({"ts": time.time(), "qv": u["quote_volume_24h"]})

    pre: list[dict] = []
    for u in hot:
        hist = _vol_hist[u["symbol"]]
        pre.append(
            {
                **u,
                "spike_5m": 0.0,
                "mom_5m": 0.0,
                "mom_15m": 0.0,
                "mom_1h": 0.0,
                "mom_4h": 0.0,
                "rsi_15m": None,
                "buy_pressure": 0.5,
                "sources": ["binance"],
                "social_boost": 0.0,
                "new_listing": False,
                "listed_at": None,
                "ts": time.time(),
            }
        )

    # deep dive the top by 24h change (and any with social boost later merged in)
    top = sorted(pre, key=lambda c: c["change_24h"], reverse=True)[:n]
    results: list[dict] = []
    for c in top:
        dd = await deep_dive(client, c["symbol"])
        c.update(dd)
        results.append(c)
    return results
