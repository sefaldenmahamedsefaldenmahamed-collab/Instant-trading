"""Exit engine — decides sells per open position:
• TP ladder (partial sells at +100% / +250% / +500% by default)
• Trailing stop-loss that arms at +30% (new listings: +20%) and follows the peak
• Hard stop-loss (default −12%)
• Momentum-weakness exit (score collapse while barely in profit)
Every decision carries an Arabic reason for the live dashboard."""
from __future__ import annotations

import logging
import time

log = logging.getLogger("exit")


class ExitAction:
    def __init__(self, kind: str, frac: float, reason: str) -> None:
        self.kind = kind          # "partial" | "full"
        self.frac = frac          # fraction of remaining qty to sell
        self.reason = reason


def evaluate_exit(pos, mark: float, live_score: float | None, min_notional: float = 5.0) -> ExitAction | None:
    pos.update_mark(mark)
    gain = pos.gain_pct(mark)

    # 1) Hard stop-loss — never let a sniper shot become a disaster
    if gain <= pos.hard_sl:
        return ExitAction("full", 1.0, f"وقف الخسارة الصارم ({gain:.1f}% ≤ {pos.hard_sl:.0f}%)")

    # 2) TP ladder — take profits in steps
    tp = pos.next_tp()
    if tp and gain >= tp["gain"]:
        sell_frac = tp["sell"] / 100.0
        if tp["gain"] >= 500:
            reason = f"🎯 الهدف الثالث تحقق: +{gain:.0f}% — بيع {tp['sell']}% الأخير"
        elif tp["gain"] >= 200:
            reason = f"🎯 الهدف الثاني تحقق: +{gain:.0f}% — بيع {tp['sell']}% إضافي"
        else:
            reason = f"🎯 الهدف الأول تحقق: +{gain:.0f}% — تأمين {tp['sell']}% من الصفقة"
        return ExitAction("partial", sell_frac, reason)

    # 3) Trailing stop — protect the rocket's gains
    stop_price = pos.trailing_stop_price()
    if stop_price is not None and mark <= stop_price:
        give_back = (pos.peak_price / mark - 1.0) * 100.0
        return ExitAction(
            "full", 1.0,
            f"📈 الوقف المتحرك: هبط السعر {give_back:.1f}% من القمة ({pos.peak_price:.8g}) — حماية الأرباح",
        )

    # 4) Momentum weakness — the party is over, leave before the lights go out
    if (live_score is not None and gain >= 0 and gain < 10.0
            and live_score < 40.0 and pos.entry_ts < time.time() - 20 * 60):
        return ExitAction("full", 1.0, f"🧟 انهيار الزخم (الدرجة {live_score:.0f}) دون ربح يُذكر — خروج احترازي")

    return None


def should_merge_to_full(remaining_quote: float, min_notional: float = 5.0) -> bool:
    """If what's left is dust below minNotional, just exit fully."""
    return remaining_quote < min_notional
