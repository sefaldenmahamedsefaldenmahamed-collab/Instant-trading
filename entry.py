"""Entry gate — final decision layer before any buy. Every rejection has a human-readable
Arabic reason which is streamed to the dashboard."""
from __future__ import annotations

import time

from app.config import CFG


class EntryGate:
    def __init__(self, store) -> None:
        self.store = store

    async def evaluate(self, candidate: dict, engine) -> tuple[bool, str, dict]:
        """Returns (ok, reason, meta). reason is Arabic; meta carries overrides (e.g. new listing)."""
        sym = candidate["symbol"]
        threshold = CFG.entry_score_threshold + engine.learned.get("entry_threshold_delta", 0.0)

        meta: dict = {"threshold": threshold, "checks": {}}

        # already holding?
        if any(p.symbol == sym for p in engine.positions.values()):
            return False, "نحتفظ بها بالفعل", meta

        # max concurrent trades
        if len(engine.positions) >= CFG.max_concurrent_trades:
            return False, f"وصلنا الحد الأقصى للصفقات المفتوحة ({CFG.max_concurrent_trades})", meta

        # daily cap
        day_start = time.time() - 24 * 3600
        buys = await self.store.buys_today(day_start)
        if buys >= CFG.max_trades_per_day:
            return False, f"بلغنا حد صفقات اليوم ({CFG.max_trades_per_day})", meta

        # liquidity
        qv = float(candidate.get("quote_volume_24h") or 0.0)
        meta["checks"]["liquidity"] = qv
        if qv < CFG.min_quote_volume_24h and not candidate.get("new_listing"):
            return False, f"سيولة ضعيفة ({qv/1e6:.1f}M < {CFG.min_quote_volume_24h/1e6:.0f}M)", meta

        # FOMO guard — never chase a moonshot that already left
        ch24 = float(candidate.get("change_24h") or 0.0)
        fomo_block = CFG.fomo_block_24h_pct + engine.learned.get("fomo_block_delta", 0.0)
        meta["checks"]["change_24h"] = ch24
        if ch24 > fomo_block and not (CFG.new_listing_snipe and candidate.get("new_listing")
                                      and CFG.new_listing_skip_fomo_guard):
            return False, f"درع FOMO: ارتفعت بالفعل {ch24:.0f}% في 24 ساعة — خطر شراء القمة", meta

        # parabolic 1h candle — chasing a vertical candle = buying someone's exit
        m1h = float(candidate.get("mom_1h") or 0.0)
        if m1h > CFG.parabolic_1h_pct and not candidate.get("new_listing"):
            return False, f"شمعة عمودية (+{m1h:.0f}% في ساعة) — ننتظر هبوطاً صحياً", meta

        # book spread (real tradability)
        bt = await engine.client.book_ticker(sym)
        if bt and bt.get("bidPrice") and bt.get("askPrice"):
            bid, ask = float(bt["bidPrice"]), float(bt["askPrice"])
            if bid > 0:
                spread = (ask / bid - 1.0) * 100.0
                meta["checks"]["spread_pct"] = round(spread, 3)
                if spread > CFG.max_book_spread_pct:
                    return False, f"فرق سعر العرض/الطلب واسع ({spread:.2f}%) — سيولة فعلية ضعيفة", meta

        # Fear & Greed behaviour
        fng = engine.fng_ctx or {}
        if fng.get("pause_entries"):
            if candidate.get("score", 0) < 90:
                return False, f"مؤشر الخوف والطمع عند {fng.get('value')} — الخوف الشديد، وقف دخول مؤقت", meta

        # score threshold
        score = float(candidate.get("score") or 0.0)
        if score < threshold:
            return False, f"درجة الزخم {score} < الحد المطلوب {threshold:.0f}", meta

        # all green → overrides for new listings
        if candidate.get("new_listing"):
            meta["allocation_pct"] = CFG.new_listing_allocation_pct
            meta["new_listing"] = True
        return True, "كل الشروط تحققت ✅", meta
