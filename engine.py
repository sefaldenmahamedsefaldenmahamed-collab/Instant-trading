"""Engine — the orchestrator. Owns the event loop tasks:
  • market scan (every SCAN_INTERVAL_SEC)
  • external discovery (every EXTERNAL_SCAN_INTERVAL_SEC)
  • Fear & Greed (every FNG_INTERVAL_SEC)
  • exit monitor (every EXIT_CHECK_INTERVAL_SEC)
  • new-listings watcher (every 60s)
  • equity snapshots (every 60s)
and the buy/sell execution pipeline. Everything it does is emitted as events
to the store (persistence) and broadcaster (live dashboard).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp

from app.config import CFG
from app.exchange.binance_client import BinanceClient
from app.modes.live_broker import LiveBroker
from app.modes.paper_broker import PaperBroker
from app.scanner import external_discovery as ext
from app.scanner import market_scanner as mscan
from app.scanner.new_listings import NewListingsWatcher
from app.state.broadcaster import Broadcaster
from app.state.store import Store
from app.strategy.autopsy import Autopsy
from app.strategy.entry import EntryGate
from app.strategy.exit_engine import evaluate_exit
from app.strategy.momentum_score import score_candidate
from app.trading.position import Position

log = logging.getLogger("engine")


class Engine:
    def __init__(self, store: Store) -> None:
        self.cfg = CFG
        self.store = store
        self.bc = Broadcaster()
        self.client = None            # BinanceClient, started in start()
        self.broker = None
        self.session: aiohttp.ClientSession | None = None
        self.gate = EntryGate(store)
        self.autopsy = Autopsy(store)
        self.watcher = NewListingsWatcher(store)

        # live state
        self.prices: dict[str, float] = {}
        self.candidates: list[dict] = []
        self.external_signals: dict = {}
        self.fng: dict | None = None
        self.fng_ctx: dict = ext.fng_context(None)
        self.positions: dict[str, Position] = {}   # pos_id → Position
        self.learned: dict = {"entry_threshold_delta": 0.0, "trail_drop_delta": 0.0, "fomo_block_delta": 0.0}
        self.started_ts = time.time()
        self.last_scan_ts: float = 0.0
        self.last_external_ts: float = 0.0
        self.status = "starting"
        self._tasks: list[asyncio.Task] = []
        self._recent_rejections: list[dict] = []

    # ── events ────────────────────────────────────────────────────────────
    async def emit(self, level: str, category: str, msg: str, data: dict | None = None) -> None:
        await self.store.add_event(level, category, msg, data)
        self.bc.send_nowait({"type": "event", "ts": time.time(), "level": level,
                             "category": category, "msg": msg, "data": data})

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def start(self) -> None:
        errs = self.cfg.validate()
        if errs:
            self.status = "config-error"
            for e in errs:
                await self.emit("danger", "system", f"⛔ خطأ إعداد: {e}")
            raise RuntimeError("; ".join(errs))

        self.client = BinanceClient()
        await self.client.start()
        self.session = aiohttp.ClientSession()
        self.status = "running"

        if self.cfg.mode == "paper":
            self.broker = PaperBroker(self._price_provider)
            await self.emit("info", "system",
                            f"🚀 انطلق البوت في وضع المحاكاة (Paper) برأس مال {self.cfg.paper_start_balance} USDT — أسعار Binance حية، أموال وهمية")
        else:
            self.broker = LiveBroker(self.client)
            await self.emit("warn", "system",
                            f"🔥 انطلق البوت في وضع {self.cfg.mode.upper()} — أوامر حقيقية عبر Binance!")

        saved = await self.store.get_param("learned")
        if isinstance(saved, dict):
            self.learned = saved
        await self.client.sync_time()
        try:
            ex = await self.client.exchange_info()
            self.watcher.prime(set(ex.keys()))
            await self.emit("info", "system", f"📡 تم تحميل معلومات المنصة: {len(ex)} رمز مُدرج")
        except Exception as e:
            await self.emit("danger", "system", f"⚠️ فشل تحميل exchangeInfo: {e}")

        self._tasks = [
            asyncio.create_task(self._loop(self._market_loop, "market", self.cfg.scan_interval_sec)),
            asyncio.create_task(self._loop(self._exit_loop, "exit", self.cfg.exit_check_interval_sec, run_now=True)),
            asyncio.create_task(self._loop(self._external_loop, "external", self.cfg.external_scan_interval_sec, run_now=True)),
            asyncio.create_task(self._loop(self._fng_loop, "fng", self.cfg.fng_interval_sec, run_now=True)),
            asyncio.create_task(self._loop(self._listings_loop, "listings", 60)),
            asyncio.create_task(self._loop(self._equity_loop, "equity", 60)),
        ]

    async def stop(self) -> None:
        self.status = "stopping"
        for t in self._tasks:
            t.cancel()
        if self.session:
            await self.session.close()
        if self.client:
            await self.client.close()
        self.status = "stopped"

    async def _loop(self, coro_fn, name: str, interval: int, run_now: bool = False) -> None:
        if not run_now:
            await asyncio.sleep(3)
        while True:
            try:
                await coro_fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("loop %s crashed", name)
                await self.emit("danger", "system", f"⛔ حلقة {name} توقفت بخطأ: {e}")
                await asyncio.sleep(10)
            await asyncio.sleep(interval)

    # ── price provider (paper broker) ─────────────────────────────────────
    async def _price_provider(self, symbol: str) -> float | None:
        p = self.prices.get(symbol)
        if p:
            return p
        try:
            t = await self.client.tickers([symbol])
            return float(t[symbol]["lastPrice"])
        except Exception:
            return None

    # ── market scan + entries ─────────────────────────────────────────────
    async def _market_loop(self) -> None:
        t0 = time.time()
        cands = await mscan.scan(self.client)
        await self._inject_external(cands)
        # merge external signals into candidates
        self._apply_external(cands)
        # score everything
        penalty = self.fng_ctx.get("score_penalty", 0.0)
        for c in cands:
            c["score"], c["breakdown"] = score_candidate(c, fng_penalty=penalty)
        cands.sort(key=lambda c: c["score"], reverse=True)
        self.candidates = cands[:25]
        self.last_scan_ts = time.time()

        # update prices map for held symbols + candidates
        for c in self.candidates:
            if c.get("price"):
                self.prices[c["symbol"]] = c["price"]

        await self.emit("info", "scanner",
                        f"🔍 فحص السوق: {len(cands)} مرشح — الأعلى: "
                        + ", ".join(f"{c['base']} {c['score']:.0f}" for c in cands[:3]),
                        {"top": [{"symbol": c["symbol"], "score": c["score"]} for c in cands[:5]]})

        dur = time.time() - t0
        log.info("market scan done in %.1fs (%d candidates)", dur, len(cands))
        await self._maybe_enter()

    def _apply_external(self, cands: list[dict]) -> None:
        ext_sig = self.external_signals
        if not ext_sig:
            return
        trending = ext_sig.get("trending", {})
        movers = ext_sig.get("movers", {})
        boosts = ext_sig.get("boosts", {})
        for c in cands:
            base = c.get("base", "")
            if base in trending:
                c["sources"].append("coingecko_trending")
            if base in movers and abs(movers[base]) >= 10:
                c["sources"].append("coingecko_mover")
            boost = boosts.get(base, 0.0)
            c["social_boost"] = max(c.get("social_boost", 0.0), boost)

    async def _inject_external(self, cands: list[dict]) -> None:
        """Coins trending OUTSIDE Binance that don't appear in top gainers yet get pulled in —
        this is the whole point of external discovery (catch it before the crowd)."""
        ext_sig = self.external_signals
        if not ext_sig or not cands:
            return
        have = {c["symbol"] for c in cands}
        trending = ext_sig.get("trending", {})
        wanted: list[tuple[str, str]] = []
        for base, rank in trending.items():
            sym = f"{base}{self.cfg.quote_asset}"
            if sym not in have and self.client.is_spot_usdt(sym):
                wanted.append((sym, base))
        if not wanted:
            return
        try:
            tickers = await self.client.tickers([s for s, _ in wanted[:10]])
        except Exception:
            return
        for sym, base in wanted[:10]:
            t = tickers.get(sym)
            if not t:
                continue
            c = {
                "symbol": sym, "base": base,
                "price": float(t.get("lastPrice", 0) or 0),
                "change_24h": float(t.get("priceChangePercent", 0) or 0),
                "quote_volume_24h": float(t.get("quoteVolume", 0) or 0),
                "trades_24h": int(t.get("count", 0) or 0),
                "spike_5m": 0.0, "mom_5m": 0.0, "mom_15m": 0.0, "mom_1h": 0.0, "mom_4h": 0.0,
                "rsi_15m": None, "buy_pressure": 0.5,
                "sources": ["coingecko_trending"], "social_boost": 0.5,
                "new_listing": False, "listed_at": None, "ts": time.time(),
            }
            dd = await mscan.deep_dive(self.client, sym)
            c.update(dd)
            cands.append(c)
            await self.emit("info", "external", f"🌐 {base} متصدّر الترند خارج Binance — أُضيف لقائمة الفحص العميق")

    async def _maybe_enter(self) -> None:
        for c in self.candidates[:8]:
            ok, reason, meta = await self.gate.evaluate(c, self)
            if ok:
                await self._execute_entry(c, meta)
            elif c["score"] >= self.cfg.entry_score_threshold - 15:
                self._remember_rejection(c, reason)

    def _remember_rejection(self, c: dict, reason: str) -> None:
        self._recent_rejections = (self._recent_rejections or [])[-19:] + [
            {"symbol": c["symbol"], "base": c["base"], "score": c["score"], "reason": reason, "ts": time.time()}
        ]

    async def _execute_entry(self, c: dict, meta: dict) -> None:
        sym, base = c["symbol"], c["base"]
        try:
            if isinstance(self.broker, PaperBroker):
                usdt_free = self.broker.usdt_free
            else:
                usdt_free = await self.broker.usdt_free()
            alloc_pct = meta.get("allocation_pct", self.cfg.allocation_pct)
            quote_amount = round(usdt_free * alloc_pct / 100.0, 2)
            if quote_amount < self.cfg.min_notional_usdt:
                await self.emit("warn", "entry", f"💸 الرصيد غير كافٍ لفتح صفقة جديدة على {sym} (المطلوب ≥ {self.cfg.min_notional_usdt} USDT)")
                return

            fill = await self.broker.buy_market(sym, quote_amount)
            if not fill.get("price") or not fill.get("qty"):
                raise ValueError(f"تنفيذ الشراء فشل: {fill}")

            pos = Position(
                symbol=sym, base=base, qty=fill["qty"], qty_initial=fill["qty"],
                entry_price=fill["price"], entry_ts=fill["ts"] or time.time(),
                mode=self.broker.mode, score_at_entry=c["score"],
                reasons=[r for r in c.get("sources", []) if r != "binance"] or ["زخم سعري وحجم"],
                sources=c.get("sources", []),
                new_listing=meta.get("new_listing", False),
            )
            if meta.get("new_listing"):
                pos.trail_trigger = self.cfg.new_listing_trail_trigger
            self.positions[pos.pos_id] = pos
            self.prices[sym] = fill["price"]

            await self.store.add_fill(
                ts=fill["ts"] or time.time(), pos_id=pos.pos_id, mode=self.broker.mode,
                symbol=sym, side="BUY", qty=fill["qty"], price=fill["price"],
                quote=fill["quote"], fee=fill.get("fee", 0.0), reason="entry",
            )
            src_txt = "، ".join(pos.reasons)
            await self.emit(
                "success", "entry",
                f"🟢 شراء {base} — درجة الزخم {c['score']:.0f}/100 | السعر {fill['price']:.8g} | "
                f"الكمية {fill['qty']:.6g} | القيمة {fill['quote']:.2f} USDT | السبب: {src_txt}",
                {"candidate": {k: c.get(k) for k in ("symbol", "base", "price", "score", "change_24h", "spike_5m", "sources")},
                 "breakdown": c.get("breakdown"), "fill": fill},
            )
        except Exception as e:
            await self.emit("danger", "entry", f"⛔ فشل تنفيذ شراء {sym}: {e}")

    # ── exit monitor ──────────────────────────────────────────────────────
    async def _exit_loop(self) -> None:
        if not self.positions:
            return
        held = [p.symbol for p in self.positions.values()]
        try:
            tickers = await self.client.tickers(held)
        except Exception as e:
            log.debug("exit tickers failed: %s", e)
            return
        live_scores = {c["symbol"]: c["score"] for c in self.candidates}
        for pos in list(self.positions.values()):
            t = tickers.get(pos.symbol)
            if not t:
                continue
            mark = float(t["lastPrice"])
            self.prices[pos.symbol] = mark
            score = live_scores.get(pos.symbol)
            action = evaluate_exit(pos, mark, score, self.cfg.min_notional_usdt)
            if action:
                await self._execute_exit(pos, action)

    async def _execute_exit(self, pos: Position, action) -> None:
        sym = pos.symbol
        try:
            if action.kind == "partial":
                sell_qty = pos.qty * action.frac
                # if remaining after partial would be dust → sell everything
                remaining_val = (pos.qty - sell_qty) * (self.prices.get(sym) or pos.last_mark)
                if remaining_val < self.cfg.min_notional_usdt:
                    action.kind, action.frac, action.reason = "full", 1.0, action.reason + " (تبقّى أقل من الحد الأدنى → بيع كامل)"
                    sell_qty = pos.qty
            else:
                sell_qty = pos.qty

            fill = await self.broker.sell_market(sym, sell_qty)
            pos.qty -= fill["qty"]
            realized = fill["quote"] - fill["fee"] - (fill["qty"] * pos.entry_price)
            pos.realized_quote += realized
            pos.fees_paid += fill.get("fee", 0.0)

            await self.store.add_fill(
                ts=fill["ts"] or time.time(), pos_id=pos.pos_id, mode=pos.mode,
                symbol=sym, side="SELL", qty=fill["qty"], price=fill["price"],
                quote=fill["quote"], fee=fill.get("fee", 0.0), reason=action.reason,
            )
            pnl_txt = f"{(fill['price'] / pos.entry_price - 1) * 100:+.1f}%"
            await self.emit(
                "success" if pos.gain_pct(fill['price']) >= 0 else "warn", "exit",
                f"🔴 بيع {pos.base} ({fill['qty']:.6g}) بسعر {fill['price']:.8g} — {pnl_txt} | {action.reason}",
                {"pos_id": pos.pos_id, "fill": fill, "reason": action.reason},
            )

            if action.kind == "partial" and pos.qty > 0:
                tp = pos.next_tp()
                if tp:
                    tp["done"] = True
                await self.emit("info", "exit", f"✂️ متبقٍ من {pos.base}: {pos.qty:.6g} — الترailing والهدف التالي يعملان")
            else:
                await self._close_position(pos)
        except Exception as e:
            await self.emit("danger", "exit", f"⛔ فشل تنفيذ بيع {sym}: {e}")

    async def _close_position(self, pos: Position) -> None:
        self.positions.pop(pos.pos_id, None)
        closed = {
            "pos_id": pos.pos_id,
            "opened_ts": pos.entry_ts,
            "closed_ts": time.time(),
            "mode": pos.mode,
            "symbol": pos.symbol,
            "qty_total": pos.qty_initial,
            "avg_entry": pos.entry_price,
            "exit_avg": None,  # computed below from the actual SELL fills
            "realized_quote": pos.realized_quote,
            "realized_pct": round(pos.realized_quote / max(pos.qty_initial * pos.entry_price, 1e-9) * 100.0, 2),
            "max_gain_pct": pos.max_gain_pct,
            "exit_reason": "إغلاق كامل",
            "entry_score": pos.score_at_entry,
            "meta": {"change_24h_at_entry": None, "sources": pos.sources},
        }
        # compute weighted exit average from fills
        try:
            fills = await self.store.run(
                lambda: [dict(r) for r in self.store._conn.execute(
                    "SELECT side, qty, price FROM fills WHERE pos_id=? AND side='SELL'", (pos.pos_id,)).fetchall()]
            )
            sold_q = sum(f["qty"] for f in fills)
            closed["exit_avg"] = (sum(f["qty"] * f["price"] for f in fills) / sold_q) if sold_q > 0 else pos.last_mark
        except Exception:
            closed["exit_avg"] = pos.last_mark
        await self.store.add_closed_position(**closed)
        emoji = "💰" if pos.realized_quote >= 0 else "🩸"
        await self.emit(
            "success" if pos.realized_quote >= 0 else "danger", "exit",
            f"{emoji} أُغلقت صفقة {pos.base} بالكامل — صافي النتيجة {pos.realized_quote:+.2f} USDT "
            f"({closed['realized_pct']:+.1f}%) | أعلى قمة: +{pos.max_gain_pct:.1f}%",
            {"closed": closed},
        )
        await self.autopsy.review(self, pos, closed)

    # ── external loop ─────────────────────────────────────────────────────
    async def _external_loop(self) -> None:
        try:
            self.external_signals = await ext.collect_external(self.session)
            self.last_external_ts = time.time()
            tr = self.external_signals.get("trending", {})
            if tr:
                top3 = ", ".join(list(tr)[:3])
                await self.emit("info", "external", f"🌐 مصادر خارجية: صعدت للترند {top3} — سيتم فحصها ضد Binance")
        except Exception as e:
            log.debug("external loop error: %s", e)

    async def _fng_loop(self) -> None:
        self.fng = await ext.fear_greed(self.session)
        self.fng_ctx = ext.fng_context(self.fng)
        if self.fng:
            v = self.fng["value"]
            label = self.fng_ctx["label"]
            if v >= self.cfg.fng_greed_threshold:
                msg = f"😨🔥 الخوف والطمع = {v} ({label}) — طمع شديد في السوق: رفعنا سقف الدخول (+{self.fng_ctx['score_penalty']:.0f}) لهذا السبب"
            elif self.fng_ctx.get("pause_entries"):
                msg = f"🥶 الخوف والطمع = {v} ({label}) — خوف شديد: تجميد الدخول مؤقتاً حمايةً من الانهيار الجماعي"
            else:
                msg = f"😐 الخوف والطمع = {v} ({label}) — ظروف طبيعية"
            await self.emit("info", "external", msg, self.fng)

    # ── new listings ──────────────────────────────────────────────────────
    async def _listings_loop(self) -> None:
        # 1) official: exchangeInfo diff
        fresh = await self.watcher.check_exchange_diff(self.client)
        for sym in fresh:
            base = sym.replace(self.cfg.quote_asset, "")
            await self.emit("sniper", "external", f"🚨 إدراج جديد على Binance: {sym} فتح التداول للتو!", {"symbol": sym})
            if self.cfg.new_listing_snipe:
                c = await self._snipe_candidate(sym, base, source="exchangeInfo")
                await self._try_snipe(c)

        # 2) best-effort announcements → watchlist
        try:
            for a in await self.watcher.scan_announcements(self.session):
                sym = self.watcher.ticker_to_symbol(a["ticker"])
                if sym:
                    await self.store.watch_upsert(sym, "announcement", a)
                    await self.emit("sniper", "external",
                                    f"📢 إعلان إدراج: سيسرد {a['name']} ({a['ticker']}) — على الرادار، سيُقنص لحظة فتح التداول", a)
                else:
                    await self.store.watch_upsert(f"{a['ticker']}{self.cfg.quote_asset}", "announcement-pending", a)
        except Exception as e:
            log.debug("announcements loop: %s", e)

    async def _snipe_candidate(self, sym: str, base: str, source: str) -> dict:
        dd = await mscan.deep_dive(self.client, sym)
        t = (await self.client.tickers([sym])).get(sym, {})
        c = {
            "symbol": sym, "base": base,
            "price": float(t.get("lastPrice", 0) or 0),
            "change_24h": float(t.get("priceChangePercent", 0) or 0),
            "quote_volume_24h": float(t.get("quoteVolume", 0) or 0),
            "trades_24h": int(t.get("count", 0) or 0),
            "sources": ["new_listing", source], "social_boost": 0.5,
            "new_listing": True, "listed_at": time.time(), "ts": time.time(),
        }
        c.update(dd)
        score, breakdown = score_candidate(c, extra={"new_listing": {"value": "🚀 إدراج جديد", "weight": 0, "grade": 1.0}})
        c["score"], c["breakdown"] = score, breakdown
        return c

    async def _try_snipe(self, c: dict) -> None:
        ok, reason, meta = await self.gate.evaluate(c, self)
        if ok:
            await self.emit("sniper", "entry", f"🎯 قنص إدراج جديد: {c['base']} — تنفيذ فوري!", {"candidate": c})
            await self._execute_entry(c, meta)
        else:
            await self.emit("warn", "entry", f"🎯❌ قنص {c.get('base')} لم يتحقق: {reason}")

    # ── equity ────────────────────────────────────────────────────────────
    async def _equity_loop(self) -> None:
        if isinstance(self.broker, PaperBroker):
            bal = self.broker.usdt_free
        else:
            try:
                bal = await self.broker.usdt_free()
            except Exception:
                return
        held_value = sum(p.value_quote(self.prices.get(p.symbol, p.last_mark)) for p in self.positions.values())
        total = bal + held_value
        await self.store.add_equity(total, bal)

    # ── snapshot for API/WS ───────────────────────────────────────────────
    async def snapshot(self) -> dict:
        if isinstance(self.broker, PaperBroker):
            bal = self.broker.usdt_free
            mode_label = "paper"
        elif self.broker:
            try:
                bal = await self.broker.usdt_free()
            except Exception:
                bal = None
            mode_label = self.broker.mode
        else:
            bal, mode_label = None, self.status

        held_value = sum(p.value_quote(self.prices.get(p.symbol, p.last_mark)) for p in self.positions.values())
        stats = await self.store.stats()
        equity = await self.store.equity_history(160)
        events = await self.store.events(120)
        closed = await self.store.closed_positions(40)
        watch = await self.store.watch_all()

        return {
            "ts": time.time(),
            "now": datetime.now(timezone.utc).isoformat(),
            "status": self.status,
            "mode": mode_label,
            "uptime_sec": round(time.time() - self.started_ts),
            "balance_quote": bal,
            "held_value": round(held_value, 4),
            "equity_total": round((bal or 0) + held_value, 4),
            "start_balance": self.cfg.paper_start_balance if mode_label == "paper" else None,
            "positions": [p.to_dict() for p in self.positions.values()],
            "candidates": [
                {"symbol": c["symbol"], "base": c["base"], "price": c.get("price"),
                 "change_24h": c.get("change_24h"), "score": c.get("score"),
                 "spike_5m": c.get("spike_5m"), "mom_1h": c.get("mom_1h"),
                 "rsi_15m": c.get("rsi_15m"), "quote_volume_24h": c.get("quote_volume_24h"),
                 "sources": c.get("sources"), "new_listing": c.get("new_listing", False),
                 "breakdown": c.get("breakdown")}
                for c in self.candidates[:15]
            ],
            "rejections": self._recent_rejections[-10:],
            "fng": self.fng,
            "fng_ctx": self.fng_ctx,
            "watchlist": watch,
            "learned": self.learned,
            "stats": stats | {"open": len(self.positions)},
            "equity_curve": equity,
            "events": events,
            "closed_positions": closed,
            "config": {
                "mode": self.cfg.mode, "scan_sec": self.cfg.scan_interval_sec,
                "entry_threshold": self.cfg.entry_score_threshold + self.learned.get("entry_threshold_delta", 0.0),
                "allocation_pct": self.cfg.allocation_pct,
                "max_concurrent": self.cfg.max_concurrent_trades,
                "max_per_day": self.cfg.max_trades_per_day,
                "hard_sl": self.cfg.hard_stop_loss_pct,
                "tp_ladder": self.cfg.tp_ladder,
                "trail_trigger": self.cfg.trail_trigger_pct, "trail_drop": self.cfg.trail_drop_pct,
                "fomo_block": self.cfg.fomo_block_24h_pct + self.learned.get("fomo_block_delta", 0.0),
                "min_volume": self.cfg.min_quote_volume_24h,
                "sniper_on": self.cfg.new_listing_snipe, "autopsy_on": self.cfg.autopsy_learning,
            },
        }
