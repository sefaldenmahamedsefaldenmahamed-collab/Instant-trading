"""External discovery: find momentum BEFORE it shows on Binance screeners.
Sources: CoinGecko trending + global top movers, Reddit mention spikes (best-effort),
X/Twitter (optional, only if a bearer token is provided), Fear & Greed Index."""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque

import aiohttp

from app.config import CFG

log = logging.getLogger("external")

_MENTION_HIST: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
_UA = {"User-Agent": "Mozilla/5.0 (compatible; MomentumSniper/1.0)"}


async def _get_json(session: aiohttp.ClientSession, url: str, headers: dict | None = None,
                    timeout: int = 12) -> dict | list | None:
    try:
        async with session.get(url, headers=headers or _UA,
                               timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status != 200:
                log.debug("GET %s → %s", url, r.status)
                return None
            return await r.json(content_type=None)
    except Exception as e:
        log.debug("GET %s failed: %s", url, e)
        return None


# ── CoinGecko ─────────────────────────────────────────────────────────────
async def coingecko_signals(session: aiohttp.ClientSession) -> dict:
    """Returns {"trending_bases": {BASE: rank}, "movers": {BASE: pct24h}}"""
    out: dict = {"trending_bases": {}, "movers": {}}
    data = await _get_json(session, f"{CFG.coingecko_base}/search/trending")
    if isinstance(data, dict):
        for i, c in enumerate(data.get("coins", [])[:15]):
            item = c.get("item") or {}
            sym = (item.get("symbol") or "").upper()
            if sym:
                out["trending_bases"][sym] = i + 1
    movers = await _get_json(
        session,
        f"{CFG.coingecko_base}/coins/markets?vs_currency=usd&order=price_change_desc&per_page=30&page=1",
    )
    if isinstance(movers, list):
        for m in movers:
            sym = (m.get("symbol") or "").upper()
            pct = m.get("price_change_percentage_24h")
            if sym and isinstance(pct, (int, float)):
                out["movers"][sym] = float(pct)
    return out


# ── Reddit mentions ───────────────────────────────────────────────────────
_TICKER_RE = re.compile(r"\$([A-Za-z]{2,10})\b|\b([A-Z]{3,8})\b")


def _count_mentions(text: str, bases: set[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for m in _TICKER_RE.finditer(text or ""):
        tok = (m.group(1) or m.group(2) or "").upper()
        if tok in bases:
            counts[tok] += 1
    return counts


async def reddit_mentions(session: aiohttp.ClientSession, bases: set[str]) -> dict[str, int]:
    if not CFG.reddit_enabled or not bases:
        return {}
    totals: dict[str, int] = defaultdict(int)
    subs = [s.strip() for s in CFG.reddit_subreddits.split(",") if s.strip()]
    for sub in subs[:3]:
        data = await _get_json(session, f"{CFG.reddit_base}/r/{sub}/hot.json?limit=50")
        children = (data or {}).get("data", {}).get("children", []) if isinstance(data, dict) else []
        for ch in children:
            d = ch.get("data", {})
            text = f'{d.get("title", "")} {d.get("selftext", "")[:300]}'
            for base, n in _count_mentions(text, bases).items():
                totals[base] += n
    return dict(totals)


def mention_boost(bases: set[str], mentions: dict[str, int]) -> dict[str, float]:
    """Mentions now vs baseline EMA → boost 0..1. Keeps a rolling history per base."""
    boost: dict[str, float] = {}
    for base in bases:
        cur = mentions.get(base, 0)
        hist = _MENTION_HIST[base]
        baseline = (sum(hist) / len(hist)) if hist else 0.0
        hist.append(cur)
        if baseline <= 0.01:
            boost[base] = 0.35 if cur >= 3 else 0.0
        else:
            ratio = cur / baseline
            boost[base] = min(1.0, max(0.0, (ratio - 1.5) / 4.0)) if ratio > 1.5 else 0.0
    return boost


# ── X / Twitter (optional) ────────────────────────────────────────────────
async def x_mentions(session: aiohttp.ClientSession, bases: set[str]) -> dict[str, int]:
    """Only runs if X_BEARER_TOKEN is set (X API is paid). Counts $TICKER in recent tweets."""
    if not CFG.x_bearer_token or not bases:
        return {}
    headers = {"Authorization": f"Bearer {CFG.x_bearer_token}"}
    totals: dict[str, int] = defaultdict(int)
    query = "(" + " OR ".join(f"${b}" for b in list(bases)[:20]) + ") -is:retweet lang:en"
    data = await _get_json(
        session,
        "https://api.x.com/2/tweets/search/recent?max_results=50&query=" + aiohttp.helpers.quote(query),
        headers=headers,
        timeout=10,
    )
    for t in (data or {}).get("data", []) if isinstance(data, dict) else []:
        for base, n in _count_mentions(t.get("text", ""), bases).items():
            totals[base] += n
    return dict(totals)


# ── Fear & Greed ──────────────────────────────────────────────────────────
async def fear_greed(session: aiohttp.ClientSession) -> dict | None:
    data = await _get_json(session, CFG.fng_base, timeout=10)
    try:
        d = (data or {}).get("data", [])[0]
        return {"value": int(d["value"]), "classification": d.get("value_classification", "")}
    except Exception:
        return None


def fng_context(fng: dict | None) -> dict:
    """Turn F&G into a behaviour context for the strategy."""
    if not fng:
        return {"value": None, "pause_entries": False, "score_penalty": 0.0, "label": "غير متوفر"}
    v = fng["value"]
    ctx = {"value": v, "label": fng.get("classification", ""), "score_penalty": 0.0, "pause_entries": False}
    if v >= CFG.fng_greed_threshold:                 # extreme greed → be pickier
        ctx["score_penalty"] = CFG.fng_greed_score_penalty
    elif v <= CFG.fng_fear_threshold:                # extreme fear → stand aside
        ctx["pause_entries"] = True
    return ctx


# ── one full external pass ────────────────────────────────────────────────
async def collect_external(session: aiohttp.ClientSession) -> dict:
    """Runs all external sources; returns a combined signal map keyed by BASE asset."""
    cg = await coingecko_signals(session)
    bases = set(cg["trending_bases"]) | set(cg["movers"])
    reddit = await reddit_mentions(session, bases)
    x = await x_mentions(session, bases)
    mentions = {b: reddit.get(b, 0) + x.get(b, 0) for b in bases}
    boosts = mention_boost(bases, mentions)
    for b, m in list(mentions.items()):
        if m:
            log.debug("mentions %s: %s", b, m)
    return {
        "ts": time.time(),
        "trending": cg["trending_bases"],
        "movers": cg["movers"],
        "boosts": boosts,
        "mentions": mentions,
    }
