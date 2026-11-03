"""
Momentum Sniper — Configuration
All settings are read from environment variables (with sane defaults).
See .env.example for the full documented list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional .env loader
    from dotenv import load_dotenv

    _ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except Exception:  # pragma: no cover
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(_env(key, str(default))))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key, str(default)).lower()
    return raw in ("1", "true", "yes", "on", "y")


@dataclass
class Settings:
    # ── Core ──────────────────────────────────────────────────────────────
    mode: str = _env("MODE", "paper").lower()              # paper | testnet | live
    host: str = _env("HOST", "0.0.0.0")
    port: int = _env_int("PORT", 8000)
    log_level: str = _env("LOG_LEVEL", "INFO").upper()
    db_path: str = _env("DB_PATH", "data/bot.db")
    timezone_offset_hours: float = _env_float("TZ_OFFSET_HOURS", 0.0)

    # ── Binance ───────────────────────────────────────────────────────────
    binance_api_base: str = _env("BINANCE_API_BASE", "https://api.binance.com")
    binance_testnet_base: str = _env("BINANCE_TESTNET_BASE", "https://testnet.binance.vision")
    binance_announce_base: str = _env("BINANCE_ANNOUNCE_BASE", "https://www.binance.com")
    api_key: str = _env("BINANCE_API_KEY", "")
    api_secret: str = _env("BINANCE_API_SECRET", "")
    recv_window: int = _env_int("RECV_WINDOW", 5000)
    quote_asset: str = _env("QUOTE_ASSET", "USDT").upper()

    # ── Portfolio & risk ──────────────────────────────────────────────────
    paper_start_balance: float = _env_float("PAPER_START_BALANCE", 100.0)
    allocation_pct: float = _env_float("TRADE_ALLOCATION_PCT", 10.0)      # % of free USDT per trade
    max_concurrent_trades: int = _env_int("MAX_CONCURRENT_TRADES", 3)
    max_trades_per_day: int = _env_int("MAX_TRADES_PER_DAY", 6)
    hard_stop_loss_pct: float = _env_float("HARD_STOP_LOSS_PCT", -12.0)   # e.g. -12 → -12%
    fee_pct: float = _env_float("FEE_PCT", 0.1)                           # taker fee (paper)
    slippage_pct: float = _env_float("PAPER_SLIPPAGE_PCT", 0.15)          # paper fill slippage
    min_notional_usdt: float = _env_float("MIN_NOTIONAL_USDT", 5.0)

    # TP ladder: "gain%:sell%,gain%:sell%,..."  e.g. +100% → sell 30%
    tp_ladder_raw: str = _env("TP_LADDER", "100:30,250:30,500:40")
    trail_trigger_pct: float = _env_float("TRAIL_TRIGGER_PCT", 30.0)      # arm trailing at +30%
    trail_drop_pct: float = _env_float("TRAIL_DROP_PCT", 15.0)            # sell if price drops 15% off peak
    momentum_exit_score: float = _env_float("MOMENTUM_EXIT_SCORE", 40.0)  # weakness exit level
    momentum_exit_max_gain: float = _env_float("MOMENTUM_EXIT_MAX_GAIN", 10.0)

    # ── Scanner & strategy ────────────────────────────────────────────────
    scan_interval_sec: int = _env_int("SCAN_INTERVAL_SEC", 60)
    exit_check_interval_sec: int = _env_int("EXIT_CHECK_INTERVAL_SEC", 10)
    external_scan_interval_sec: int = _env_int("EXTERNAL_SCAN_INTERVAL_SEC", 300)
    entry_score_threshold: float = _env_float("ENTRY_SCORE_THRESHOLD", 78.0)
    min_quote_volume_24h: float = _env_float("MIN_QUOTE_VOLUME_24H", 2_000_000.0)
    fomo_block_24h_pct: float = _env_float("FOMO_BLOCK_24H_PCT", 80.0)    # skip if already up more
    parabolic_1h_pct: float = _env_float("PARABOLIC_1H_PCT", 45.0)        # skip crazy 1h candles
    max_book_spread_pct: float = _env_float("MAX_BOOK_SPREAD_PCT", 1.0)
    deep_dive_top_n: int = _env_int("DEEP_DIVE_TOP_N", 20)

    # ── External discovery ────────────────────────────────────────────────
    coingecko_base: str = _env("COINGECKO_BASE", "https://api.coingecko.com/api/v3")
    fng_base: str = _env("FNG_BASE", "https://api.alternative.me/fng/")
    reddit_enabled: bool = _env_bool("REDDIT_ENABLED", True)
    reddit_base: str = _env("REDDIT_BASE", "https://www.reddit.com")
    reddit_subreddits: str = _env("REDDIT_SUBREDDITS", "CryptoCurrency,savememecoins,MemeEconomy")
    x_bearer_token: str = _env("X_BEARER_TOKEN", "")                      # optional (paid API)
    fng_interval_sec: int = _env_int("FNG_INTERVAL_SEC", 1800)

    # ── Crazy features ────────────────────────────────────────────────────
    new_listing_snipe: bool = _env_bool("NEW_LISTING_SNIPE", True)
    new_listing_catalog_id: str = _env("NEW_LISTING_CATALOG_ID", "48")
    new_listing_max_age_hours: float = _env_float("NEW_LISTING_MAX_AGE_HOURS", 24.0)
    new_listing_allocation_pct: float = _env_float("NEW_LISTING_ALLOCATION_PCT", 5.0)
    new_listing_skip_fomo_guard: bool = _env_bool("NEW_LISTING_SKIP_FOMO_GUARD", True)
    new_listing_trail_trigger: float = _env_float("NEW_LISTING_TRAIL_TRIGGER", 20.0)

    autopsy_learning: bool = _env_bool("AUTOPSY_LEARNING", True)

    # Fear & Greed behaviour: extreme greed → raise entry bar; extreme fear → pause entries
    fng_greed_threshold: int = _env_int("FNG_GREED_THRESHOLD", 80)
    fng_fear_threshold: int = _env_int("FNG_FEAR_THRESHOLD", 20)
    fng_greed_score_penalty: float = _env_float("FNG_GREED_SCORE_PENALTY", 8.0)

    # ── Static exclusions ─────────────────────────────────────────────────
    blacklist_raw: str = _env(
        "SYMBOL_BLACKLIST",
        "USDCUSDT,FDUSDUSDT,TUSDUSDT,BUSDUSDT,DAIUSDT,EURIUSDT,AEURUSDT,USDPUSDT,"
        "PAXGUSDT,XUSDUSDT,USD1USDT,PYUSDUSDT,USDEUSDT,EURTUSDT",
    )
    leveraged_patterns: tuple = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

    dashboard_password: str = _env("DASHBOARD_PASSWORD", "")  # optional read lock (not auth-grade)

    @property
    def api_base(self) -> str:
        return self.binance_testnet_base if self.mode == "testnet" else self.binance_api_base

    @property
    def tp_ladder(self) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for chunk in self.tp_ladder_raw.split(","):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            g, s = chunk.split(":", 1)
            try:
                out.append((float(g), float(s)))
            except ValueError:
                continue
        return out or [(100.0, 30.0), (250.0, 30.0), (500.0, 40.0)]

    @property
    def blacklist(self) -> set[str]:
        return {s.strip().upper() for s in self.blacklist_raw.split(",") if s.strip()}

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.mode not in ("paper", "testnet", "live"):
            errs.append(f"MODE غير صالح: {self.mode}")
        if self.mode in ("testnet", "live") and (not self.api_key or not self.api_secret):
            errs.append(f"وضع {self.mode} يتطلب BINANCE_API_KEY و BINANCE_API_SECRET")
        if self.allocation_pct <= 0 or self.allocation_pct > 50:
            errs.append("TRADE_ALLOCATION_PCT يجب أن يكون بين 1 و 50")
        return errs


CFG = Settings()
