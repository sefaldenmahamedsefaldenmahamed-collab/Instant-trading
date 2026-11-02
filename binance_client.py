"""Binance REST client (public + signed HMAC endpoints) built on aiohttp.
Works for live (api.binance.com) and testnet (testnet.binance.vision) via CFG.api_base.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from app.config import CFG

log = logging.getLogger("binance")


class BinanceError(Exception):
    def __init__(self, code: Any, msg: str, status: int = 0) -> None:
        super().__init__(f"[{code}] {msg} (http {status})")
        self.code = code
        self.msg = msg
        self.status = status


class BinanceClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._exinfo_ts: float = 0.0
        self.exinfo: dict[str, dict] = {}          # symbol → exchangeInfo symbol object
        self._sem = asyncio.Semaphore(6)
        self.server_time_offset: float = 0.0

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"X-MBX-APIKEY": CFG.api_key} if CFG.api_key else {},
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    # ── plumbing ──────────────────────────────────────────────────────────
    async def _req(self, method: str, path: str, params: dict | None = None, signed: bool = False) -> Any:
        if self._session is None:
            raise BinanceError("session", "client not started")
        params = dict(params or {})
        attempts = 0
        while True:
            attempts += 1
            if signed:
                params["timestamp"] = int(time.time() * 1000 + self.server_time_offset * 1000)
                params["recvWindow"] = CFG.recv_window
                qs = urlencode(params, doseq=True)
                sig = hmac.new(CFG.api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
                url = f"{CFG.api_base}{path}?{qs}&signature={sig}"
            else:
                url = f"{CFG.api_base}{path}"
                if params:
                    url += "?" + urlencode(params, doseq=True)
            try:
                async with self._sem:
                    async with self._session.request(method, url) as resp:
                        if resp.status in (418, 429):
                            retry = float(resp.headers.get("Retry-After", "10"))
                            log.warning("rate limited %s — sleeping %ss", path, retry)
                            await asyncio.sleep(retry + 0.5)
                            continue
                        data = await resp.json(content_type=None)
                        if resp.status >= 400:
                            if isinstance(data, dict) and "code" in data:
                                # clock drift fix
                                if data.get("code") == -1021:
                                    await self.sync_time()
                                    if attempts < 3:
                                        continue
                                raise BinanceError(data.get("code"), data.get("msg", "?"), resp.status)
                            raise BinanceError("http", str(data)[:200], resp.status)
                        return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempts >= 3:
                    raise BinanceError("network", str(e)) from e
                await asyncio.sleep(1.5 * attempts)

    async def sync_time(self) -> None:
        try:
            data = await self._req("GET", "/api/v3/time")
            self.server_time_offset = data["serverTime"] / 1000 - time.time()
        except Exception:
            self.server_time_offset = 0.0

    # ── public endpoints ──────────────────────────────────────────────────
    async def ping(self) -> bool:
        try:
            await self._req("GET", "/api/v3/ping")
            return True
        except Exception:
            return False

    async def exchange_info(self, force: bool = False, max_age: float = 3600) -> dict[str, dict]:
        now = time.time()
        if force or not self.exinfo or now - self._exinfo_ts > max_age:
            data = await self._req("GET", "/api/v3/exchangeInfo", {"permissions": "SPOT"})
            self.exinfo = {s["symbol"]: s for s in data.get("symbols", [])}
            self._exinfo_ts = now
        return self.exinfo

    async def tickers_all(self) -> list[dict]:
        return await self._req("GET", "/api/v3/ticker/24hr")

    async def tickers(self, symbols: list[str]) -> dict[str, dict]:
        if not symbols:
            return {}
        data = await self._req("GET", "/api/v3/ticker/24hr", {"symbols": '["' + '","'.join(symbols) + '"]'})
        return {d["symbol"]: d for d in data}

    async def klines(self, symbol: str, interval: str = "1m", limit: int = 60) -> list[list]:
        return await self._req("GET", "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    async def book_ticker(self, symbol: str) -> dict | None:
        try:
            return await self._req("GET", "/api/v3/ticker/bookTicker", {"symbol": symbol})
        except BinanceError:
            return None

    # ── signed endpoints ──────────────────────────────────────────────────
    async def account(self) -> dict:
        return await self._req("GET", "/api/v3/account", signed=True)

    async def usdt_free(self) -> float:
        acc = await self.account()
        for b in acc.get("balances", []):
            if b["asset"] == CFG.quote_asset:
                return float(b["free"])
        return 0.0

    async def order_market_buy(self, symbol: str, quote_qty: float) -> dict:
        return await self._req(
            "POST", "/api/v3/order",
            {"symbol": symbol, "side": "BUY", "type": "MARKET", "quoteOrderQty": f"{quote_qty:.8f}"},
            signed=True,
        )

    async def order_market_sell(self, symbol: str, qty: float) -> dict:
        return await self._req(
            "POST", "/api/v3/order",
            {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": f"{qty:.8f}"},
            signed=True,
        )

    # ── helpers ───────────────────────────────────────────────────────────
    def symbol_filters(self, symbol: str) -> dict:
        s = self.exinfo.get(symbol)
        if not s:
            return {}
        out: dict[str, float] = {}
        for f in s.get("filters", []):
            ftype = f.get("filterType")
            if ftype in ("LOT_SIZE",):
                out["stepSize"] = float(f["stepSize"])
                out["minQty"] = float(f["minQty"])
            elif ftype in ("NOTIONAL", "MIN_NOTIONAL"):
                out["minNotional"] = float(f.get("minNotional", 0))
            elif ftype == "PRICE_FILTER":
                out["tickSize"] = float(f["tickSize"])
        return out

    @staticmethod
    def round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return (int(value / step)) * step

    def is_spot_usdt(self, symbol: str) -> bool:
        s = self.exinfo.get(symbol)
        return bool(s and s.get("status") == "TRADING" and s.get("quoteAsset") == CFG.quote_asset)
