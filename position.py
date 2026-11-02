"""Position model with TP ladder + trailing stop state."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from app.config import CFG


def new_pos_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Position:
    symbol: str
    base: str
    qty: float                      # remaining (unsold) quantity
    qty_initial: float
    entry_price: float
    entry_ts: float
    pos_id: str = field(default_factory=new_pos_id)
    mode: str = CFG.mode
    score_at_entry: float = 0.0
    reasons: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    ladder: list[dict] = field(default_factory=list)   # [{"gain":100,"sell":30,"done":False}, ...]
    trail_trigger: float = CFG.trail_trigger_pct
    trail_drop: float = CFG.trail_drop_pct
    hard_sl: float = CFG.hard_stop_loss_pct
    peak_price: float = 0.0
    trailing_armed: bool = False
    realized_quote: float = 0.0     # net realized pnl in USDT (after fees), accumulates
    fees_paid: float = 0.0
    max_gain_pct: float = 0.0
    new_listing: bool = False
    last_mark: float = 0.0

    def __post_init__(self) -> None:
        if not self.ladder:
            self.ladder = [{"gain": g, "sell": s, "done": False} for (g, s) in CFG.tp_ladder]
        self.peak_price = self.peak_price or self.entry_price
        self.last_mark = self.last_mark or self.entry_price

    # ── metrics ───────────────────────────────────────────────────────────
    def gain_pct(self, mark: float | None = None) -> float:
        p = mark or self.last_mark
        if self.entry_price <= 0:
            return 0.0
        return (p / self.entry_price - 1.0) * 100.0

    def value_quote(self, mark: float | None = None) -> float:
        return self.qty * (mark or self.last_mark)

    def update_mark(self, mark: float) -> None:
        self.last_mark = mark
        if mark > self.peak_price:
            self.peak_price = mark
        g = self.gain_pct(mark)
        if g > self.max_gain_pct:
            self.max_gain_pct = g
        if not self.trailing_armed and g >= self.trail_trigger:
            self.trailing_armed = True

    def trailing_stop_price(self) -> float | None:
        if not self.trailing_armed:
            return None
        return self.peak_price * (1.0 - self.trail_drop / 100.0)

    def next_tp(self) -> dict | None:
        for step in self.ladder:
            if not step["done"]:
                return step
        return None

    def to_dict(self) -> dict:
        tp_next = self.next_tp()
        return {
            "pos_id": self.pos_id,
            "symbol": self.symbol,
            "base": self.base,
            "qty": self.qty,
            "qty_initial": self.qty_initial,
            "entry_price": self.entry_price,
            "entry_ts": self.entry_ts,
            "mode": self.mode,
            "score_at_entry": self.score_at_entry,
            "reasons": self.reasons,
            "sources": self.sources,
            "gain_pct": round(self.gain_pct(), 2),
            "max_gain_pct": round(self.max_gain_pct, 2),
            "value_quote": round(self.value_quote(), 4),
            "peak_price": self.peak_price,
            "trailing_armed": self.trailing_armed,
            "trail_stop_price": round(self.trailing_stop_price(), 8) if self.trailing_stop_price() else None,
            "hard_sl_price": round(self.entry_price * (1 + self.hard_sl / 100.0), 8),
            "next_tp": ({"gain": tp_next["gain"], "sell": tp_next["sell"]} if tp_next else None),
            "ladder": [{"gain": s["gain"], "sell": s["sell"], "done": s["done"]} for s in self.ladder],
            "realized_quote": round(self.realized_quote, 4),
            "new_listing": self.new_listing,
            "mark": self.last_mark,
            "hold_min": round((time.time() - self.entry_ts) / 60.0, 1),
        }
