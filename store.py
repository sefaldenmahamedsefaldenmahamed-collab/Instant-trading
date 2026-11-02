"""SQLite persistence: events, fills, closed positions, equity curve, adaptive params, watchlist."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            c = self._conn
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    msg TEXT NOT NULL,
                    data TEXT
                );
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    pos_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    quote REAL NOT NULL,
                    fee REAL NOT NULL DEFAULT 0,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS closed_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pos_id TEXT NOT NULL,
                    opened_ts REAL NOT NULL,
                    closed_ts REAL NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    qty_total REAL NOT NULL,
                    avg_entry REAL NOT NULL,
                    exit_avg REAL NOT NULL,
                    realized_quote REAL NOT NULL,
                    realized_pct REAL NOT NULL,
                    max_gain_pct REAL NOT NULL,
                    exit_reason TEXT,
                    entry_score REAL,
                    meta TEXT
                );
                CREATE TABLE IF NOT EXISTS equity (
                    ts REAL NOT NULL,
                    total_quote REAL NOT NULL,
                    balance_quote REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS params (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    source TEXT,
                    added_ts REAL,
                    meta TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_fills_pos ON fills(pos_id);
                """
            )
            self._conn.commit()

    # ── low-level helpers ─────────────────────────────────────────────────
    async def run(self, fn, *args, **kwargs) -> Any:
        def _work():
            with self._lock:
                return fn(*args, **kwargs)

        return await asyncio.to_thread(_work)

    def _now(self) -> float:
        return time.time()

    # ── events ────────────────────────────────────────────────────────────
    def _insert_event(self, ts: float, level: str, category: str, msg: str, data: dict | None) -> None:
        self._conn.execute(
            "INSERT INTO events(ts, level, category, msg, data) VALUES (?,?,?,?,?)",
            (ts, level, category, msg, json.dumps(data, ensure_ascii=False, default=str) if data else None),
        )
        self._conn.commit()

    def _recent_events(self, limit: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, level, category, msg, data FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in reversed(rows):
            out.append(
                {
                    "ts": r["ts"],
                    "level": r["level"],
                    "category": r["category"],
                    "msg": r["msg"],
                    "data": json.loads(r["data"]) if r["data"] else None,
                }
            )
        return out

    async def add_event(self, level: str, category: str, msg: str, data: dict | None = None) -> None:
        await self.run(self._insert_event, self._now(), level, category, msg, data)

    async def events(self, limit: int = 200) -> list[dict]:
        return await self.run(self._recent_events, limit)

    # ── fills / closed positions ──────────────────────────────────────────
    def _insert_fill(self, r: dict) -> None:
        self._conn.execute(
            "INSERT INTO fills(ts,pos_id,mode,symbol,side,qty,price,quote,fee,reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r["ts"], r["pos_id"], r["mode"], r["symbol"], r["side"], r["qty"],
                r["price"], r["quote"], r.get("fee", 0.0), r.get("reason"),
            ),
        )
        self._conn.commit()

    async def add_fill(self, **r) -> None:
        await self.run(self._insert_fill, r)

    def _insert_closed(self, r: dict) -> None:
        self._conn.execute(
            "INSERT INTO closed_positions(pos_id,opened_ts,closed_ts,mode,symbol,qty_total,avg_entry,"
            "exit_avg,realized_quote,realized_pct,max_gain_pct,exit_reason,entry_score,meta) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["pos_id"], r["opened_ts"], r["closed_ts"], r["mode"], r["symbol"], r["qty_total"],
                r["avg_entry"], r["exit_avg"], r["realized_quote"], r["realized_pct"],
                r["max_gain_pct"], r["exit_reason"], r.get("entry_score"),
                json.dumps(r.get("meta") or {}, ensure_ascii=False, default=str),
            ),
        )
        self._conn.commit()

    async def add_closed_position(self, **r) -> None:
        await self.run(self._insert_closed, r)

    def _closed_positions(self, limit: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM closed_positions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) | {"meta": json.loads(r["meta"]) if r["meta"] else {}} for r in rows]

    async def closed_positions(self, limit: int = 100) -> list[dict]:
        return await self.run(self._closed_positions, limit)

    def _stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n, "
            "SUM(CASE WHEN realized_quote > 0 THEN 1 ELSE 0 END) AS wins, "
            "COALESCE(SUM(realized_quote),0) AS total "
            "FROM closed_positions"
        ).fetchone()
        return {"closed": row["n"] or 0, "wins": row["wins"] or 0, "realized_total": row["total"] or 0.0}

    async def stats(self) -> dict:
        return await self.run(self._stats)

    # ── equity ────────────────────────────────────────────────────────────
    def _insert_equity(self, ts: float, total: float, balance: float) -> None:
        self._conn.execute("INSERT INTO equity(ts,total_quote,balance_quote) VALUES (?,?,?)", (ts, total, balance))
        self._conn.execute("DELETE FROM equity WHERE ts < (SELECT MIN(ts) FROM (SELECT ts FROM equity ORDER BY ts DESC LIMIT 2000))")
        self._conn.commit()

    def _equity_history(self, limit: int) -> list[dict]:
        rows = self._conn.execute("SELECT ts, total_quote, balance_quote FROM equity ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"ts": r["ts"], "total": r["total_quote"], "balance": r["balance_quote"]} for r in reversed(rows)]

    async def add_equity(self, total: float, balance: float) -> None:
        await self.run(self._insert_equity, self._now(), total, balance)

    async def equity_history(self, limit: int = 300) -> list[dict]:
        return await self.run(self._equity_history, limit)

    # ── adaptive params (autopsy) ─────────────────────────────────────────
    def _get_param(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM params WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    def _set_param(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO params(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )
        self._conn.commit()

    async def get_param(self, key: str, default: Any = None) -> Any:
        return await self.run(self._get_param, key, default)

    async def set_param(self, key: str, value: Any) -> None:
        await self.run(self._set_param, key, value)

    # ── watchlist (announced, not yet trading) ────────────────────────────
    def _watch_upsert(self, symbol: str, source: str, meta: dict | None) -> None:
        self._conn.execute(
            "INSERT INTO watchlist(symbol,source,added_ts,meta) VALUES (?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET source=excluded.source, meta=excluded.meta",
            (symbol, source, self._now(), json.dumps(meta or {}, ensure_ascii=False, default=str)),
        )
        self._conn.commit()

    def _watch_remove(self, symbol: str) -> None:
        self._conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
        self._conn.commit()

    def _watch_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT symbol, source, added_ts, meta FROM watchlist ORDER BY added_ts DESC").fetchall()
        return [dict(r) | {"meta": json.loads(r["meta"]) if r["meta"] else {}} for r in rows]

    async def watch_upsert(self, symbol: str, source: str, meta: dict | None = None) -> None:
        await self.run(self._watch_upsert, symbol, source, meta)

    async def watch_remove(self, symbol: str) -> None:
        await self.run(self._watch_remove, symbol)

    async def watch_all(self) -> list[dict]:
        return await self.run(self._watch_all)

    def _fills_today(self, day_start: float) -> int:
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT pos_id) AS n FROM fills WHERE side='BUY' AND ts>=?", (day_start,)
        ).fetchone()
        return row["n"] or 0

    async def buys_today(self, day_start: float) -> int:
        return await self.run(self._fills_today, day_start)

    async def close(self) -> None:
        def _c():
            with self._lock:
                self._conn.close()
        await asyncio.to_thread(_c)
