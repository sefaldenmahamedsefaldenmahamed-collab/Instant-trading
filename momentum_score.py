"""Composite Momentum Score (0–100) — 10 weighted factors with a full transparent breakdown
(shown on the dashboard: "لماذا هذه العملة؟")."""
from __future__ import annotations

import time


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _grade_positive(pct: float, soft: float, hard: float) -> float:
    """Map a momentum % to 0..1 (soft → 0.5, hard+ → 1.0)."""
    if pct <= 0:
        return _clamp(0.5 + pct / 10.0, 0.0, 0.5)   # negative momentum grades low
    if pct >= hard:
        return 1.0
    if pct >= soft:
        return 0.5 + 0.5 * (pct - soft) / max(hard - soft, 1e-9)
    return 0.5 * (pct / max(soft, 1e-9))


WEIGHTS = {
    "mom_5m": 8, "mom_15m": 10, "mom_1h": 14, "mom_4h": 8, "mom_24h": 8,
    "spike_5m": 16, "liquidity": 6, "rsi_15m": 10, "social": 12, "pressure": 8,
}


def score_candidate(c: dict, fng_penalty: float = 0.0, extra: dict | None = None) -> tuple[float, dict]:
    """Returns (score 0-100, breakdown {factor: {value, weight, grade}})."""
    breakdown: dict[str, dict] = {}

    # 1-5 · price momentum across timeframes
    mom_specs = {
        "mom_5m": (1.5, 5.0), "mom_15m": (2.5, 8.0), "mom_1h": (4.0, 12.0),
        "mom_4h": (5.0, 15.0), "mom_24h": (6.0, 25.0),
    }
    for key, (soft, hard) in mom_specs.items():
        g = _grade_positive(float(c.get(key) or 0.0), soft, hard)
        breakdown[key] = {"value": round(float(c.get(key) or 0.0), 2), "weight": WEIGHTS[key], "grade": round(g, 3)}

    # 6 · 5-minute volume spike (the explosion detector)
    spike = float(c.get("spike_5m") or 0.0)
    g_spike = _clamp(spike / 6.0)          # 6× baseline volume → max grade
    breakdown["spike_5m"] = {"value": f"{spike}x", "weight": WEIGHTS["spike_5m"], "grade": round(g_spike, 3)}

    # 7 · liquidity (24h quote volume)
    qv = float(c.get("quote_volume_24h") or 0.0)
    g_liq = _clamp((qv - 2_000_000) / 48_000_000 + 0.3)
    breakdown["liquidity"] = {"value": f"{qv/1e6:.1f}M", "weight": WEIGHTS["liquidity"], "grade": round(g_liq, 3)}

    # 8 · RSI(14) on 15m — sweet spot 58..78, overheated >86, dead <45
    rsi = c.get("rsi_15m")
    if rsi is None:
        g_rsi, rsi_txt = 0.4, "—"
    elif rsi >= 86:
        g_rsi = 0.35
    elif rsi >= 58:
        g_rsi = 0.5 + 0.5 * (rsi - 58) / 20.0
    elif rsi >= 45:
        g_rsi = 0.3 + 0.4 * (rsi - 45) / 13.0
    else:
        g_rsi = 0.1
    breakdown["rsi_15m"] = {"value": rsi_txt if rsi is None else f"{rsi}", "weight": WEIGHTS["rsi_15m"],
                            "grade": round(_clamp(g_rsi), 3)}

    # 9 · social/news boost (CoinGecko trending, Reddit/X mentions)
    g_social = _clamp(float(c.get("social_boost") or 0.0))
    src = c.get("sources") or []
    if "coingecko_trending" in src:
        g_social = min(1.0, g_social + 0.35)
    if "coingecko_mover" in src:
        g_social = min(1.0, g_social + 0.15)
    breakdown["social"] = {"value": ",".join(s for s in src if s != "binance") or "—",
                           "weight": WEIGHTS["social"], "grade": round(g_social, 3)}

    # 10 · buy pressure (taker buy volume share, 5m)
    bp = float(c.get("buy_pressure") or 0.5)
    g_bp = _clamp((bp - 0.42) / 0.35)
    breakdown["pressure"] = {"value": f"{bp*100:.0f}%", "weight": WEIGHTS["pressure"], "grade": round(g_bp, 3)}

    total = sum(bd["weight"] * bd["grade"] for bd in breakdown.values())
    total = max(0.0, total - fng_penalty)
    if extra:
        for k, v in extra.items():
            breakdown[k] = v
    breakdown["_meta"] = {"fng_penalty": round(fng_penalty, 2), "ts": time.time()}
    return round(total, 1), breakdown
