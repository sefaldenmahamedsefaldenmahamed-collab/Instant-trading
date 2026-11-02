"""Paper broker: simulated spot fills using live Binance prices. No API keys needed."""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from app.config import CFG

log = logging.getLogger("paper")


class PaperBroker:
    mode = "paper"

    def __init__(self, price_provider: Callable[[str], Awaitable[float | None]] | None = None) -> None:
        self.balance = {CFG.quote_asset: CFG.paper_start_balance}
        self._price_provider = price_provider

    async def get_price(self, symbol: str) -> float | None:
        if self._price_provider:
            try:
                return await self._price_provider(symbol)
            except Exception:
                return None
        return None

    async def get_balance(self) -> dict[str, float]:
        return dict(self.balance)

    @property
    def usdt_free(self) -> float:
        return self.balance.get(CFG.quote_asset, 0.0)

    def _fee(self, quote_value: float) -> float:
        return quote_value * CFG.fee_pct / 100.0

    async def buy_market(self, symbol: str, quote_amount: float, **_) -> dict:
        quote_amount = round(min(quote_amount, self.usdt_free), 8)
        if quote_amount < CFG.min_notional_usdt:
            raise ValueError(f"المبلغ أقل من الحد الأدنى ({quote_amount:.2f} < {CFG.min_notional_usdt})")
        price = await self.get_price(symbol)
        if not price or price <= 0:
            raise ValueError("لا يوجد سعر متاح للتنفيذ المحاكى")
        fill_price = price * (1.0 + CFG.slippage_pct / 100.0)
        fee = self._fee(quote_amount)
        net_quote = quote_amount - fee
        qty = net_quote / fill_price
        self.balance[CFG.quote_asset] = round(self.usdt_free - quote_amount, 8)
        return {
            "order_id": f"paper-{int(time.time()*1000)}",
            "symbol": symbol,
            "price": fill_price,
            "qty": qty,
            "quote": quote_amount,
            "fee": fee,
            "ts": time.time(),
        }

    async def sell_market(self, symbol: str, qty: float, *, proceeds_hint: float | None = None, **_) -> dict:
        price = await self.get_price(symbol)
        if not price or price <= 0:
            raise ValueError("لا يوجد سعر متاح للتنفيذ المحاكى")
        fill_price = price * (1.0 - CFG.slippage_pct / 100.0)
        quote = qty * fill_price
        fee = self._fee(quote)
        self.balance[CFG.quote_asset] = round(self.usdt_free + quote - fee, 8)
        return {
            "order_id": f"paper-{int(time.time()*1000)}",
            "symbol": symbol,
            "price": fill_price,
            "qty": qty,
            "quote": quote,
            "fee": fee,
            "ts": time.time(),
        }
