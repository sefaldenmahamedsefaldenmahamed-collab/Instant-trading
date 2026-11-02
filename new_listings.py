"""New Listings Sniper — detects newly listed Binance spot symbols two ways:
1) exchangeInfo diff (official & reliable): a symbol appears with status TRADING.
2) Binance CMS announcements (best-effort): "Binance Will List X (XYZ)" → watchlist
   so the bot is ready the second the pair opens.
"""
from __future__ import annotations

import logging
import re
import time

import aiohttp

from app.config import CFG
from app.exchange.binance_client import BinanceClient

log = logging.getLogger("newlistings")

_WILL_LIST_RE = re.compile(r"will\s+list\s+(?P<name>[A-Za-z0-9 .\-]+?)\s*\((?P<ticker>[A-Z0-9]{2,12})\)",
                           re.IGNORECASE)
_OPEN_TRADING_RE = re.compile(r"has\s+(?:now\s+)?(?:opened\s+trading|listed)\s+(?P<name>[A-Za-z0-9 .\-]+?)\s*\((?P<ticker>[A-Z0-9]{2,12})\)",
                              re.IGNORECASE)
_ANNOUNCE_URLS = [
    "{base}/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId={cat}&pageNo=1&pageSize=20&type=1",
    "{base}/bapi/apex/v1/public/apex/cms/article/catalog/list/query?catalogId={cat}&pageNo=1&pageSize=20&type=1",
]
_ANNOUNCE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "application/json",
}


async def fetch_announcements(session: aiohttp.ClientSession) -> list[dict]:
    """Best-effort list of {"title", "ticker", "ts"} from the New-Cryptocurrency-Listing catalog."""
    results: list[dict] = []
    for tpl in _ANNOUNCE_URLS:
        url = tpl.format(base=CFG.binance_announce_base.rstrip("/"), cat=CFG.new_listing_catalog_id)
        try:
            async with session.get(url, headers=_ANNOUNCE_HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)
            articles = ((data or {}).get("data") or {}).get("articleList") or []
            for a in articles:
                title = a.get("title", "")
                ts = (a.get("releaseDate") or 0) / 1000.0
                m = _WILL_LIST_RE.search(title) or _OPEN_TRADING_RE.search(title)
                if m:
                    results.append({"title": title, "ticker": m.group("ticker").upper(),
                                    "name": m.group("name").strip(), "ts": ts})
            if results:
                return results
        except Exception as e:
            log.debug("announcements fetch failed (%s): %s", tpl[:60], e)
    return results


class NewListingsWatcher:
    def __init__(self, store) -> None:
        self.store = store
        self.known_symbols: set[str] = set()
        self.seen_articles: set[int] = set()
        self.first_snapshot_done = False

    def prime(self, symbols: set[str]) -> None:
        """First call after startup: adopt current symbol set as baseline (no spam)."""
        self.known_symbols = set(symbols)
        self.first_snapshot_done = True

    async def check_exchange_diff(self, client: BinanceClient) -> list[dict]:
        """Returns newly TRADING symbols since last check (and primes on first run)."""
        exinfo = await client.exchange_info(force=True, max_age=0)
        current = {s for s, info in exinfo.items()
                   if info.get("status") == "TRADING" and info.get("quoteAsset") == CFG.quote_asset}
        if not self.first_snapshot_done:
            self.prime(current)
            return []
        fresh = current - self.known_symbols
        self.known_symbols = current
        return sorted(fresh)

    async def scan_announcements(self, session: aiohttp.ClientSession) -> list[dict]:
        """Find 'Will List' announcements we haven't seen; upsert watchlist rows."""
        news: list[dict] = []
        for a in await fetch_announcements(session):
            art_id = hash(a["title"].lower())          # title alone: releaseDate may change server-side
            if art_id in self.seen_articles:
                continue
            self.seen_articles.add(int(art_id))
            if len(self.seen_articles) > 400:
                self.seen_articles = set(list(self.seen_articles)[-200:])
            news.append(a)
        return news

    def ticker_to_symbol(self, ticker: str) -> str | None:
        sym = f"{ticker}{CFG.quote_asset}"
        return sym if sym in self.known_symbols else None
