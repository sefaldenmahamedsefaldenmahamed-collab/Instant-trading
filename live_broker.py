"""Live/Testnet broker: real MARKET orders via signed Binance REST (same code path for both,
only the base URL differs — testnet → testnet.binance.vision)."""
from __future__ import annotations

import logging

from app.config import CFG
from app.exchange.binance_client import BinanceClient, BinanceError

log = logging.getLogger("live")


class LiveBroker:
    def __init__(self, client: BinanceClient) -> None:
        self.client = client
        self.mode = CFG.mode  # "live" | "testnet"

    async def get_price(self, symbol: str) -> float | None:
        try:
            t = await self.client.tickers([symbol])
            return float(t[symbol]["lastPrice"])
        except Exception:
            return None

    async def get_balance(self) -> dict[str, float]:
        acc = await self.client.account()
        return {b["asset"]: float(b["free"]) for b in acc.get("balances", []) if float(b["free"]) > 0}

    async def usdt_free(self) -> float:
        bal = await self.get_balance()
        return bal.get(CFG.quote_asset, 0.0)

    async def buy_market(self, symbol: str, quote_amount: float, **_) -> dict:
        filters = self.client.symbol_filters(symbol)
        min_notional = filters.get("minNotional", CFG.min_notional_usdt)
        if quote_amount < min_notional:
            raise ValueError(f"المبلغ {quote_amount:.2f} أقل من الحد الأدنى للعملة ({min_notional})")
        r = await self.client.order_market_buy(symbol, quote_amount)
        executed_quote = float(r.get("cummulativeQuoteQty", 0.0))
        qty = float(r.get("executedQty", 0.0))
        price = (executed_quote / qty) if qty > 0 else 0.0
        fee = 0.0
        for f in r.get("fills", []) or []:
            if f.get("commissionAsset") == CFG.quote_asset:
                fee += float(f.get("commission", 0.0))
        return {
            "order_id": str(r.get("orderId", "")),
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "quote": executed_quote,
            "fee": fee,
            "ts": r.get("transactTime", 0) / 1000.0,
        }

    async def sell_market(self, symbol: str, qty: float, **_) -> dict:
        filters = self.client.symbol_filters(symbol)
        step = filters.get("stepSize", 0.0)
        min_qty = filters.get("minQty", 0.0)
        qty = self.client.round_step(qty, step)
        if qty <= 0 or qty < min_qty:
            raise ValueError(f"الكمية المتبقية أصغر من الحد الأدنى للبيع ({qty})")
        r = await self.client.order_market_sell(symbol, qty)
        executed_quote = float(r.get("cummulativeQuoteQty", 0.0))
        exec_qty = float(r.get("executedQty", 0.0)) or qty
        price = (executed_quote / exec_qty) if exec_qty > 0 else 0.0
        fee = 0.0
        for f in r.get("fills", []) or []:
            if f.get("commissionAsset") == CFG.quote_asset:
                fee += float(f.get("commission", 0.0))
        return {
            "order_id": str(r.get("orderId", "")),
            "symbol": symbol,
            "price": price,
            "qty": exec_qty,
            "quote": executed_quote,
            "fee": fee,
            "ts": r.get("transactTime", 0) / 1000.0,
        }
