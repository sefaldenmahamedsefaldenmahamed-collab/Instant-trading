"""Trade Autopsy — after every closed trade the bot writes a post-mortem report and
adapts its own parameters within hard bounds. All adjustments are streamed to the dashboard
so the "learning" is fully transparent (no black box)."""
from __future__ import annotations

import time

BOUNDS = {
    "entry_threshold_delta": (-4.0, +6.0),
    "trail_drop_delta": (-5.0, +2.0),
    "fomo_block_delta": (0.0, +15.0),
}


def _clamp_key(key: str, val: float) -> float:
    lo, hi = BOUNDS.get(key, (-100.0, 100.0))
    return max(lo, min(hi, val))


class Autopsy:
    """Keeps counters in the params table so learnings survive restarts."""

    def __init__(self, store) -> None:
        self.store = store

    async def _counter(self, key: str, reset: bool = False) -> int:
        v = await self.store.get_param(f"autopsy_{key}", 0)
        v = int(v or 0)
        return 0 if reset else v

    async def _bump(self, key: str, by: int = 1, reset: bool = False) -> int:
        v = 0 if reset else await self._counter(key)
        v += by
        await self.store.set_param(f"autopsy_{key}", v)
        return v

    async def review(self, engine, pos, closed: dict) -> None:
        """Analyze a closed position and adjust strategy parameters (bounded)."""
        if not engine.cfg.autopsy_learning:
            return
        learned = engine.learned
        changes: list[str] = []
        exit_reason = (closed.get("exit_reason") or "")
        pnl_pct = float(closed.get("realized_pct") or 0.0)
        max_gain = float(closed.get("max_gain_pct") or 0.0)
        hold_min = (closed.get("closed_ts", 0) - closed.get("opened_ts", 0)) / 60.0

        # give-back ratio: how much of the peak we surrendered
        give_back = (max_gain - pnl_pct) if pnl_pct > 0 else 0.0

        # 1) Quick stop-outs → the entry bar was too low
        if "وقف الخسارة" in exit_reason and hold_min < 45 and max_gain < 4.0:
            n = await self._bump("fast_sl_streak")
            if n >= 3:
                old = learned.get("entry_threshold_delta", 0.0)
                learned["entry_threshold_delta"] = _clamp_key("entry_threshold_delta", old + 2.0)
                changes.append(f"ثلاث صفقات قُطعت سريعاً → رفع حد الدخول +2 (الآن {learned['entry_threshold_delta']:+.0f})")
                await self._bump("fast_sl_streak", reset=True)
        elif pnl_pct > 0:
            await self._bump("fast_sl_streak", reset=True)

        # 2) Big round-trips → trailing is too loose
        if give_back > 35.0:
            n = await self._bump("giveback_streak")
            if n >= 2:
                old = learned.get("trail_drop_delta", 0.0)
                learned["trail_drop_delta"] = _clamp_key("trail_drop_delta", old - 1.0)
                changes.append(f"فقدنا {give_back:.0f}% من القمة مرتين → شدّ الترailing −1 (الآن {learned['trail_drop_delta']:+.0f})")
                await self._bump("giveback_streak", reset=True)
        elif pnl_pct > 50:
            await self._bump("giveback_streak", reset=True)

        # 3) Winning streak → allow slightly braver entries
        if pnl_pct > 60:
            n = await self._bump("win_streak")
            if n >= 3:
                old = learned.get("entry_threshold_delta", 0.0)
                learned["entry_threshold_delta"] = _clamp_key("entry_threshold_delta", old - 1.0)
                changes.append(f"ثلاث أرباح متتالية 🎉 → تخفيف حد الدخول −1 (الآن {learned['entry_threshold_delta']:+.0f})")
                await self._bump("win_streak", reset=True)
        else:
            await self._bump("win_streak", reset=True)

        # 4) Repeated FOMO-blocked entries that instantly died → raise the FOMO wall
        if pnl_pct < -8.0 and float(closed.get("meta", {}).get("change_24h_at_entry", 0) or 0) > 40:
            old = learned.get("fomo_block_delta", 0.0)
            learned["fomo_block_delta"] = _clamp_key("fomo_block_delta", old + 3.0)
            changes.append(f"دخلنا متأخرين على عملة ساخنة وخسرنا → رفع درع FOMO +3 (الآن +{learned['fomo_block_delta']:.0f})")

        await self.store.set_param("learned", learned)

        # report
        verdict = "مربحة ✅" if pnl_pct > 0 else "خاسرة ❌"
        report = (
            f"🔬 تشريح الصفقة {pos.symbol}: {verdict} ({pnl_pct:+.1f}%، القمة {max_gain:+.1f}%، "
            f"مدة {hold_min:.0f} دقيقة، السبب: {exit_reason})"
        )
        await engine.emit("autopsy", "autopsy", report, {"closed": closed, "learned": learned})
        for ch in changes:
            await engine.emit("autopsy", "autopsy", f"🧠 تعلم ذاتي: {ch}", {"learned": learned})
