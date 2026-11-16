"""
═══════════════════════════════════════════════════════════════════════
  🤖 البوت ثنائي الاستراتيجية — محرك واحد + استراتيجيتان في ملف واحد
═══════════════════════════════════════════════════════════════════════
  هذا هو المحرك الأساسي الكامل (ملف واحد من الصفر). يحتوي
  استراتيجيتين مستقلتين تماماً:

  1) 🚀 راكب الترند (TREND) — الإعدادات المحسّنة المعتمدة من اختبار
       600 عملة × 30 يوماً (تقرير رفع نسبة الفوز):
       اختراق أعلى/أدنى 36 شمعة ساعة + اتجاه 4 ساعات EMA20/50
       وقف 3.0×ATR(1h) | جني 50% عند TP1=0.8R | وقف متحرك 2.0×ATR
       نتيجة الاختبار: 2140 صفقة | فوز 67.76% | صافي +1,741.33$ | PF 1.66
       طريقة الدخول (الفائز من اختبار طرق الدخول والفريمات):
       أمر وقف فوق أعلى/تحت أدنى شمعة الإشارة — صلاحية 120 دقيقة،
       وبلا لمس تُلغى الإشارة: فوز 71.44% | PF 1.92 | صافي +1,737$
  2) 📐 موجات 7/25/99 (MARS) — التركيبة البطلة المعتمدة حرفياً من اختبار
       600 عملة × 30 يوماً (FINAL2_SL5): فوز 69.94% | 3034 صفقة
       | صافي +7,414.97$ | معامل ربح 2.14:
       شراء: MA7 قطعت MA25/MA99 صعوداً (آخر 6 شمعات 15د) + شمعة زخم
             (جسم ≥50% من المدى) مغلقة فوق MA7 وفوق MA25
             + تأكيد الساعة: تقاطع صعود ≤3 شمعات ساعة + اتجاه ساعة صاعد
             + شمعة زخم ساعة فوق MA7/MA99
       بيع : MA7 قطعت هبوطاً (آخر 3 شمعات ساعة) + إغلاق بزخم تحت MA7/MA25
       وقف 5.0×ATR(ساعة) للجانبين | هدف الشراء 0.5R = 2.5×ATR
       | هدف البيع 1.75R = 8.75×ATR
       | وقف تعادل: شراء عند +0.25R / بيع عند +0.75R (يغطي العمولات)
       فلتر مخاطرة 8% (يرفض الوقف القريب من مسافة التصفية عند 10x)
       خطوط RSI: معطّلة (أُثبت بالاختبار أنها تضر)

  · كل استراتيجية لها: تحليل خاص + دخول خاص + خروج خاص + قاعدة بيانات
    مستقلة (trend_trades / mars_trades) + إحصاءات مستقلة + سعة مستقلة.
  · لا سقف إجمالي مشترك: سعة كل استراتيجية يتحكم بها متغير بيئتها وحده
    (MAX_OPEN_TRADES_TREND / MAX_OPEN_TRADES_MARS).
  · لا هوية «GENERIC» بعد اليوم: أي مركز يتيم بعد إعادة التشغيل يُسند حصراً
    إلى TREND أو MARS (بدليل من signal_log ثم تاريخ القواعد ثم السعة المتاحة)
    ويظهر في لوحته فقط — ولا صفقة تظهر في اللوحتين معاً.
  · Keep-Alive كل 10 دقائق على /health يمنع إسبان الخدمة المجانية على Render
    بعد الخمول (سبب ظهور مشاكل المصالحة بعد غياب ساعة/نصف يوم/يوم).
  · اللوحة: ملف web_panel.py واحد فيه لوحتان — /trend و /mars (+ /health)
    وفي كل لوحة تبويب «الصفقات الخاسرة» (win=0 أو pnl<0).
  · التشغيل: python bot.py        (المتغيرات عبر البيئة:
      BINANCE_API_KEY, BINANCE_API_SECRET, TRADE_ENABLED, TESTNET,
      TRADE_SIZE_USDT, MAX_OPEN_TRADES_TREND, MAX_OPEN_TRADES_MARS,
      TRADE_SIZE_USDT_TREND, TRADE_SIZE_USDT_MARS,
      DB_FILE / DATA_DIR, PORT, KEEPALIVE_URLS)
═══════════════════════════════════════════════════════════════════════
"""

import asyncio, aiohttp, json, math, os, sys, time, logging
import collections
import pandas as pd
import numpy as np
import hmac
import hashlib
import signal
from decimal import Decimal
from urllib.parse import urlencode
from logging.handlers import RotatingFileHandler
import websockets
import aiosqlite
from web_panel import start_web_panel, notify as panel_notify

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logger = logging.getLogger('DualBot')
logger.setLevel(logging.INFO)
fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
fh = RotatingFileHandler(os.path.join('/tmp', 'bot.log'), maxBytes=2*1024*1024, backupCount=2, encoding='utf-8')
fh.setFormatter(fmt); logger.addHandler(fh)
ch = logging.StreamHandler(); ch.setFormatter(fmt); logger.addHandler(ch)

import requests

def check_outbound_ip():
    try:
        # استخدام ipify لمعرفة الـ IP الخارجي
        response = requests.get('https://api.ipify.org?format=json', timeout=10)
        ip_address = response.json().get('ip')
        print(f"Current Outbound IP on Render: {ip_address}")
        return ip_address
    except Exception as e:
        print(f"Failed to fetch IP: {e}")
        return None

# استدعاء الدالة عند بدء تشغيل البوت
if __name__ == "__main__":
    check_outbound_ip()
  
# ═══ مسار قاعدة البيانات — قرار واحد مضبوط عند الإقلاع (لا انهيار أبداً) ═══
# سبب انهيار النشر سابقاً: «sqlite3.OperationalError: unable to open database file»
# يحدث إذا كان مجلد ملف القاعدة غير موجود أو غير قابل للكتابة. لذلك هنا:
# نُجرّب كل مسار مرشّح بإنشاء مجلده واختبار كتابة حقيقية قبل الاعتماد عليه،
# ومع فشل الجميع نتراجع إلى /tmp المضمون على Render.
BASE_DIR = "/tmp"


def resolve_db_path():
    """يختار أول مسار قابل للاستخدام فعلاً لقاعدة البيانات بالترتيب:
    1) DB_FILE من البيئة (مثلاً قرص Render الدائم /var/data/…)
    2) DATA_DIR من البيئة (مجلد بيانات، يُضاف إليه dual_v11.db)
    3) /tmp/dual_v11.db (مضمون الكتابة على Render دائماً)"""
    candidates = []
    env_file = (os.environ.get('DB_FILE') or '').strip()
    if env_file:
        candidates.append(('DB_FILE', env_file))
    data_dir = (os.environ.get('DATA_DIR') or '').strip()
    if data_dir:
        candidates.append(('DATA_DIR', os.path.join(data_dir, "dual_v11.db")))
    candidates.append(('DEFAULT', os.path.join(BASE_DIR, "dual_v11.db")))
    for src, path in candidates:
        folder = os.path.dirname(os.path.abspath(path)) or '.'
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, '.db_probe')
            with open(probe, 'w', encoding='utf-8') as f:
                f.write('ok')
            os.remove(probe)
            if src != 'DEFAULT':
                logger.info(f"💾 قاعدة البيانات: {path} (من المتغير {src})")
            return path
        except Exception as e:
            logger.warning(f"⚠️ مسار قاعدة البيانات غير قابل للاستخدام: {path} — السبب: {e}")
    return os.path.join(BASE_DIR, "dual_v11.db")


db_file = resolve_db_path()

# ═══════════════════════ قاعدة البيانات المشتركة ═══════════════════════
class DatabaseManager:
    """قاعدة مشتركة: الصفقات الحية + أرباح الأيام + سجل الإشارات + الإعدادات."""

    def __init__(self, db_name=None):
        # مسار واحد موحّد لكل الفئات — يأتي من resolve_db_path المضمون
        self.db_name = db_name or db_file

    async def init_db(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS active_trades (
                symbol TEXT PRIMARY KEY, side TEXT, entry_price REAL, quantity REAL,
                sl REAL, tp REAL, tp2 REAL, trailing_active INTEGER, highest_price REAL,
                lowest_price REAL, entry_time REAL, partial_closed INTEGER,
                realized_pnl REAL DEFAULT 0, stop_order_id INTEGER, tp_order_id INTEGER)""")
            for col_def in ('realized_pnl REAL DEFAULT 0', 'stop_order_id INTEGER',
                            'tp2 REAL', 'tp_order_id INTEGER', 'strategy TEXT',
                            'margin_usdt REAL DEFAULT 0'):
                try:
                    await db.execute(f"ALTER TABLE active_trades ADD COLUMN {col_def}")
                except Exception:
                    pass
            await db.execute("""CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY, realized_pnl REAL, wins INTEGER, losses INTEGER)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS bot_params (
                key TEXT PRIMARY KEY, value TEXT)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, direction TEXT,
                entry_ts REAL, score REAL, components TEXT,
                result INTEGER DEFAULT -1, pnl REAL)""")
            for col_def in ('close_ts REAL', 'close_reason TEXT',
                            'duration_s REAL', 'pnl_pct REAL'):
                try:
                    await db.execute(f"ALTER TABLE signal_log ADD COLUMN {col_def}")
                except Exception:
                    pass
            await db.commit()

    async def get_param(self, key):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                async with db.execute("SELECT value FROM bot_params WHERE key=?", (key,)) as cur:
                    row = await cur.fetchone()
                    return row[0] if row else None
        except Exception:
            return None

    async def set_param(self, key, value):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO bot_params (key, value) VALUES (?,?)", (key, value))
            await db.commit()

    async def log_signal(self, symbol, direction, entry_ts, score, components):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute(
                    "INSERT INTO signal_log (symbol, direction, entry_ts, score, components) VALUES (?,?,?,?,?)",
                    (symbol, direction, entry_ts, score, json.dumps(components, ensure_ascii=False)))
                await db.commit()
        except Exception as e:
            logger.warning(f"تعذر تسجيل الإشارة: {e}")

    async def set_signal_result(self, symbol, entry_ts, win, pnl,
                                close_ts=None, close_reason=None, duration_s=None, pnl_pct=None):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute(
                    """UPDATE signal_log SET result=?, pnl=?, close_ts=?, close_reason=?,
                       duration_s=?, pnl_pct=? WHERE symbol=? AND entry_ts=? AND result=-1""",
                    (int(win), pnl, close_ts, close_reason, duration_s, pnl_pct,
                     symbol, entry_ts))
                await db.commit()
        except Exception as e:
            logger.warning(f"تعذر تحديث نتيجة الإشارة: {e}")

    async def save_trade(self, t):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""INSERT OR REPLACE INTO active_trades
                (symbol, side, entry_price, quantity, sl, tp, tp2, trailing_active,
                 highest_price, lowest_price, entry_time, partial_closed,
                 realized_pnl, stop_order_id, tp_order_id, strategy, margin_usdt)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t['symbol'], t['side'], t['entry_price'], t['quantity'],
                 t['sl'], t['tp'], t.get('tp2'), int(t.get('trailing_active', False)),
                 t.get('highest_price', 0), t.get('lowest_price', 999999),
                 t['entry_time'], int(t.get('partial_closed', 0)),
                 float(t.get('realized_pnl', 0.0)), t.get('stop_order_id'), t.get('tp_order_id'),
                 t.get('strategy') or '', float(t.get('margin_usdt') or 0)))
            await db.commit()

    async def load_active_trades(self):
        trades = {}
        try:
            async with aiosqlite.connect(self.db_name) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""SELECT symbol, side, entry_price, quantity, sl, tp, tp2,
                    trailing_active, highest_price, lowest_price, entry_time, partial_closed,
                    realized_pnl, stop_order_id, tp_order_id, strategy, margin_usdt
                    FROM active_trades""") as cur:
                    async for row in cur:
                        trades[row['symbol']] = {
                            'symbol': row['symbol'], 'side': row['side'],
                            'entry_price': row['entry_price'], 'quantity': row['quantity'],
                            'sl': row['sl'], 'tp': row['tp'], 'tp2': row['tp2'],
                            'trailing_active': bool(row['trailing_active']),
                            'highest_price': row['highest_price'],
                            'lowest_price': row['lowest_price'],
                            'entry_time': row['entry_time'],
                            'partial_closed': bool(row['partial_closed']),
                            'realized_pnl': row['realized_pnl'] if row['realized_pnl'] is not None else 0.0,
                            'stop_order_id': row['stop_order_id'],
                            'tp_order_id': row['tp_order_id'],
                            'strategy': row['strategy'] or None,
                            'margin_usdt': row['margin_usdt'] or 0,
                            'stop_synced_price': None, 'tp_skipped': False
                        }
        except Exception as e:
            logger.error(f"❌ فشل تحميل الصفقات من القاعدة: {e}")
        return trades

    async def remove_trade(self, symbol):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM active_trades WHERE symbol=?", (symbol,))
            await db.commit()

    async def update_daily_pnl(self, pnl, is_win=None):
        today = time.strftime("%Y-%m-%d")
        w = 1 if is_win is True else 0
        l = 1 if is_win is False else 0
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("SELECT * FROM daily_stats WHERE date=?", (today,)) as cur:
                row = await cur.fetchone()
            if row:
                await db.execute("UPDATE daily_stats SET realized_pnl=?, wins=?, losses=? WHERE date=?",
                    (row[1]+pnl, row[2]+w, row[3]+l, today))
            else:
                await db.execute("INSERT INTO daily_stats VALUES (?,?,?,?)", (today, pnl, w, l))
            await db.commit()

    async def get_day_stats(self, day):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                async with db.execute(
                        "SELECT realized_pnl, wins, losses FROM daily_stats WHERE date=?", (day,)) as cur:
                    return await cur.fetchone()
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
#  🚀 الاستراتيجية الأولى: راكب الترند (TREND) — كما في الملف الأصلي
# ══════════════════════════════════════════════════════════════════════
TREND_CONFIG = {
    "name": "TREND",
    "label": "راكب الترند",
    "enabled": True,
    # ✅ v3: اعتماد طريقة الدخول الجديدة وإجبار تحميلها فوق أي إعدادات قديمة محفوظة
    "settings_version": 3,
    # الدخول
    "donch": 36,               # ✅ اختراق أعلى/أدنى 36 شمعة ساعة سابقة (كان 48)
    "sl_atr1h": 3.0,           # ✅ الوقف = 3.0 × ATR(1h) (كان 2.5)
    "tp1_r": 0.80,             # ✅ TP1 = 0.8 × مسافة الوقف (كان 0.9)
    "partial": 0.50,           # ✅ يُغلق 50% عند TP1 (كان 70%)
    "trail_atr": 2.0,          # ✅ الوقف المتحرك = 2.0 × ATR(1h) من أعلى إغلاق (كان 1.5)
    "be_offset": 0.002,        # التعادل +0.2% بعد الجني
    "max_hold_minutes": 5 * 24 * 60,
    # ✅ طريقة الدخول (الفائزة حرفياً من اختبار طرق الدخول والفريمات):
    #    STOP_HIGHLOW = أمر وقف فوق أعلى/تحت أدنى شمعة الإشارة بدل السوق الفوري؛
    #    الصلاحية 120 دقيقة من إغلاق شمعة الإشارة، وبلا لمس تُلغى الإشارة (اختراق ضعيف).
    #    نتيجة الاختبار: فوز 71.44% | PF 1.92 | صافي +1,737$ — فريم 1h+4h دون تغيير القيم الخمس
    "entry_method": "STOP_HIGHLOW",
    "stop_validity_min": 120,
    # فلاتر
    "max_risk_pct": 3.5,
    "min_atr_pct": 0.15,
    "max_atr_pct": 6.0,
    "max_day_change": 0.35,
    "entry_window_min": 25,    # نافذة كشف الإشارة: خلال أول 25 دقيقة بعد إغلاق الساعة
    # السعة المستقلة
    "max_open_trades": 5,
    "reentry_cooldown": 3600,
    "scan_limit": 60,
}


def ema(a, n):
    a = np.asarray(a, dtype=float)
    out = np.empty_like(a)
    out[0] = a[0]
    k = 2.0 / (n + 1.0)
    for i in range(1, len(a)):
        out[i] = out[i - 1] + k * (a[i] - out[i - 1])
    return out


def rma(a, n):
    a = np.asarray(a, dtype=float)
    out = np.full_like(a, np.nan)
    if len(a) < n:
        return out
    out[n - 1] = np.nanmean(a[:n])
    for i in range(n, len(a)):
        out[i] = out[i - 1] + (a[i] - out[i - 1]) / n
    return out


def atr(h, l, c, n=14):
    c = np.asarray(c, dtype=float)
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    pc = np.roll(c, 1)
    pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return rma(tr, n)


def _closed(df):
    """الشموع المغلقة فقط (يُستبعد آخر شمعة قيد التكوين)."""
    if df is None or len(df) < 60:
        return None
    return df.iloc[:-1].copy()


def _arr(df, col):
    return df[col].to_numpy(dtype=float)


def trend_compute_signal(df15, df1h, df4h, cfg=None):
    """يُعيد dict للتحليل إذا تحققت شروط الدخول على آخر شمعة ساعية مكتملة، وإلا None."""
    cfg = dict(TREND_CONFIG if cfg is None else cfg)
    h1, h4, m15 = _closed(df1h), _closed(df4h), _closed(df15)
    if h1 is None or h4 is None or m15 is None:
        return None
    if len(h1) < 220 or len(h4) < 55:
        return None

    c1, o1, hh1, ll1 = _arr(h1, "close"), _arr(h1, "open"), _arr(h1, "high"), _arr(h1, "low")
    a1 = atr(hh1, ll1, c1, 14)
    e20, e50 = ema(c1, 20), ema(c1, 50)
    n = int(cfg["donch"])
    if len(c1) < n + 5:
        return None
    prior_high = float(pd.Series(hh1).rolling(n).max().iloc[-2])   # بدون شمعة الإشارة
    prior_low = float(pd.Series(ll1).rolling(n).min().iloc[-2])
    i = len(c1) - 1
    cx, ox = c1[i], o1[i]
    a = a1[i]
    if not np.isfinite(a) or a <= 0:
        return None

    c4 = _arr(h4, "close")
    e20_4, e50_4 = ema(c4, 20)[-1], ema(c4, 50)[-1]
    up4 = e20_4 > e50_4 and cx > e50_4
    dn4 = e20_4 < e50_4 and cx < e50_4

    px = float(m15["close"].iloc[-1])
    atr_pct = a / px * 100.0
    if atr_pct > float(cfg["max_atr_pct"]) or atr_pct < float(cfg["min_atr_pct"]):
        return None
    mc = _arr(m15, "close")
    if len(mc) >= 97 and abs(mc[-1] / max(mc[-97], 1e-12) - 1.0) > float(cfg["max_day_change"]):
        return None

    side = None
    if up4 and cx > prior_high and cx > ox:
        side = "BUY"
    elif dn4 and cx < prior_low and cx < ox:
        side = "SELL"
    if side is None:
        return None

    risk = float(cfg["sl_atr1h"]) * a
    risk_pct = risk / px * 100.0
    if risk_pct > float(cfg["max_risk_pct"]) or risk_pct < 0.05:
        return None

    return {
        "side": side, "price_ref": px, "atr": float(a), "atr_pct": round(atr_pct, 2),
        "risk": float(risk), "risk_pct": round(risk_pct, 2),
        "prior_high": round(prior_high, 10), "prior_low": round(prior_low, 10),
        "sig_high": float(hh1[i]), "sig_low": float(ll1[i]),
        "trend_4h": "صاعد" if up4 else "هابط",
        "hour_close_ts": int(h1["close_time"].iloc[-1]) if "close_time" in h1 else None,
        "hour_open_ts": int(h1["time"].iloc[-1]),
        "hour_ref_price": float(cx),
    }


class TrendStrategy:
    """واجهة المحرك: analyze() تُعيد تحليلاً بصيغة التنفيذ نفسها."""

    def __init__(self, cfg=None, logger=None):
        self.cfg = dict(TREND_CONFIG)
        if cfg:
            self.cfg.update(cfg)
        self.log = logger or (lambda *a, **k: None)
        self.last_scan = {}
        self.stats = {"scanned": 0, "signals": 0, "errors": 0}

    async def analyze(self, bot, symbol, now=None):
        try:
            k15 = await bot.get_klines(symbol, "15m", 200)
            k1h = await bot.get_klines(symbol, "1h", 260)
            k4h = await bot.get_klines(symbol, "4h", 120)
            if k15 is None or k1h is None or k4h is None:
                return None
            sig = trend_compute_signal(k15, k1h, k4h, self.cfg)
            if not sig:
                return None
            # نافذة كشف الإشارة: خلال أول X دقيقة بعد إغلاق الشمعة الساعية
            now_ms = int((now or time.time()) * 1000)
            hour_open = sig["hour_open_ts"]
            elapsed_min = (now_ms - (hour_open + 3600_000)) / 60000.0
            if elapsed_min < -2 or elapsed_min > float(self.cfg["entry_window_min"]):
                return None

            risk = float(self.cfg["sl_atr1h"]) * sig["atr"]

            # ✅ طريقة الدخول «وقف فوق شمعة الإشارة»: لا دخول فوري — يُسلّح أمر معلق
            #    عند أعلى/أدنى شمعة الإشارة بصلاحية stop_validity_min دقيقة؛ عند اللمس
            #    يُنفّذ سوق ويُعاد حساب الوقف/الهدف من سعر التنفيذ الفعلي (مطابق للاختبار)
            if str(self.cfg.get("entry_method", "MARKET")) == "STOP_HIGHLOW":
                trigger = float(sig["sig_high"]) if sig["side"] == "BUY" else float(sig["sig_low"])
                px = trigger
                sl, tp1 = px - risk, px + float(self.cfg["tp1_r"]) * risk   # مبدئي — يُعاد حسابه عند اللمس
                validity_min = float(self.cfg.get("stop_validity_min", 120))
                expires_at = (int(sig["hour_open_ts"]) / 1000.0) + 3600.0 + validity_min * 60.0
                return {
                    "symbol": symbol, "direction": sig["side"], "price": px,
                    "sl": sl, "tp1": tp1, "tp2": None,
                    "score": 8, "strategy": "TREND",
                    "atr_ref": sig["atr"],
                    "pending_entry": True, "trigger_price": px, "expires_at": expires_at,
                    "components": {
                        "strategy": "TREND",
                        "trigger": f"اختراق {int(self.cfg['donch'])} ساعة + أمر وقف على شمعة الإشارة (صلاحية {int(validity_min)}د)",
                        "trend_4h": sig["trend_4h"], "atr_pct": sig["atr_pct"],
                        "risk_pct": sig["risk_pct"], "level": px,
                    },
                    "signals_smc": [
                        f"🚀 اختراق {'صاعد' if sig['side']=='BUY' else 'هابط'} بعد {int(self.cfg['donch'])} ساعة تجميع",
                        f"⏳ انتظار لمس {'أعلى' if sig['side']=='BUY' else 'أدنى'} شمعة الإشارة خلال {int(validity_min)} دقيقة — بلا لمس تُلغى",
                        f"🛡️ وقف {sig['risk_pct']}% | TP1 عند {self.cfg['tp1_r']}R ثم وقف متحرك",
                    ],
                }

            prices = bot.get_price(symbol)
            if not prices:
                return None
            px = prices["ask"] if sig["side"] == "BUY" else prices["bid"]
            if sig["side"] == "BUY":
                sl, tp1 = px - risk, px + float(self.cfg["tp1_r"]) * risk
            else:
                sl, tp1 = px + risk, px - float(self.cfg["tp1_r"]) * risk
            return {
                "symbol": symbol, "direction": sig["side"], "price": px,
                "sl": sl, "tp1": tp1, "tp2": None,
                "score": 8, "strategy": "TREND",
                "atr_ref": sig["atr"],
                "components": {
                    "strategy": "TREND", "trigger": f"اختراق {int(self.cfg['donch'])} ساعة",
                    "trend_4h": sig["trend_4h"], "atr_pct": sig["atr_pct"],
                    "risk_pct": sig["risk_pct"], "level": sig["prior_high"] if sig["side"] == "BUY" else sig["prior_low"],
                },
                "signals_smc": [
                    f"🚀 اختراق {'صاعد' if sig['side']=='BUY' else 'هابط'} بعد {int(self.cfg['donch'])} ساعة تجميع",
                    f"📈 اتجاه 4 ساعات {sig['trend_4h']} | ATR(1h) {sig['atr_pct']}%",
                    f"🛡️ وقف {sig['risk_pct']}% | TP1 عند {self.cfg['tp1_r']}R ثم وقف متحرك",
                ],
            }
        except Exception as e:
            self.stats["errors"] += 1
            self.log(f"خطأ تحليل الترند لـ {symbol}: {e}")
            return None

    async def scan(self, bot, candidates, active_symbols, cooldowns):
        found, scanned = [], 0
        now = time.time()
        for sym in candidates:
            if len(found) >= 2:
                break
            if sym in active_symbols or cooldowns.get(sym, 0) > now:
                continue
            if scanned >= int(self.cfg["scan_limit"]):
                break
            scanned += 1
            a = await self.analyze(bot, sym, now)
            if a:
                found.append(a)
        self.stats["scanned"] = scanned
        self.stats["signals"] = len(found)
        self.last_scan = {"ts": now, "scanned": scanned, "signals": len(found)}
        return found


class TrendExitManager:
    """خروج الترند: وقف ATR، جني جزئي عند TP1، تعادل، وقف متحرك 2.0×ATR، خروج زمني."""

    def __init__(self, cfg=None, logger=None):
        self.cfg = dict(TREND_CONFIG)
        if cfg:
            self.cfg.update(cfg)
        self.log = logger or (lambda *a, **k: None)

    def decide(self, trade, price, atr_now=None):
        """
        يُعيد:
          {"action": "hold"}
          {"action": "close",  "reason": str}
          {"action": "partial", "reason": str}     # جني 70% + نقل للتعادل
          {"action": "move_sl", "sl": float}       # تحديث الوقف فقط
        """
        side = trade["side"]
        cfg = self.cfg
        atr_v = float(trade.get("atr_ref") or (atr_now or 0) or 0)
        if atr_v <= 0:
            return {"action": "hold"}
        is_buy = side == "BUY"
        entry = float(trade["entry_price"])
        sl = float(trade["sl"])
        tp1 = float(trade["tp"]) if trade.get("tp") else None
        partial_done = bool(trade.get("partial_closed"))

        # 1) وقف الخسارة
        if (is_buy and price <= sl) or ((not is_buy) and price >= sl):
            return {"action": "close", "reason": "🛑 ضرب الوقف" if not partial_done else "🪂 الوقف المتحرك"}

        # 2) خروج زمني
        held_min = (time.time() - float(trade["entry_time"])) / 60.0
        if held_min >= float(cfg["max_hold_minutes"]):
            return {"action": "close", "reason": "⏳ خروج زمني (5 أيام)"}

        # 3) الجني الجزئي عند TP1
        if (not partial_done) and tp1:
            if (is_buy and price >= tp1) or ((not is_buy) and price <= tp1):
                return {"action": "partial",
                        "reason": f"🎯 جني {int(float(cfg['partial']) * 100)}% عند TP1"}

        # 4) الوقف المتحرك بعد الجني (2.0 × ATR من أعلى/أدنى سعر)
        if partial_done:
            ext = float(trade.get("highest_price" if is_buy else "lowest_price") or price)
            if is_buy:
                ext = max(ext, price)
                new_sl = ext - float(cfg["trail_atr"]) * atr_v
                if new_sl > sl + 1e-12:
                    return {"action": "move_sl", "sl": new_sl}
            else:
                ext = min(ext, price)
                new_sl = ext + float(cfg["trail_atr"]) * atr_v
                if new_sl < sl - 1e-12:
                    return {"action": "move_sl", "sl": new_sl}
        return {"action": "hold"}


TREND_SCHEMA = """
CREATE TABLE IF NOT EXISTS trend_trades (
    symbol TEXT PRIMARY KEY, side TEXT, entry REAL, sl REAL, tp1 REAL, atr REAL,
    entry_ts REAL, exit_ts REAL, pnl REAL, pnl_pct REAL, win INTEGER DEFAULT -1,
    reason TEXT, components TEXT, margin REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trend_daily (
    date TEXT PRIMARY KEY, pnl REAL, wins INTEGER, losses INTEGER
);
CREATE INDEX IF NOT EXISTS idx_trend_entry ON trend_trades(entry_ts);
"""


class TrendDB:
    TABLE = 'trend_trades'

    def __init__(self, db_name=None):
        self.db_name = db_name or db_file

    async def init(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript(TREND_SCHEMA)
            # ترقية قواعد بيانات قديمة: عمود هامش صفقة الترند
            try:
                await db.execute("ALTER TABLE trend_trades ADD COLUMN margin REAL DEFAULT 0")
            except Exception:
                pass
            await db.commit()

    async def open(self, t):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """INSERT OR REPLACE INTO trend_trades
                   (symbol, side, entry, sl, tp1, atr, entry_ts, margin, components)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (t["symbol"], t["side"], t["entry_price"], t["sl"], t.get("tp"),
                 t.get("atr_ref") or 0, t["entry_time"],
                 float(t.get("margin_usdt") or 0),
                 json.dumps(t.get("components", {}), ensure_ascii=False)))
            await db.commit()

    async def close(self, symbol, exit_ts, pnl, pnl_pct, win, reason):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """UPDATE trend_trades SET exit_ts=?, pnl=?, pnl_pct=?, win=?, reason=?
                   WHERE symbol=? AND win=-1""",
                (exit_ts, pnl, pnl_pct, int(win), str(reason)[:200], symbol))
            day = time.strftime("%Y-%m-%d", time.localtime(exit_ts))
            async with db.execute("SELECT pnl, wins, losses FROM trend_daily WHERE date=?", (day,)) as cur:
                row = await cur.fetchone()
            w, l = (1, 0) if win else (0, 1)
            if row:
                await db.execute("UPDATE trend_daily SET pnl=?, wins=?, losses=? WHERE date=?",
                                 (row[0] + pnl, row[1] + w, row[2] + l, day))
            else:
                await db.execute("INSERT INTO trend_daily VALUES (?,?,?,?)", (day, pnl, w, l))
            await db.commit()

    async def update_sl(self, symbol, sl):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE trend_trades SET sl=? WHERE symbol=? AND win=-1", (sl, symbol))
            await db.commit()

    async def open_symbols(self):
        """استعادة صفقات الترند المفتوحة بعد إعادة التشغيل."""
        out = {}
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """SELECT symbol, side, entry, sl, tp1, atr, entry_ts, margin
                       FROM trend_trades WHERE win=-1""") as cur:
                for r in await cur.fetchall():
                    out[r[0]] = {"symbol": r[0], "side": r[1], "entry": r[2], "sl": r[3],
                                 "tp1": r[4], "tp2": None, "atr": r[5], "entry_ts": r[6],
                                 "margin": r[7] or 0}
        return out

    async def summary(self, days=30):
        since = time.time() - days * 86400
        out = {"closed": 0, "wins": 0, "losses": 0, "winrate": 0.0, "net": 0.0,
               "pf": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "trades": [], "daily": []}
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    """SELECT COUNT(*) n, SUM(win=1) w, SUM(win=0) l, SUM(pnl) net,
                              AVG(CASE WHEN win=1 THEN pnl END) aw,
                              AVG(CASE WHEN win=0 THEN pnl END) al,
                              SUM(CASE WHEN win=1 THEN pnl ELSE 0 END) g,
                              SUM(CASE WHEN win=0 THEN -pnl ELSE 0 END) ls
                       FROM trend_trades WHERE win>=0 AND exit_ts>=?""", (since,)) as cur:
                r = await cur.fetchone()
            if r and r["n"]:
                n = r["n"]
                out.update({
                    "closed": n, "wins": int(r["w"] or 0), "losses": int(r["l"] or 0),
                    "winrate": round((r["w"] or 0) / n * 100, 2),
                    "net": round(r["net"] or 0.0, 2),
                    "pf": round((r["g"] or 0) / r["ls"], 3) if (r["ls"] or 0) > 0 else 999.0,
                    "avg_win": round(r["aw"] or 0.0, 2), "avg_loss": round(r["al"] or 0.0, 2),
                })
            async with db.execute(
                    """SELECT symbol, side, entry, exit_ts, pnl, pnl_pct, win, reason
                       FROM trend_trades WHERE win>=0 ORDER BY exit_ts DESC LIMIT 60""") as cur:
                out["trades"] = [dict(x) for x in await cur.fetchall()]
            async with db.execute("SELECT date, pnl, wins, losses FROM trend_daily ORDER BY date DESC LIMIT 30") as cur:
                out["daily"] = [{"date": x[0], "pnl": round(x[1] or 0, 2), "wins": x[2], "losses": x[3]}
                                for x in await cur.fetchall()]
        return out


# ══════════════════════════════════════════════════════════════════════
#  📐 الاستراتيجية الثانية: موجات 7/25/99 (MARS)
#     ✅ الإعدادات المعتمدة حرفياً من الاختبار الموسّع:
#        600 عملة × 30 يوماً — التركيبة البطلة FINAL2_SL5
#        فوز 69.94% | 3034 صفقة (2122 رابحة / 912 خاسرة)
#        صافي +7,414.97$ | معامل ربح 2.14 | أقصى تراجع -1,531.61$
# ══════════════════════════════════════════════════════════════════════
MARS_FEE = 0.0005             # عمولة taker لكل جانب (نفس افتراض الاختبار المعتمد)
MARS_CONFIG = {
    "name": "MARS",
    "label": "موجات 7/25/99",
    "enabled": True,
    "settings_version": 2,       # يُبطل أي إعدادات قديمة محفوظة من اللوحة
    # الدخول
    "ma_fast": 7, "ma_mid": 25, "ma_slow": 99,
    "rsi_fast": 7, "rsi_mid": 25, "rsi_slow": 99,
    "cross_window_15m": 6,       # «قطعت ضمن آخر 6 شمعات 15د» (شراء)
    "cross_window_1h": 3,        # «قطعت ضمن آخر 3 شمعات ساعة» (بيع + تأكيد الشراء)
    "momentum_body": 0.5,        # الزخم: الجسم ≥ 50% من مدى الشمعة
    "require_c2": False,         # التأكيد القديم للجانبين — استُبدل بفلاتر لكل جانب
    "require_c2_buy": True,      # ✅ معتمد: الشراء يتطلب تأكيد الساعة (تقاطع صعود ≤3 شمعات ساعة + اتجاه ساعة صاعد + شمعة زخم ساعة فوق MA7/MA99)
    "require_c2_sell": False,    # ✅ معتمد: البيع بلا تأكيد إضافي (كما اختُبر بالضبط)
    "require_rsi": False,        # خطوط RSI على الشارت معطّلة (أسوأ بالاختبار)
    "rsi_line_win": 99,          # نافذة رسم خطوط RSI (لو فعّلتها لاحقاً)
    # الخروج (التركيبة البطلة FINAL2_SL5 — معتمدة حرفياً)
    "sl_atr1h": 5.0,             # ✅ الوقف = 5.0 × ATR(ساعة) للجانبين (كان 1.5)
    "tp_r": 2.0,                 # قيمة احتياطية فقط — الفعلي tp_r_buy / tp_r_sell
    "tp_r_buy": 0.5,             # ✅ هدف الشراء = 0.5R = 2.50 × ATR(ساعة) (كان 2R)
    "tp_r_sell": 1.75,           # ✅ هدف البيع = 1.75R = 8.75 × ATR(ساعة) (كان 2R)
    "be_trigger_buy": 0.25,      # ✅ نقل وقف الشراء للتعادل بعد بلوغ +0.25R
    "be_trigger_sell": 0.75,     # ✅ نقل وقف البيع للتعادل بعد بلوغ +0.75R
    "max_hold_minutes": 7 * 24 * 60,   # خروج زمني احترازي (كما في الاختبار)
    # الفلاتر
    "max_risk_pct": 8.0,         # رفض الإشارة إذا قارب وقفها مسافة التصفية (كما في الاختبار)
    # السعة والتبريد (يديرها المحرك)
    "max_open_trades": 5,
    "reentry_cooldown": 3600,
    "scan_limit": 60,
}


def sma(a, n):
    return pd.Series(a).rolling(n, min_periods=n).mean().to_numpy()


def rsi_wilder(close, n):
    """RSI بطريقة Wilder (RMA) — مطابق للمنصات."""
    d = np.diff(close, prepend=close[:1])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = pd.Series(up).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()
    ad = pd.Series(dn).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()
    rs = au / np.where(ad == 0, np.nan, ad)
    out = 100 - 100 / (1 + rs)
    return np.where(ad == 0, 100.0, np.where(au == 0, 0.0, out))


def atr_wilder(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()


def _recent(x, w):
    """تحقق الحدث خلال آخر w شمعة (شاملة الحالية)."""
    return pd.Series(x.astype(float)).rolling(w, min_periods=1).max().to_numpy() > 0.5


def _cross_up(a, b):
    x = np.zeros(len(a), dtype=bool)
    x[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return x


def _cross_dn(a, b):
    x = np.zeros(len(a), dtype=bool)
    x[1:] = (a[1:] < b[1:]) & (a[:-1] >= b[:-1])
    return x


def mars_compute_signal(df15, df1h, cfg=None):
    """
    يُعيد dict للإشارة إذا تحققت القواعد على آخر شمعة مكتملة، وإلا None.
    df15/df1h: DataFrame بأعمدة open/high/low/close (مغلقة فقط).
    """
    cfg = dict(MARS_CONFIG if cfg is None else cfg)
    if df15 is None or df1h is None or len(df15) < 130 or len(df1h) < 130:
        return None
    c15, o15, h15, l15 = _arr(df15, "close"), _arr(df15, "open"), _arr(df15, "high"), _arr(df15, "low")
    c1h, o1h, h1h, l1h = _arr(df1h, "close"), _arr(df1h, "open"), _arr(df1h, "high"), _arr(df1h, "low")

    def tf(o, h, l, c):
        ma7, ma25, ma99 = sma(c, cfg["ma_fast"]), sma(c, cfg["ma_mid"]), sma(c, cfg["ma_slow"])
        r7 = rsi_wilder(c, cfg["rsi_fast"])
        r25 = rsi_wilder(c, cfg["rsi_mid"])
        rng = h - l
        body = np.where(rng > 0, (c - o) / np.where(rng > 0, rng, 1.0), 0.0)
        lo = pd.Series(l).rolling(cfg["rsi_line_win"], min_periods=cfg["rsi_line_win"]).min()
        hi = pd.Series(h).rolling(cfg["rsi_line_win"], min_periods=cfg["rsi_line_win"]).max()
        line7 = (lo + (hi - lo) * r7 / 100.0).to_numpy()
        line25 = (lo + (hi - lo) * r25 / 100.0).to_numpy()
        return dict(ma7=ma7, ma25=ma25, ma99=ma99, r7=r7,
                    xu=_recent(_cross_up(ma7, ma25) | _cross_up(ma7, ma99), cfg["cross_window_15m"]),
                    xd=_recent(_cross_dn(ma7, ma25) | _cross_dn(ma7, ma99), cfg["cross_window_15m"]),
                    xu1=_recent(_cross_up(ma7, ma25) | _cross_up(ma7, ma99), cfg["cross_window_1h"]),
                    xd1=_recent(_cross_dn(ma7, ma25) | _cross_dn(ma7, ma99), cfg["cross_window_1h"]),
                    up=(ma7 > ma25) | (ma7 > ma99), dn=(ma7 < ma25) | (ma7 < ma99),
                    mom_b=(c > o) & (body >= cfg["momentum_body"]) & (c > ma7) & (c > ma25),
                    mom_s=(c < o) & (-body >= cfg["momentum_body"]) & (c < ma7) & (c < ma25),
                    mom_b99=(c > o) & (body >= cfg["momentum_body"]) & (c > ma7) & (c > ma99),
                    mom_s99=(c < o) & (-body >= cfg["momentum_body"]) & (c < ma7) & (c < ma99),
                    rsi_b=(c > line7) & (c > line25), rsi_s=(c < line7) & (c < line25))

    A, B = tf(o15, h15, l15, c15), tf(o1h, h1h, l1h, c1h)
    i, j = len(c15) - 1, len(c1h) - 1
    atr_v = atr_wilder(h1h, l1h, c1h, 14)[j]
    px = float(c15[i])
    if not np.isfinite(atr_v) or atr_v <= 0 or not np.isfinite(px):
        return None

    buy = A["xu"][i] & A["up"][i] & A["mom_b"][i]
    sell = B["xd1"][j] & B["dn"][j] & B["mom_s"][j]
    if cfg.get("require_c2"):          # القديم: تأكيد للجانبين معاً
        buy &= B["xu1"][j] & B["up"][j] & B["mom_b99"][j]
        sell &= A["xd"][i] & A["dn"][i] & A["mom_s99"][i]
    if cfg.get("require_c2_buy"):      # ✅ معتمد: تأكيد الساعة للشراء فقط (كما اختُبر)
        buy &= B["xu1"][j] & B["up"][j] & B["mom_b99"][j]
    if cfg.get("require_c2_sell"):     # تأكيد اختياري للبيع (معطّل في المعتمد)
        sell &= A["xd"][i] & A["dn"][i] & A["mom_s99"][i]
    if cfg["require_rsi"]:
        buy &= A["rsi_b"][i]
        sell &= B["rsi_s"][j]
    if buy == sell:          # لا إشارة أو تعارض
        return None
    side = "BUY" if buy else "SELL"

    risk = float(cfg["sl_atr1h"]) * atr_v
    risk_pct = risk / px * 100.0
    if risk_pct > float(cfg["max_risk_pct"]):
        return None          # الوقف قارب مسافة التصفية — مرفوض (فلتر 8%)
    if side == "BUY":
        sl, tp = px - risk, px + float(cfg.get("tp_r_buy", cfg["tp_r"])) * risk
    else:
        sl, tp = px + risk, px - float(cfg.get("tp_r_sell", cfg["tp_r"])) * risk

    strong = bool((A["ma7"][i] > A["ma25"][i]) and (A["ma7"][i] > A["ma99"][i])) if buy \
        else bool((B["ma7"][j] < B["ma25"][j]) and (B["ma7"][j] < B["ma99"][j]))
    return {
        "side": side, "price_ref": px, "atr": float(atr_v), "risk_pct": round(risk_pct, 2),
        "sl": sl, "tp": tp, "strong": strong,
    }


class MaRsiStrategy:
    """واجهة المحرك: analyze() تُعيد صيغة التنفيذ نفسها."""

    def __init__(self, cfg=None, logger=None):
        self.cfg = dict(MARS_CONFIG)
        if cfg:
            self.cfg.update(cfg)
        self.log = logger or (lambda *a, **k: None)
        self.last_scan = {}
        self.stats = {"scanned": 0, "signals": 0, "errors": 0}

    def _closed(self, df):
        """الشموع المغلقة فقط (استبعاد شمعة قيد التكوين)."""
        if df is None or len(df) < 130:
            return None
        return df.iloc[:-1]

    async def analyze(self, bot, symbol, now=None):
        try:
            k15 = self._closed(await bot.get_klines(symbol, "15m", 200))
            k1h = self._closed(await bot.get_klines(symbol, "1h", 200))
            if k15 is None or k1h is None:
                return None
            sig = mars_compute_signal(k15, k1h, self.cfg)
            if not sig:
                return None
            prices = bot.get_price(symbol)
            if not prices:
                return None
            px = prices["ask"] if sig["side"] == "BUY" else prices["bid"]
            risk = float(self.cfg["sl_atr1h"]) * sig["atr"]
            is_buy = sig["side"] == "BUY"
            tp_r = float(self.cfg.get("tp_r_buy" if is_buy else "tp_r_sell",
                                      self.cfg["tp_r"]))
            be_r = float(self.cfg.get("be_trigger_buy" if is_buy else "be_trigger_sell",
                                      0) or 0)
            if is_buy:
                sl, tp = px - risk, px + tp_r * risk
                be_trig = px + be_r * risk if be_r > 0 else None
                be_px = px * (1 + MARS_FEE) / (1 - MARS_FEE) * (1 + 1e-6)
            else:
                sl, tp = px + risk, px - tp_r * risk
                be_trig = px - be_r * risk if be_r > 0 else None
                be_px = px * (1 - MARS_FEE) / (1 + MARS_FEE) * (1 - 1e-6)
            return {
                "symbol": symbol, "direction": sig["side"], "price": px,
                "sl": sl, "tp1": tp, "tp2": None,
                "score": 8, "strategy": "MARS", "atr_ref": sig["atr"],
                "be_trigger": be_trig, "be_price": be_px if be_trig else None,
                "components": {
                    "strategy": "MARS", "trigger": "تقاطع 7/25/99 + زخم",
                    "strong": sig["strong"], "risk_pct": sig["risk_pct"],
                },
                "signals_smc": [
                    f"📐 MA7 قطعت {'فوق' if is_buy else 'تحت'} متوسطات 25/99 + إغلاق بزخم"
                    + (" + تأكيد الساعة" if is_buy else ""),
                    f"🛡️ وقف {sig['risk_pct']}% ({self.cfg['sl_atr1h']}×ATR ساعة) | "
                    f"هدف {tp_r}R | تعادل عند +{be_r}R",
                ],
            }
        except Exception as e:
            self.stats["errors"] += 1
            self.log(f"خطأ تحليل 7/25/99 لـ {symbol}: {e}")
            return None

    async def scan(self, bot, candidates, active_symbols, cooldowns):
        found, scanned = [], 0
        now = time.time()
        for sym in candidates:
            if len(found) >= 2:
                break
            if sym in active_symbols or cooldowns.get(sym, 0) > now:
                continue
            if scanned >= int(self.cfg["scan_limit"]):
                break
            scanned += 1
            a = await self.analyze(bot, sym, now)
            if a:
                found.append(a)
        self.stats["scanned"] = scanned
        self.stats["signals"] = len(found)
        self.last_scan = {"ts": now, "scanned": scanned, "signals": len(found)}
        return found


class MaRsiExitManager:
    """
    خروج مطابق للتركيبة المعتمدة حرفياً (FINAL2_SL5 — فوز 69.94%):
      • وقف 5.0×ATR(ساعة) للجانبين
      • هدف شراء 0.5R / هدف بيع 1.75R
      • 🛡️ وقف تعادل: شراء بعد +0.25R | بيع بعد +0.75R
        (سعر التعادل يغطي عمولتي الدخول والخروج — نفس معادلة الاختبار)
      • خروج زمني احترازي بعد 7 أيام
    """

    def __init__(self, cfg=None, logger=None):
        self.cfg = dict(MARS_CONFIG)
        if cfg:
            self.cfg.update(cfg)
        self.log = logger or (lambda *a, **k: None)

    def _derive_be_state(self, trade):
        """استعادة حالة التعادل بعد إعادة التشغيل: الوقف الأصلي أبعد من الدخول،
        ووقف التعادل أقرب قليلاً من الدخول (يغطي العمولة) — التمييز حتمي."""
        if trade.get("be_active") is not None:
            return
        try:
            entry = float(trade.get("entry_price") or 0)
            sl = float(trade.get("sl") or 0)
            is_buy = trade.get("side") == "BUY"
            if entry > 0 and sl > 0:
                trade["be_active"] = (sl >= entry) if is_buy else (sl <= entry)
            else:
                trade["be_active"] = False
        except Exception:
            trade["be_active"] = False

    def decide(self, trade, price, atr_now=None):
        side = trade["side"]
        is_buy = side == "BUY"
        sl = float(trade["sl"])
        tp = float(trade.get("tp") or 0)
        if (is_buy and price <= sl) or ((not is_buy) and price >= sl):
            return {"action": "close",
                    "reason": f"🛑 ضرب الوقف ({self.cfg.get('sl_atr1h')}×ATR ساعة)"}
        if tp and ((is_buy and price >= tp) or ((not is_buy) and price <= tp)):
            tp_r = self.cfg.get("tp_r_buy") if is_buy else self.cfg.get("tp_r_sell")
            return {"action": "close", "reason": f"🎯 الهدف {tp_r}R محقق"}
        # ── 🛡️ وقف التعادل (جزء أساسي من التركيبة المعتمدة) ──
        self._derive_be_state(trade)
        if not trade.get("be_active"):
            be_trig = trade.get("be_trigger")
            be_px = trade.get("be_price")
            entry = float(trade.get("entry_price") or 0)
            if (be_trig is None or be_px is None) and entry > 0:
                # إعادة الاشتقاق من atr_ref المحفوظ (بعد إعادة تشغيل مثلاً)
                atr_v = float(trade.get("atr_ref") or 0)
                be_r = float(self.cfg.get("be_trigger_buy" if is_buy
                                          else "be_trigger_sell") or 0)
                if atr_v > 0 and be_r > 0:
                    risk = float(self.cfg.get("sl_atr1h")) * atr_v
                    if is_buy:
                        be_trig = entry + be_r * risk
                        be_px = entry * (1 + MARS_FEE) / (1 - MARS_FEE) * (1 + 1e-6)
                    else:
                        be_trig = entry - be_r * risk
                        be_px = entry * (1 - MARS_FEE) / (1 + MARS_FEE) * (1 - 1e-6)
                    trade["be_trigger"], trade["be_price"] = be_trig, be_px
            if be_trig is not None and be_px is not None:
                hit = price >= be_trig if is_buy else price <= be_trig
                if hit:
                    trade["be_active"] = True
                    be_r_txt = self.cfg.get("be_trigger_buy") if is_buy \
                        else self.cfg.get("be_trigger_sell")
                    return {"action": "move_sl", "sl": float(be_px),
                            "reason": f"🛡️ بلغ +{be_r_txt}R — نقل الوقف للتعادل"}
        held_min = (time.time() - float(trade.get("entry_time") or time.time())) / 60.0
        if held_min >= float(self.cfg["max_hold_minutes"]):
            return {"action": "close", "reason": "⏳ خروج زمني احترازي (7 أيام)"}
        return {"action": "hold"}


MARS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mars_trades (
    symbol TEXT PRIMARY KEY, side TEXT, entry REAL, sl REAL, tp1 REAL, atr REAL,
    entry_ts REAL, exit_ts REAL, pnl REAL, pnl_pct REAL, win INTEGER DEFAULT -1,
    reason TEXT, components TEXT, margin REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mars_daily (
    date TEXT PRIMARY KEY, pnl REAL, wins INTEGER, losses INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mars_entry ON mars_trades(entry_ts);
"""


class MarsDB:
    """قاعدة صفقات «موجات 7/25/99» — نفس واجهة TrendDB تماماً."""

    TABLE = 'mars_trades'

    def __init__(self, db_name=None):
        self.db_name = db_name or db_file

    async def init(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript(MARS_SCHEMA)
            await db.commit()

    async def open(self, t):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """INSERT OR REPLACE INTO mars_trades
                   (symbol, side, entry, sl, tp1, atr, entry_ts, margin, components)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (t["symbol"], t["side"], t["entry_price"], t["sl"], t.get("tp"),
                 t.get("atr_ref") or 0, t["entry_time"],
                 float(t.get("margin_usdt") or 0),
                 json.dumps(t.get("components", {}), ensure_ascii=False)))
            await db.commit()

    async def close(self, symbol, exit_ts, pnl, pnl_pct, win, reason):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """UPDATE mars_trades SET exit_ts=?, pnl=?, pnl_pct=?, win=?, reason=?
                   WHERE symbol=? AND win=-1""",
                (exit_ts, pnl, pnl_pct, int(win), str(reason)[:200], symbol))
            day = time.strftime("%Y-%m-%d", time.localtime(exit_ts))
            async with db.execute("SELECT pnl, wins, losses FROM mars_daily WHERE date=?",
                                  (day,)) as cur:
                row = await cur.fetchone()
            w, l = (1, 0) if win else (0, 1)
            if row:
                await db.execute("UPDATE mars_daily SET pnl=?, wins=?, losses=? WHERE date=?",
                                 (row[0] + pnl, row[1] + w, row[2] + l, day))
            else:
                await db.execute("INSERT INTO mars_daily VALUES (?,?,?,?)", (day, pnl, w, l))
            await db.commit()

    async def update_sl(self, symbol, sl):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mars_trades SET sl=? WHERE symbol=? AND win=-1", (sl, symbol))
            await db.commit()

    async def open_symbols(self):
        """استعادة صفقات الموجات المفتوحة بعد إعادة التشغيل."""
        out = {}
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """SELECT symbol, side, entry, sl, tp1, atr, entry_ts, margin
                       FROM mars_trades WHERE win=-1""") as cur:
                for r in await cur.fetchall():
                    out[r[0]] = {"symbol": r[0], "side": r[1], "entry": r[2], "sl": r[3],
                                 "tp1": r[4], "tp2": None, "atr": r[5], "entry_ts": r[6],
                                 "margin": r[7] or 0}
        return out

    async def summary(self, days=30):
        since = time.time() - days * 86400
        out = {"closed": 0, "wins": 0, "losses": 0, "winrate": 0.0, "net": 0.0,
               "pf": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "trades": [], "daily": []}
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    """SELECT COUNT(*) n, SUM(win=1) w, SUM(win=0) l, SUM(pnl) net,
                              AVG(CASE WHEN win=1 THEN pnl END) aw,
                              AVG(CASE WHEN win=0 THEN pnl END) al,
                              SUM(CASE WHEN win=1 THEN pnl ELSE 0 END) g,
                              SUM(CASE WHEN win=0 THEN -pnl ELSE 0 END) ls
                       FROM mars_trades WHERE win>=0 AND exit_ts>=?""", (since,)) as cur:
                r = await cur.fetchone()
            if r and r["n"]:
                n = r["n"]
                out.update({
                    "closed": n, "wins": int(r["w"] or 0), "losses": int(r["l"] or 0),
                    "winrate": round((r["w"] or 0) / n * 100, 2),
                    "net": round(r["net"] or 0.0, 2),
                    "pf": round((r["g"] or 0) / r["ls"], 3) if (r["ls"] or 0) > 0 else 999.0,
                    "avg_win": round(r["aw"] or 0.0, 2), "avg_loss": round(r["al"] or 0.0, 2),
                })
            async with db.execute(
                    """SELECT symbol, side, entry, exit_ts, pnl, pnl_pct, win, reason
                       FROM mars_trades WHERE win>=0 ORDER BY exit_ts DESC LIMIT 60""") as cur:
                out["trades"] = [dict(x) for x in await cur.fetchall()]
            async with db.execute(
                    "SELECT date, pnl, wins, losses FROM mars_daily ORDER BY date DESC LIMIT 30") as cur:
                out["daily"] = [{"date": x[0], "pnl": round(x[1] or 0, 2), "wins": x[2],
                                 "losses": x[3]} for x in await cur.fetchall()]
        return out


# ══════════════════════════════════════════════════════════════════════
#  ⚙️ المحرك الأساسي — (تنفيذ، وقف على المنصة، مصالحة ذاتية، شفاء ذاتي)
#     + توجيه استراتيجيتين
# ══════════════════════════════════════════════════════════════════════
class DualStrategyBot:
    STRATEGY_LABELS = {'TREND': '🚀 راكب الترند', 'MARS': '📐 موجات 7/25/99'}

    def __init__(self):
        self.binance_api_key = os.environ.get('BINANCE_API_KEY', '')
        self.binance_api_secret = os.environ.get('BINANCE_API_SECRET', '')

        self.TRADE_ENABLED = os.environ.get('TRADE_ENABLED', 'false').lower() == 'true'
        self.LEVERAGE = 10
        self.TRADE_SIZE_USDT = float(os.environ.get('TRADE_SIZE_USDT', '14'))
        self.TESTNET = os.environ.get('TESTNET', 'false').lower() == 'true'

        # سعة الصفقات: مستقلة تماماً لكل استراتيجية — لا يوجد سقف إجمالي مشترك.
        # كل استراتيجية يتحكم في سقفها متغير بيئتها فقط:
        #   MAX_OPEN_TRADES_TREND (راكب الترند) | MAX_OPEN_TRADES_MARS (الموجات)
        self.max_open_trend = int(os.environ.get('MAX_OPEN_TRADES_TREND', '5'))
        self.max_open_mars = int(os.environ.get('MAX_OPEN_TRADES_MARS', '5'))
        # هامش مستقل لكل استراتيجية (0 = يستخدم TRADE_SIZE_USDT المشترك)
        self.trade_size_trend = float(os.environ.get('TRADE_SIZE_USDT_TREND', '0'))
        self.trade_size_mars = float(os.environ.get('TRADE_SIZE_USDT_MARS', '0'))

        # ✅ تحقق صارم من الإعدادات — فشل سريع وواضح بدل التشغيل المعطوب
        problems = []
        if self.TRADE_SIZE_USDT <= 0:
            problems.append("TRADE_SIZE_USDT يجب أن يكون أكبر من صفر")
        if not (1 <= self.max_open_trend <= 20):
            problems.append("MAX_OPEN_TRADES_TREND يجب أن يكون بين 1 و 20")
        if not (1 <= self.max_open_mars <= 20):
            problems.append("MAX_OPEN_TRADES_MARS يجب أن يكون بين 1 و 20")
        if self.TESTNET:
            logger.info("🧪 وضع Testnet التجريبي مفعّل")
        if problems:
            raise SystemExit("❌ إعدادات خاطئة:\n- " + "\n- ".join(problems))

        if self.TRADE_ENABLED and (not self.binance_api_key or not self.binance_api_secret):
            self.TRADE_ENABLED = False
            logger.error("❌ التداول مفعّل لكن مفاتيح API ناقصة! التحويل للمراقبة فقط")

        # ثوابت حماية تشغيلية
        self.PRICE_MAX_AGE = 30
        self.REENTRY_COOLDOWN = 900
        self.VERIFY_EVERY_N_LOOPS = 5
        self.WS_STALE_ALERT = 120
        self.BALANCE_CACHE_SECONDS = 60

        self.data_url = "https://fapi.binance.com"
        self.trade_url = ("https://testnet.binancefuture.com" if self.TESTNET
                          else "https://fapi.binance.com")
        self.time_offset_ms = 0

  
        # ✅ مسار واحد موحّد للقواعد الثلاث (المشتركة + الترند + الموجات)
        self.db = DatabaseManager(db_file)
        self.trend = TrendStrategy(None, logger.warning)
        self.trend_exit = TrendExitManager(None, logger.warning)
        self.trend_db = TrendDB(db_file)
        self.mars = MaRsiStrategy(None, logger.warning)
        self.mars_exit = MaRsiExitManager(None, logger.warning)
        self.mars_db = MarsDB(db_file)
        self.port = int(os.environ.get('PORT', '10000'))

        self.session = None
        self.ws_task = None
        self._shutdown_requested = False

        self.all_futures_pairs = []
        self.step_sizes_cache = {}
        self.tick_sizes_cache = {}
        self.min_qty_cache = {}
        self.max_qty_cache = {}
        self.min_notional_cache = {}
        self.live_prices = {}
        self.active_trades = {}
        self.trend_pending = {}   # أوامر «وقف فوق شمعة الإشارة» المعلقة (TREND): symbol → بيانات الأمر
        self.reentry_cooldown = {}
        self.EMERGENCY_MODE = False   # يمنع أي دخول حتى إلغاء صريح من اللوحة
        self.error_counts = {}
        self.last_discovery_alert = {}
        self.entry_history = collections.deque(maxlen=200)   # (ts, date) لحساب صفقات اليوم
        self.last_scan_info = None
        self._last_heartbeat = 0
        self._report_day = time.strftime("%Y-%m-%d")
        self._balance_cache = (0.0, 0.0)

        # دوران المسح المستقل لكل استراتيجية + سجل حي لكل استراتيجية
        self._trend_cursor = 0
        self._mars_cursor = 0
        self.trend_events = collections.deque(maxlen=300)
        self.mars_events = collections.deque(maxlen=300)

        # السعة الفعلية (قد تُحدَّث من الإعدادات المحفوظة في القاعدة عند الإقلاع)
        self.trend_capacity = self.max_open_trend
        self.mars_capacity = self.max_open_mars

        self.stats = {'total_scans': 0, 'trades_executed': 0}
        self.stats_trend = {'wins': 0, 'losses': 0, 'trades': 0}
        self.stats_mars = {'wins': 0, 'losses': 0, 'trades': 0}

    # ═══ أدوات الاستراتيجيات ═══
    def strategy_cfg(self, key):
        return self.trend.cfg if key == 'TREND' else self.mars.cfg

    def strategy_exit(self, key):
        return self.trend_exit if key == 'TREND' else self.mars_exit

    def strategy_events(self, key):
        return self.trend_events if key == 'TREND' else self.mars_events

    def strategy_stats(self, key):
        return self.stats_trend if key == 'TREND' else self.stats_mars

    def strategy_margin(self, key):
        if key == 'TREND':
            return self.trade_size_trend if self.trade_size_trend > 0 else self.TRADE_SIZE_USDT
        return self.trade_size_mars if self.trade_size_mars > 0 else self.TRADE_SIZE_USDT

    def strategy_capacity(self, key):
        return self.trend_capacity if key == 'TREND' else self.mars_capacity

    @staticmethod
    def other_strategy(key):
        return 'MARS' if key == 'TREND' else 'TREND'

    def count_open(self, key):
        return sum(1 for t in self.active_trades.values() if t.get('strategy') == key)

    def _log_event(self, key, kind, msg):
        """تسجيل حركة في سجل الاستراتيجية (يظهر في تبويب الحركات بلوحتها فقط)."""
        try:
            self.strategy_events(key).append({"ts": time.time(), "kind": kind, "msg": msg})
        except Exception:
            pass

    # ═══ نظام مكافحة الصمت ═══
    def _notify_error(self, source, exc=None, context=""):
        count = self.error_counts.get(source, 0) + 1
        self.error_counts[source] = count
        txt = f"⚠️ {source}" + (f" — {context}" if context else "")
        if exc is not None:
            txt += f" | `{str(exc)[:100]}`"
        logger.warning(f"{txt} (تكرار #{count})")
        if count == 1 or count % 10 == 0:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.tg(f"{txt}\n🔢 مرات التكرار: {count}"))
            except RuntimeError:
                pass

    def _reset_error(self, source):
        self.error_counts.pop(source, None)

    def fmt_price(self, price):
        if price is None or price == 0: return "$0"
        if price < 0.00001: return f"${price:.10f}"
        elif price < 0.001: return f"${price:.6f}"
        elif price < 1: return f"${price:.4f}"
        elif price < 100: return f"${price:.2f}"
        else: return f"${price:,.1f}"

    async def tg(self, msg):
        """كل إشعار يذهب للوحة (طبقة عرض) — نفس واجهة الملف الأصلي"""
        try:
            first_line = msg.split('\n')[0].replace('*', '').strip()
            kind = 'info'
            if msg.startswith('✅') or 'صفقة منفذة' in msg or 'صفقة جديدة' in msg: kind = 'trade'
            elif msg.startswith('🎯') or 'جني' in first_line: kind = 'partial'
            elif msg.startswith('🏁') or 'إغلاق' in first_line: kind = 'close'
            elif msg.startswith('🚨') or 'خطأ' in first_line or msg.startswith('⚠️'): kind = 'error'
            elif msg.startswith('🛑'): kind = 'system'
            await panel_notify(kind, first_line, msg, 'info')
        except Exception:
            pass

    # ═══ توقيت الخادم (علاج خطأ -1021 الشهير) ═══
    async def sync_server_time(self):
        try:
            res = await self._fapi_request('GET', '/fapi/v1/time')
            if res and 'serverTime' in res:
                self.time_offset_ms = int(res['serverTime']) - int(time.time() * 1000)
                logger.info(f"🕐 مزامنة وقت الخادم: إزاحة {self.time_offset_ms}ms")
        except Exception as e:
            logger.warning(f"تعذر مزامنة وقت الخادم: {e}")

    def _sign(self, params):
        params['timestamp'] = int(time.time() * 1000) + self.time_offset_ms
        params['recvWindow'] = 5000
        query = urlencode(params)
        params['signature'] = hmac.new(
            self.binance_api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return params

    async def _fapi_request(self, method, endpoint, params=None, signed=False, retries=3, quiet=(), soft=()):
        for attempt in range(retries):
            try:
                url = f"{self.trade_url}{endpoint}"
                headers = {'X-MBX-APIKEY': self.binance_api_key} if signed else {}
                req_params = self._sign(dict(params) if params else {}) if signed else params

                async with self.session.request(method, url, params=req_params,
                                                headers=headers, timeout=15) as r:
                    if r.status == 200:
                        return await r.json()
                    body = await r.text()
                    if r.status in (429, 418):
                        await asyncio.sleep(10 * (attempt + 1))
                        continue
                    if r.status == 401:
                        self._notify_error("خطأ 401 من Binance", context="مفاتيح API خاطئة أو مقيدة بـIP")
                        return None
                    if '-1021' in body:  # توقيت غير متزامن → مزامنة وإعادة
                        logger.warning("⚠️ خطأ توقيم -1021 — مزامنة الوقت وإعادة المحاولة")
                        await self.sync_server_time()
                        await asyncio.sleep(1)
                        continue
                    if r.status >= 500:
                        logger.warning(f"Futures API {r.status} — إعادة محاولة...")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    for c in soft:
                        if str(c) in body:
                            return {'_soft_code': c}
                    if any(str(c) in body for c in quiet):
                        return None
                    logger.warning(f"Futures API Error {r.status}: {body[:120]}")
                    return None
            except asyncio.TimeoutError:
                if attempt == retries - 1:
                    self._notify_error("انتهت مهلة طلب Binance", context=endpoint)
                    return None
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                if attempt == retries - 1:
                    self._notify_error("فشل طلب Binance", exc=e, context=endpoint)
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def setup_futures_account(self):
        msg = f"⚙️ *إعداد حساب العقود الآجلة (الرافعة {self.LEVERAGE}x)*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        setup_count = 0
        for pair in self.all_futures_pairs[:50]:
            symbol = pair['symbol']
            try:
                lev_res = await self._fapi_request('POST', '/fapi/v1/leverage',
                    {'symbol': symbol, 'leverage': self.LEVERAGE}, signed=True)
                await self._fapi_request('POST', '/fapi/v1/marginType',
                    {'symbol': symbol, 'marginType': 'ISOLATED'}, signed=True, quiet=(-4046,))
                if lev_res and lev_res.get('leverage') == self.LEVERAGE:
                    setup_count += 1
            except Exception as e:
                logger.debug(f"تخطي إعداد {symbol}: {e}")
            await asyncio.sleep(0.15)
        msg += f"✅ تم ضبط الرافعة والهامش المعزول لـ {setup_count} زوج"
        await self.tg(msg)

    async def load_market_data(self):
        data = await self._fapi_request('GET', '/fapi/v1/exchangeInfo')
        if not data: return
        new_pairs = []
        for s in data.get('symbols', []):
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING' and s['contractType'] == 'PERPETUAL':
                new_pairs.append({'symbol': s['symbol'], 'baseAsset': s['baseAsset']})
                for f in s.get('filters', []):
                    if f['filterType'] == 'LOT_SIZE':
                        self.step_sizes_cache[s['symbol']] = float(f['stepSize'])
                        self.min_qty_cache[s['symbol']] = float(f.get('minQty', f['stepSize']))
                        self.max_qty_cache[s['symbol']] = float(f.get('maxQty', 1e12))
                    elif f['filterType'] == 'PRICE_FILTER':
                        self.tick_sizes_cache[s['symbol']] = float(f['tickSize'])
                    elif f['filterType'] == 'MIN_NOTIONAL':
                        self.min_notional_cache[s['symbol']] = float(f.get('notional', f.get('minNotional', 5.0)))
        self.all_futures_pairs = new_pairs
        logger.info(f"📊 تم تحميل {len(self.all_futures_pairs)} زوج عقود آجلة")

    # ═══ أدوات التنسيق الدقيق ═══
    @staticmethod
    def _decimals_of(step):
        try:
            exp = Decimal(str(step)).normalize().as_tuple().exponent
            return max(0, -exp)
        except Exception:
            return 8

    def _step_qty(self, symbol, qty):
        step = self.step_sizes_cache.get(symbol) or 1.0
        if step <= 0: step = 1.0
        dec = self._decimals_of(step)
        return round(math.floor(round(qty / step, 9)) * step, dec)

    def format_quantity(self, symbol, qty):
        return self._step_qty(symbol, qty)

    def qty_to_str(self, symbol, qty):
        step = self.step_sizes_cache.get(symbol) or 1.0
        dec = self._decimals_of(step)
        return f"{self._step_qty(symbol, qty):.{dec}f}"

    def price_to_str(self, symbol, price):
        tick = self.tick_sizes_cache.get(symbol)
        if not tick or tick <= 0:
            if price >= 100: dec = 2
            elif price >= 1: dec = 4
            elif price >= 0.01: dec = 6
            else: dec = 8
            return f"{price:.{dec}f}"
        dec = self._decimals_of(tick)
        stepped = math.floor(round(price / tick, 9)) * tick
        return f"{round(stepped, dec):.{dec}f}"

    def get_price(self, symbol):
        p = self.live_prices.get(symbol)
        if p and (time.time() - p.get('ts', 0)) <= self.PRICE_MAX_AGE:
            return p
        return None

    def set_cooldown(self, symbol):
        self.reentry_cooldown[symbol] = time.time() + self.REENTRY_COOLDOWN

    def is_in_cooldown(self, symbol):
        expiry = self.reentry_cooldown.get(symbol, 0)
        if time.time() < expiry: return True
        self.reentry_cooldown.pop(symbol, None)
        return False

    async def get_available_usdt(self):
        now = time.time()
        cached_val, cached_ts = self._balance_cache
        if now - cached_ts < self.BALANCE_CACHE_SECONDS and cached_ts > 0:
            return cached_val
        res = await self._fapi_request('GET', '/fapi/v2/balance', signed=True)
        avail = 0.0
        if isinstance(res, list):
            for b in res:
                if b.get('asset') == 'USDT':
                    avail = float(b.get('availableBalance', 0))
                    break
        self._balance_cache = (avail, now)
        return avail

    # ═══ WebSocket ═══
    async def ws_manager(self):
        ws_url = ("wss://stream.binancefuture.com/ws/!bookTicker" if self.TESTNET
                  else "wss://fstream.binance.com/ws/!bookTicker")
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20) as ws:
                    logger.info("✅ Futures WebSocket متصل (Global Mode)!")
                    self._reset_error("انقطاع WebSocket")
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if 's' in data and 'b' in data and 'a' in data:
                                self.live_prices[data['s']] = {
                                    'bid': float(data['b']), 'ask': float(data['a']),
                                    'ts': time.time()}
                        except (ValueError, KeyError, TypeError):
                            continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._notify_error("انقطاع WebSocket", exc=e, context="إعادة الاتصال خلال 5 ثوانٍ")
                await asyncio.sleep(5)

    async def get_klines(self, symbol, interval='15m', limit=100):
        data = await self._fapi_request('GET', '/fapi/v1/klines',
            {'symbol': symbol, 'interval': interval, 'limit': limit})
        if data and len(data) > 20:
            df = pd.DataFrame(data, columns=[
                'time','open','high','low','close','volume',
                'close_time','quote_volume','trades','taker_buy_vol',
                'taker_buy_quote_vol','ignore'])
            for col in ['open','high','low','close','volume','quote_volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        return None

    @staticmethod
    def _compute_atr(df, period=14):
        hl = df['high'] - df['low']
        hc = (df['high'] - df['close'].shift()).abs()
        lc = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    # ═══ المسح الدوراني: كل استراتيجية تدور على الأزواج باستقلال ═══
    def _rotation_candidates(self, cursor_attr, limit):
        """دوران على كل أزواج العقود حتى تُغطّى كلها داخل نافذة الدخول."""
        pairs = [p['symbol'] for p in self.all_futures_pairs]
        if not pairs:
            return []
        n = len(pairs)
        start = getattr(self, cursor_attr) % n
        setattr(self, cursor_attr, (start + int(limit)) % n)
        out = []
        for k in range(min(int(limit), n)):
            sym = pairs[(start + k) % n]
            if sym not in self.active_trades:
                out.append(sym)
        return out

    async def _scan_strategy(self, key):
        strat = self.trend if key == 'TREND' else self.mars
        if not strat.cfg.get('enabled'):
            return
        if self.count_open(key) >= self.strategy_capacity(key):
            return
        try:
            cursor = '_trend_cursor' if key == 'TREND' else '_mars_cursor'
            candidates = self._rotation_candidates(cursor, int(strat.cfg['scan_limit']))
            if not candidates:
                return
            sigs = await strat.scan(self, candidates, set(self.active_trades),
                                    self.reentry_cooldown)
            if sigs:
                self._log_event(key, 'SCAN',
                                f"🔍 {len(sigs)} إشارة من {len(candidates)} زوجاً مفحوصاً")
            for a in sigs:
                if key == 'TREND' and a.get('pending_entry'):
                    await self._arm_trend_pending(a)
                    await asyncio.sleep(1)
                    continue
                await self.execute_trade(a)
                await asyncio.sleep(1)
        except Exception as e:
            self._notify_error(f"خطأ مسح استراتيجية {self.STRATEGY_LABELS[key]}", exc=e)

    async def scan_volatile_coins(self):
        """مسح الاستراتيجيتين معاً — كل واحدة بقواعدها وسعتها ودورانها الخاص."""
        if self.EMERGENCY_MODE or not self.TRADE_ENABLED:
            return
        await self._scan_strategy('TREND')
        await self._scan_strategy('MARS')
        self.last_scan_info = {
            'ts': time.time(),
            'trend': dict(getattr(self.trend, 'last_scan', {}) or {}),
            'mars': dict(getattr(self.mars, 'last_scan', {}) or {}),
        }

    # ═══ أوامر «وقف فوق شمعة الإشارة» المعلقة (طريقة دخول راكب الترند) ═══
    async def _arm_trend_pending(self, analysis):
        """تسليح أمر الدخول المعلق: انتظار لمس أعلى/أدنى شمعة الإشارة خلال الصلاحية."""
        sym = analysis['symbol']
        if sym in self.active_trades or sym in self.trend_pending:
            return
        if self.count_open('TREND') >= self.strategy_capacity('TREND'):
            return
        self.trend_pending[sym] = {
            'symbol': sym, 'side': analysis['direction'],
            'trigger': float(analysis['trigger_price']),
            'expires_at': float(analysis['expires_at']),
            'atr': float(analysis.get('atr_ref') or 0.0),
            'analysis': analysis, 'armed_ts': time.time(),
        }
        self._log_event('TREND', 'PEND',
                        f"⏳ {sym} {analysis['direction']} — أمر وقف على شمعة الإشارة @ "
                        f"{self.fmt_price(analysis['trigger_price'])} | صلاحية حتى "
                        f"{time.strftime('%H:%M', time.localtime(analysis['expires_at']))} — بلا لمس يُلغى")
        # لمس فوري (سعر تجاوز المُشغّل لحظة التسليح) — مطابق لمعالجة الفجوات في الاختبار
        await self._check_one_pending(sym)

    async def _check_one_pending(self, sym):
        p = self.trend_pending.get(sym)
        if not p:
            return
        now = time.time()
        if now > p['expires_at']:
            del self.trend_pending[sym]
            self._log_event('TREND', 'PEND',
                            f"⌛ {sym} انتهت صلاحية الأمر بلا لمس — إشارة ملغاة (اختراق ضعيف)")
            return
        if sym in self.active_trades:
            del self.trend_pending[sym]
            return
        if not self.TRADE_ENABLED or self.EMERGENCY_MODE:
            return
        if self.is_in_cooldown(sym):
            return   # التبريد يمنع الدخول — يُعاد الفحص في الدورة التالية حتى انتهاء الصلاحية
        if self.count_open('TREND') >= self.strategy_capacity('TREND'):
            return   # يبقى معلقاً حتى تفرغ خانة قبل انتهاء صلاحيته
        prices = self.get_price(sym)
        if not prices:
            return
        if p['side'] == 'BUY':
            touched, px = prices['ask'] >= p['trigger'], prices['ask']
        else:
            touched, px = prices['bid'] <= p['trigger'], prices['bid']
        if not touched:
            return
        del self.trend_pending[sym]
        await self._fill_trend_pending(p, px)

    async def _fill_trend_pending(self, p, px):
        """تنفيذ اللمس: إعادة حساب الوقف/الهدف من سعر التنفيذ الفعلي (مطابق لمحرك الاختبار)."""
        base = dict(p['analysis'])
        cfg = self.trend.cfg
        risk = float(cfg['sl_atr1h']) * float(p.get('atr') or 0.0)
        if risk <= 0:
            return
        if p['side'] == 'BUY':
            sl, tp1 = px - risk, px + float(cfg['tp1_r']) * risk
        else:
            sl, tp1 = px + risk, px - float(cfg['tp1_r']) * risk
        base.update({
            'price': px, 'sl': sl, 'tp1': tp1, 'pending_entry': False,
            'components': dict(base.get('components', {}),
                               trigger=f"اختراق {int(cfg['donch'])} ساعة + لمس "
                                       f"{'أعلى' if p['side'] == 'BUY' else 'أدنى'} شمعة الإشارة"),
        })
        self._log_event('TREND', 'PEND',
                        f"✅ {p['symbol']} لمس المُشغّل {self.fmt_price(p['trigger'])} — "
                        f"تنفيذ السوق @ {self.fmt_price(px)}")
        await self.execute_trade(base)

    async def check_trend_pending(self):
        """مراقبة أوامر «وقف فوق شمعة الإشارة» المعلقة — تُستدعى كل دورة (~60 ثانية)."""
        if not self.trend_pending:
            return
        for sym in list(self.trend_pending.keys()):
            try:
                await self._check_one_pending(sym)
            except Exception as e:
                self._notify_error(f"خطأ مراقبة أمر معلق {sym}", exc=e)

    # ═══ التنفيذ (بإعدادات الاستراتيجية: هامش وسعة مستقلان) ═══
    async def execute_trade(self, analysis):
        if not self.TRADE_ENABLED: return
        if self.EMERGENCY_MODE: return
        strategy = analysis.get('strategy')
        if strategy not in ('TREND', 'MARS'):
            return   # لا دخول إلا بهوية استراتيجية صريحة

        symbol = analysis['symbol']
        if symbol in self.active_trades: return
        if self.is_in_cooldown(symbol): return

        margin = self.strategy_margin(strategy)
        if self.count_open(strategy) >= self.strategy_capacity(strategy): return

        # ✅ فحص الرصيد المتاح (بذاكرة مؤقتة 60 ثانية)
        available = await self.get_available_usdt()
        if available < margin * 1.2:
            self._notify_error("رصيد غير كافٍ للدخول",
                               context=f"المتاح {available:.2f}$ < المطلوب {margin * 1.2:.2f}$")
            return

        notional = margin * self.LEVERAGE
        quantity = self.format_quantity(symbol, notional / analysis['price'])
        if quantity <= 0: return
        if quantity < self.min_qty_cache.get(symbol, 0.0): return
        if quantity > self.max_qty_cache.get(symbol, 1e12): return
        if quantity * analysis['price'] < self.min_notional_cache.get(symbol, 5.0) * 1.02:
            return

        await self._fapi_request('POST', '/fapi/v1/leverage',
            {'symbol': symbol, 'leverage': self.LEVERAGE}, signed=True)
        await self._fapi_request('POST', '/fapi/v1/marginType',
            {'symbol': symbol, 'marginType': 'ISOLATED'}, signed=True, quiet=(-4046,))

        side = 'BUY' if analysis['direction'] == 'BUY' else 'SELL'
        result = await self._fapi_request('POST', '/fapi/v1/order', {
            'symbol': symbol, 'side': side, 'type': 'MARKET',
            'quantity': self.qty_to_str(symbol, quantity)
        }, signed=True)

        if not result or result.get('status') not in ['FILLED', 'NEW']:
            await self.tg(f"❌ *فشل تنفيذ {side} (`{symbol}`)*\n⚠️ تأكد من إعدادات العقود الآجلة وصلاحيات المفتاح")
            return

        avg = float(result.get('avgPrice') or 0)
        entry_price = avg if avg > 0 else analysis['price']

        trade_data = {
            'symbol': symbol, 'side': side, 'entry_price': entry_price,
            'quantity': quantity, 'sl': analysis['sl'], 'tp': analysis['tp1'],
            'tp2': analysis.get('tp2'),
            'score': analysis.get('score', 8),
            'trailing_active': False, 'highest_price': entry_price,
            'lowest_price': entry_price, 'entry_time': time.time(),
            'partial_closed': False, 'realized_pnl': 0.0,
            'stop_order_id': None, 'tp_order_id': None,
            'stop_is_algo': False, 'tp_is_algo': False,
            'stop_synced_price': None, 'tp_skipped': False,
            'strategy': strategy, 'margin_usdt': margin,
            'atr_ref': analysis.get('atr_ref'),
            'be_active': False,
            'be_trigger': analysis.get('be_trigger'),
            'be_price': analysis.get('be_price'),
            'components': analysis.get('components', {}),
            }
        self.active_trades[symbol] = trade_data
        await self.db.save_trade(trade_data)
        self.stats['trades_executed'] += 1
        self.strategy_stats(strategy)['trades'] += 1
        self.entry_history.append((time.time(), time.strftime("%Y-%m-%d")))
        await self.db.log_signal(symbol, side, trade_data['entry_time'],
                                 analysis.get('score', 8), analysis.get('components', {}))

        prices = self.get_price(symbol)
        ref_price = (prices['bid'] if side == 'BUY' else prices['ask']) if prices else entry_price
        await self._sync_stop_order(trade_data, ref_price)
        # 📐 موجات 7/25/99: تثبيت الهدف على المنصة أيضاً (ينجو من انهيار البوت)
        if strategy == 'MARS' and trade_data.get('tp'):
            await self._place_tp_order(trade_data, ref_price,
                                       target=trade_data['tp'], qty=trade_data['quantity'])
        await self.db.save_trade(trade_data)

        # تبريد إعادة الدخول بحسب إعداد الاستراتيجية
        try:
            cd = int(self.strategy_cfg(strategy).get('reentry_cooldown', 3600))
        except Exception:
            cd = 3600
        self.reentry_cooldown[symbol] = time.time() + cd

        if strategy == 'TREND':
            try:
                await self.trend_db.open(trade_data)
            except Exception as e:
                logger.warning(f"تعذر تسجيل صفقة الترند: {e}")
        else:
            try:
                await self.mars_db.open(trade_data)
            except Exception as e:
                logger.warning(f"تعذر تسجيل صفقة الموجات: {e}")

        risk = abs(analysis['price'] - analysis['sl'])
        self._log_event(strategy, 'ENTRY',
                        f"{symbol} {analysis['direction']} @ {self.fmt_price(analysis['price'])} | "
                        f"وقف {self.fmt_price(analysis['sl'])} ({risk / analysis['price'] * 100:.2f}%) | "
                        f"هدف {self.fmt_price(analysis['tp1'])} | مخاطرة {risk * (quantity or 0):.3f}$")
        label = self.STRATEGY_LABELS[strategy]
        await self.tg(f"{label} — *صفقة جديدة*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                      f"🪙 `{symbol}` | رافعة {self.LEVERAGE}x | هامش {margin:.0f}$\n"
                      f"💵 الدخول: {self.fmt_price(entry_price)}\n"
                      f"🛑 SL: {self.fmt_price(analysis['sl'])}\n"
                      f"🎯 الهدف: {self.fmt_price(analysis['tp1'])}\n"
                      f"📋 " + " | ".join(analysis.get('signals_smc', [])[:2]))

    # ═══ أوامر المنصة الشرطية (Algo Order API) ═══
    @staticmethod
    def _find_order_id(data):
        """البحث المتكرر عن algoId/orderId في أي شكل استجابة (إنتاج/تجريبي)"""
        if isinstance(data, dict):
            for k in ('algoId', 'orderId', 'algoID', 'orderID'):
                v = data.get(k)
                if v:
                    return v
            for v in data.values():
                r = DualStrategyBot._find_order_id(v)
                if r:
                    return r
        elif isinstance(data, list):
            for v in data:
                r = DualStrategyBot._find_order_id(v)
                if r:
                    return r
        return None

    async def _place_algo_order(self, params):
        """تثبيت أمر شرطي (ستوب/هدف) عبر Algo Order API.
        العائد: معرف رقمي عند النجاح | 'EXISTS' إذا كان موجوداً (-4130) |
        'UNKNOWN' عند نجاح 200 بلا معرف (سلوك Testnet) | None عند فشل حقيقي"""
        payload = {'algoType': 'CONDITIONAL'}
        payload.update(params)
        res = await self._fapi_request('POST', '/fapi/v1/algoOrder', payload,
                                       signed=True, soft=(-4130,))
        if isinstance(res, dict):
            if '_soft_code' in res:
                return 'EXISTS' if res['_soft_code'] == -4130 else None
            oid = self._find_order_id(res)
            if oid:
                return oid
            return 'UNKNOWN'
        return None

    async def _cancel_algo_order(self, symbol, algo_id):
        await self._fapi_request('DELETE', '/fapi/v1/algoOrder',
            {'symbol': symbol, 'algoId': algo_id}, signed=True, quiet=('-2011', '-2013'))

    # ═══ مزامنة الستوب: وضع الجديد أولاً ثم حذف القديم (لا فجوة حماية أبداً) ═══
    async def _sync_stop_order(self, trade, current_price):
        symbol = trade['symbol']
        is_buy = trade['side'] == 'BUY'
        desired = trade['sl']
        if desired is None: return False

        if current_price and ((is_buy and desired >= current_price) or (not is_buy and desired <= current_price)):
            return False

        desired_str = self.price_to_str(symbol, desired)
        if trade.get('stop_order_id') and trade.get('stop_synced_price') is not None:
            if self.price_to_str(symbol, trade['stop_synced_price']) == desired_str:
                return False

        stop_side = 'SELL' if is_buy else 'BUY'
        new_id = await self._place_algo_order({
            'symbol': symbol, 'side': stop_side, 'type': 'STOP_MARKET',
            'triggerPrice': desired_str, 'closePosition': 'true',
            'workingType': 'CONTRACT_PRICE'})

        if new_id:
            old_id = trade.get('stop_order_id')          # ✅ الجديد حي الآن — احذف القديم بأمان
            if old_id:
                await self._cancel_algo_order(symbol, old_id)
            trade['stop_is_algo'] = True
            trade['stop_synced_price'] = desired
            if new_id in ('EXISTS', 'UNKNOWN'):
                trade['stop_order_id'] = None
                self._reset_error(f"ستوب المنصة {symbol}")
                logger.info(f"🛡️ ستوب {symbol} مؤكد على المنصة (معرف غير متاح من Testnet)")
                return True
            trade['stop_order_id'] = new_id
            self._reset_error(f"ستوب المنصة {symbol}")
            return True

        self._notify_error(f"تعذّر وضع ستوب المنصة لـ {symbol}",
                           context="سيُعاد — الوقف المحلي يعمل")
        return False

    # ═══ تثبيت هدف TAKE_PROFIT_MARKET على المنصة ═══
    async def _place_tp_order(self, trade, current_price, target=None, qty=None):
        symbol = trade['symbol']
        is_buy = trade['side'] == 'BUY'
        if trade.get('tp_order_id') or trade.get('tp_skipped') or trade.get('tp_unconfirmed'):
            return
        tp = target if target is not None else trade.get('tp2')
        if not tp: return
        if (is_buy and tp <= current_price) or (not is_buy and tp >= current_price):
            trade['tp_skipped'] = True
            return
        close_side = 'SELL' if is_buy else 'BUY'
        quantity = qty if qty is not None else trade['quantity']
        new_id = await self._place_algo_order({
            'symbol': symbol, 'side': close_side, 'type': 'TAKE_PROFIT_MARKET',
            'triggerPrice': self.price_to_str(symbol, tp),
            'quantity': self.qty_to_str(symbol, quantity),
            'reduceOnly': 'true',
            'workingType': 'CONTRACT_PRICE'})
        if new_id:
            trade['tp_is_algo'] = True
            if new_id in ('EXISTS', 'UNKNOWN'):
                trade['tp_order_id'] = None
                trade['tp_unconfirmed'] = True
            else:
                trade['tp_order_id'] = new_id
            await self.tg(f"🎯 *هدف مثبّت على المنصة* (`{symbol}`) عند {self.fmt_price(tp)}")
        else:
            trade['tp_skipped'] = True
            self._notify_error(f"تعذر تثبيت الهدف لـ {symbol}",
                               context="المراقبة المحلية ستدير الخروج بدلاً منه")

    # ═══ استعلامات المنصة ═══
    async def get_position_amt(self, symbol):
        try:
            res = await self._fapi_request('GET', '/fapi/v2/positionRisk',
                {'symbol': symbol}, signed=True)
            if isinstance(res, list) and res:
                return float(res[0].get('positionAmt', 0))
        except Exception as e:
            logger.warning(f"فشل استعلام المركز لـ {symbol}: {e}")
        return None

    async def get_last_realized_pnl(self, symbol, trade):
        try:
            res = await self._fapi_request('GET', '/fapi/v1/income',
                {'symbol': symbol, 'incomeType': 'REALIZED_PNL', 'limit': 20}, signed=True)
            if isinstance(res, list) and res:
                entry_ms = int(trade.get('entry_time', 0) * 1000)
                last = None
                for e in res:
                    if int(e.get('time', 0)) >= entry_ms - 5000:
                        last = e
                        break
                if last is not None:
                    return float(last.get('income', 0))
        except Exception as e:
            logger.warning(f"فشل جلب الأرباح المحققة لـ {symbol}: {e}")
        return None

    # ملخص مالي اليوم من المنصة مباشرة — صافي الربح بعد الرسوم والتمويل
    async def get_income_summary(self, day_start_ms=None):
        if day_start_ms is None:
            day_str = time.strftime('%Y-%m-%d')
            day_start_ms = int(time.mktime(time.strptime(day_str, '%Y-%m-%d')) * 1000)
        out = {'ok': False, 'realized': 0.0, 'commission': 0.0,
               'funding': 0.0, 'net': 0.0, 'n_income': 0}
        try:
            for typ, key in (('REALIZED_PNL', 'realized'),
                             ('COMMISSION', 'commission'),
                             ('FUNDING_FEE', 'funding')):
                res = await self._fapi_request('GET', '/fapi/v1/income',
                    {'incomeType': typ, 'startTime': int(day_start_ms), 'limit': 1000},
                    signed=True)
                if isinstance(res, list):
                    out[key] = sum(float(e.get('income', 0)) for e in res
                                   if isinstance(e, dict))
                    out['n_income'] += len(res)
            out['net'] = out['realized'] + out['funding'] + out['commission']
            out['ok'] = True
        except Exception as e:
            out['error'] = str(e)
        return out

    # ✅ إيقاف آمن (أُصلح: نسخة واحدة فقط — زر اللوحة يعمل الآن فعلاً)
    async def request_shutdown(self, source='panel'):
        if self._shutdown_requested:
            return False
        self._shutdown_requested = True
        logger.info(f"🛑 طلب إيقاف آمن من: {source}")
        try:
            await self.tg("🛑 *إيقاف آمن:* ستوب/أوامر الهدف على المنصة تبقى فعالة وتحمي المراكز.")
        except Exception:
            pass
        return True

    async def verify_positions(self):
        if not self.TRADE_ENABLED or not self.binance_api_key:
            return
        if not self.active_trades: return
        for symbol, trade in list(self.active_trades.items()):
            try:
                amt = await self.get_position_amt(symbol)
                if amt is None: continue
                step = self.step_sizes_cache.get(symbol) or 1.0
                if abs(amt) < step:
                    pnl = await self.get_last_realized_pnl(symbol, trade)
                    prices = self.get_price(symbol)
                    px = (prices['bid'] if trade['side'] == 'BUY' else prices['ask']) if prices else trade['entry_price']
                    await self._finalize_trade(trade, px, "🛑 أُغلق على المنصة (Stop/TP)", pnl)
            except Exception as e:
                self._notify_error(f"فشل التحقق من مركز {symbol}", exc=e)

    # ═══ إغلاق آمن بالكمية الفعلية على المنصة ═══
    async def _close_position(self, trade, current_price):
        symbol = trade['symbol']
        is_buy = trade['side'] == 'BUY'
        close_side = 'SELL' if is_buy else 'BUY'

        amt = await self.get_position_amt(symbol)
        if amt is None:
            self._notify_error(f"تعذر قراءة مركز {symbol}", context="إعادة المحاولة لاحقاً")
            return False, None, None
        step = self.step_sizes_cache.get(symbol) or 1.0
        if abs(amt) < step:   # المركز مأفول أصلاً (الستوب سبقنا)
            pnl = await self.get_last_realized_pnl(symbol, trade)
            return True, current_price, pnl

        qty = self.format_quantity(symbol, min(trade['quantity'], abs(amt)))
        if qty <= 0:
            return True, current_price, await self.get_last_realized_pnl(symbol, trade)

        res = await self._fapi_request('POST', '/fapi/v1/order', {
            'symbol': symbol, 'side': close_side, 'type': 'MARKET',
            'quantity': self.qty_to_str(symbol, qty), 'reduceOnly': 'true'
        }, signed=True)

        if res and res.get('status') in ['FILLED', 'NEW']:
            fill = float(res.get('avgPrice') or 0)
            fill_price = fill if fill > 0 else current_price
            self._reset_error(f"إغلاق {symbol}")
            return True, fill_price, None

        amt2 = await self.get_position_amt(symbol)
        if amt2 is not None and abs(amt2) < step:
            return True, current_price, await self.get_last_realized_pnl(symbol, trade)

        self._notify_error(f"فشل إغلاق {symbol}",
                           context="ستُعاد المحاولة — ستوب المنصة يحمي المركز")
        return False, None, None

    # ═══ الجني الجزئي الخاص بالترند (70% عند TP1 ثم نقل الوقف للتعادل) ═══
    async def _do_trend_partial(self, trade, price):
        sym = trade['symbol']
        is_buy = trade['side'] == 'BUY'
        frac = float(self.trend.cfg['partial'])
        qty = self.format_quantity(sym, trade['quantity'] * frac)
        rem = self.format_quantity(sym, trade['quantity'] - qty)
        min_notional = self.min_notional_cache.get(sym, 5.0)
        if qty <= 0 or rem <= 0 or qty * price < min_notional or rem * price < min_notional:
            ok, fill, pnl_over = await self._close_position(trade, price)
            if ok:
                await self._finalize_trade(trade, fill, "🎯 TP1 (إغلاق كامل — حدود الزوج)", pnl_over)
            return
        res = await self._fapi_request('POST', '/fapi/v1/order', {
            'symbol': sym, 'side': 'SELL' if is_buy else 'BUY', 'type': 'MARKET',
            'quantity': self.qty_to_str(sym, qty), 'reduceOnly': 'true'}, signed=True)
        if not res or res.get('status') not in ('FILLED', 'NEW'):
            self._notify_error(f"فشل الجني الجزئي (ترند) لـ {sym}")
            return
        fill = float(res.get('avgPrice') or 0) or price
        part_pnl = ((fill - trade['entry_price']) if is_buy else (trade['entry_price'] - fill)) * qty
        trade['realized_pnl'] = trade.get('realized_pnl', 0.0) + part_pnl
        await self.db.update_daily_pnl(part_pnl, None)
        trade['quantity'] = rem
        trade['partial_closed'] = True
        be = float(self.trend.cfg.get('be_offset', 0.002))
        trade['sl'] = trade['entry_price'] * (1 + be) if is_buy else trade['entry_price'] * (1 - be)
        await self.db.save_trade(trade)
        await self.trend_db.update_sl(sym, trade['sl'])
        prices = self.get_price(sym)
        await self._sync_stop_order(trade, (prices['bid'] if is_buy else prices['ask']) if prices else price)
        _pc = float(self.trend.cfg['partial']) * 100
        self._log_event('TREND', 'PARTIAL',
                        f"{sym} جني {_pc:.0f}% عند TP1 — ربح محقق {part_pnl:+.4f}$ | "
                        f"الوقف إلى التعادل {self.fmt_price(trade['sl'])}")
        await self.tg(f"🎯 *جني ترند* (`{sym}`)\n💸 أُغلق {_pc:.0f}% بربح `{part_pnl:.4f} USDT`\n"
                      f"🛡️ الوقف للتعادل ثم وقف متحرك {self.trend.cfg['trail_atr']}×ATR(1h)")

    # ═══ إنهاء الصفقة — موجّه مركزي يوزّع المحاسبة على الاستراتيجية الصحيحة ═══
    async def _finalize_trade(self, trade, fill_price, reason, pnl_override=None):
        symbol = trade['symbol']
        is_buy = trade['side'] == 'BUY'
        strategy = trade.get('strategy')
        if strategy not in ('TREND', 'MARS'):
            # حماية دفاعية فقط: كل صفقة تُحمّل/تُتبنّى بهوية جاهزة — هذا للطوارئ
            strategy = 'TREND' if self.count_open('TREND') <= self.count_open('MARS') else 'MARS'
            trade['strategy'] = strategy

        # 1) إلغاء أوامر المنصة المعلقة (ستوب/هدف)
        for oid_key, algo_key in (('stop_order_id', 'stop_is_algo'), ('tp_order_id', 'tp_is_algo')):
            oid = trade.get(oid_key)
            if not oid:
                continue
            if trade.get(algo_key):
                await self._cancel_algo_order(symbol, oid)
            else:
                # مصدر مجهول (محمّل من القاعدة بعد إعادة تشغيل) — جرّب المسارين بصمت
                await self._fapi_request('DELETE', '/fapi/v1/order',
                    {'symbol': symbol, 'orderId': oid}, signed=True, quiet=('-2011', '-2013'))
                await self._cancel_algo_order(symbol, oid)

        # 2) حساب النتيجة (بهامش الاستراتيجية نفسه)
        if pnl_override is not None:
            final_pnl = float(pnl_override)
        else:
            if is_buy: final_pnl = (fill_price - trade['entry_price']) * trade['quantity']
            else: final_pnl = (trade['entry_price'] - fill_price) * trade['quantity']

        total_pnl = trade.get('realized_pnl', 0.0) + final_pnl
        margin_used = float(trade.get('margin_usdt') or self.TRADE_SIZE_USDT or 0)
        margin_pnl_pct = (total_pnl / margin_used * 100) if margin_used > 0 else 0
        is_win = total_pnl > 0

        # 3) إحصاءات الاستراتيجية الصحيحة
        self.strategy_stats(strategy)['wins' if is_win else 'losses'] += 1

        # 4) السجل المشترك (سجل الإشارات + أرباح اليوم) ثم الحذف والتبريد
        try:
            await self.db.set_signal_result(
                symbol, trade['entry_time'], is_win, total_pnl,
                close_ts=time.time(), close_reason=str(reason)[:200],
                duration_s=round(time.time() - trade['entry_time'], 1),
                pnl_pct=round(margin_pnl_pct, 2))
        except Exception:
            pass
        await self.db.update_daily_pnl(total_pnl, is_win)
        await self.db.remove_trade(symbol)
        self.active_trades.pop(symbol, None)
        self.set_cooldown(symbol)

        # 5) قاعدة الاستراتيجية المستقلة
        try:
            if strategy == 'TREND':
                await self.trend_db.close(symbol, time.time(), total_pnl,
                                          round(margin_pnl_pct, 2), is_win, reason)
            elif strategy == 'MARS':
                await self.mars_db.close(symbol, time.time(), total_pnl,
                                         round(margin_pnl_pct, 2), is_win, reason)
        except Exception as e:
            logger.warning(f"تعذر إغلاق سجل الاستراتيجية: {e}")

        icon = "✅" if is_win else "❌"
        partial_note = (f"\n🧾 جني جزئي سابق: `{trade.get('realized_pnl', 0.0):.4f} USDT`"
                        if abs(trade.get('realized_pnl', 0.0)) > 1e-9 else "")
        label = self.STRATEGY_LABELS.get(strategy, '🧩')
        msg = (f"🏁 {icon} *إغلاق `{symbol}`* {label}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
               f"{reason}\n"
               f"💵 النتيجة: `{total_pnl:.4f} USDT` ({margin_pnl_pct:.1f}% من الهامش)\n"
               f"🏆 {label.split(' ', 1)[1]}: "
               f"{self.strategy_stats(strategy)['wins']}W / {self.strategy_stats(strategy)['losses']}L"
               f"{partial_note}")
        await self.tg(msg)
        self._log_event(strategy, 'CLOSE',
                        f"{symbol} {trade['side']} أُغلقت {total_pnl:+.4f}$ ({margin_pnl_pct:+.1f}%) — {reason}")
        logger.info(f"🏁 [{strategy}] {symbol} {total_pnl:+.3f} USDT ({margin_pnl_pct:+.1f}%) — {reason}")

    # ═══ مراقبة الصفقات: كل استراتيجية بقواعدها ═══
    async def monitor_trades(self):
        if not self.active_trades: return
        stale_symbols = []

        for symbol, trade in list(self.active_trades.items()):
            prices = self.get_price(symbol)
            if not prices:
                stale_symbols.append(symbol)
                continue

            is_buy = trade['side'] == 'BUY'
            current_price = prices['bid'] if is_buy else prices['ask']

            if is_buy and current_price > trade.get('highest_price', 0):
                trade['highest_price'] = current_price
            elif not is_buy and current_price < trade.get('lowest_price', 999999):
                trade['lowest_price'] = current_price

            strategy = trade.get('strategy')
            if strategy not in ('TREND', 'MARS'):
                strategy = 'TREND' if self.count_open('TREND') <= self.count_open('MARS') else 'MARS'
                trade['strategy'] = strategy

            # ── 🚀 راكب الترند: مدير الخروج الخاص به ──
            if strategy == 'TREND':
                decision = self.trend_exit.decide(trade, current_price)
                act = decision.get('action')
                if act == 'close':
                    ok, fill, pnl_over = await self._close_position(trade, current_price)
                    if ok:
                        await self._finalize_trade(trade, fill, decision['reason'], pnl_over)
                    continue
                if act == 'partial':
                    await self._do_trend_partial(trade, current_price)
                elif act == 'move_sl':
                    new_sl = decision['sl']
                    if (is_buy and new_sl > trade['sl']) or ((not is_buy) and new_sl < trade['sl']):
                        self._log_event('TREND', 'TRAIL',
                                        f"{symbol} وقف متحرك: {self.fmt_price(trade['sl'])} → "
                                        f"{self.fmt_price(new_sl)}")
                        trade['sl'] = new_sl
                        await self.trend_db.update_sl(symbol, new_sl)
                await self._sync_stop_order(trade, current_price)
                await self.db.save_trade(trade)
                continue

            # ── 📐 موجات 7/25/99: التركيبة المعتمدة (وقف 5×ATR + أهداف لكل جانب + تعادل) ──
            if strategy == 'MARS':
                decision = self.mars_exit.decide(trade, current_price)
                act = decision.get('action')
                if act == 'close':
                    ok, fill, pnl_over = await self._close_position(trade, current_price)
                    if ok:
                        await self._finalize_trade(trade, fill, decision['reason'], pnl_over)
                    continue
                if act == 'move_sl':
                    new_sl = decision['sl']
                    if (is_buy and new_sl > trade['sl']) or ((not is_buy) and new_sl < trade['sl']):
                        trade['sl'] = new_sl
                        trade['be_active'] = True
                        try:
                            await self.mars_db.update_sl(symbol, new_sl)
                        except Exception as e:
                            logger.warning(f"تعذر تحديث وقف التعادل في القاعدة: {e}")
                        await self.db.save_trade(trade)
                        self._log_event('MARS', 'BREAKEVEN',
                                        f"{symbol} وقف التعادل: {self.fmt_price(new_sl)}")
                        logger.info(f"🛡️ [MARS] {symbol} وقف للتعادل @ {self.fmt_price(new_sl)}")
                await self._sync_stop_order(trade, current_price)
                continue

            # ── 🧩 لا يوجد مسار «متبنّى عام» بعد اليوم: كل صفقة لها استراتيجية ──

        if stale_symbols:
            self._notify_error("أسعار مجمّدة لمراكز مفتوحة",
                               context=f"{', '.join(stale_symbols)} — ستوب المنصة يحميها")

    # ═══ الصيانة الذاتية ═══
    def _cleanup_memory(self):
        now = time.time()
        self.reentry_cooldown = {k: v for k, v in self.reentry_cooldown.items() if v > now}
        self.last_discovery_alert = {k: v for k, v in self.last_discovery_alert.items()
                                     if v > now - 7200}
        if len(self.error_counts) > 500:
            self.error_counts.clear()

    async def _send_daily_report(self, day):
        row = await self.db.get_day_stats(day)
        if not row: return
        pnl, w, l = row
        wr = (w / (w + l) * 100) if (w + l) > 0 else 0
        await self.tg(f"📊 *تقرير {day}* (الاستراتيجيتان)\n💰 PnL: `{pnl:.4f} USDT`\n"
                      f"🏆 {w}W / {l}L (فوز {wr:.0f}%)")

    def _trades_today(self):
        today = time.strftime("%Y-%m-%d")
        return sum(1 for _, d in self.entry_history if d == today)

    async def _heartbeat_and_report(self, loop_count):
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        if today != self._report_day:
            await self._send_daily_report(self._report_day)
            self._report_day = today
        if now - self._last_heartbeat >= 3600:
            self._last_heartbeat = now
            await self.tg(f"💓 *النبض:* حي ✓ | مسح #{loop_count} | صفقات اليوم: {self._trades_today()}\n"
                          f"🚀 ترند مفتوحة: {self.count_open('TREND')}/{self.trend_capacity} "
                          f"({self.stats_trend['wins']}W/{self.stats_trend['losses']}L) | "
                          f"📐 موجات مفتوحة: {self.count_open('MARS')}/{self.mars_capacity} "
                          f"({self.stats_mars['wins']}W/{self.stats_mars['losses']}L)")

    # ═══ تحديد هوية الاستراتيجية لأي مركز بلا سجل واضح ═══
    async def resolve_strategy_for_symbol(self, symbol):
        """يُرجع 'TREND' أو 'MARS' حصراً لأي مركز/صفقة بلا هوية — بترتيب الأدلة الأقوى:
        1) آخر إشارة مسجّلة لهذا الزوج في signal_log (مكوناتها تحمل اسم الاستراتيجية)
        2) أحدث صفقة لهذا الزوج في قاعدة أي استراتيجية (الأحدث تفوز)
        3) الاستراتيجية الأكثر سعة متاحة (والتعادل لترند) — قرار حتمي دائماً
        لا يوجد أي مسار يُرجع هوية عامة: كل صفقة تظهر في لوحتها فقط."""
        try:
            async with aiosqlite.connect(self.db.db_name) as db:
                async with db.execute(
                        """SELECT components FROM signal_log WHERE symbol=?
                           ORDER BY entry_ts DESC LIMIT 5""", (symbol,)) as cur:
                    rows = await cur.fetchall()
            for r in rows:
                try:
                    s = (json.loads(r[0] or '{}') or {}).get('strategy')
                except Exception:
                    s = None
                if s in ('TREND', 'MARS'):
                    return s
        except Exception:
            pass
        try:
            last_ts = {}
            for key, sdb in (('TREND', self.trend_db), ('MARS', self.mars_db)):
                async with aiosqlite.connect(sdb.db_name) as db:
                    async with db.execute(
                            f"SELECT MAX(entry_ts) FROM {sdb.TABLE} WHERE symbol=?",
                            (symbol,)) as cur:
                        row = await cur.fetchone()
                last_ts[key] = (row[0] or 0) if row else 0
            if last_ts['TREND'] or last_ts['MARS']:
                return 'TREND' if last_ts['TREND'] >= last_ts['MARS'] else 'MARS'
        except Exception:
            pass
        free_trend = self.strategy_capacity('TREND') - self.count_open('TREND')
        free_mars = self.strategy_capacity('MARS') - self.count_open('MARS')
        return 'TREND' if free_trend >= free_mars else 'MARS'

    # ═══ المصالحة الذاتية عند الإقلاع (واعية بالاستراتيجيتين) ═══
    async def reconcile(self):
        if not self.binance_api_key or not self.TRADE_ENABLED:
            return
        try:
            positions = await self._fapi_request('GET', '/fapi/v2/positionRisk', signed=True)
            open_pos = {}
            if isinstance(positions, list):
                for p in positions:
                    try:
                        amt = float(p.get('positionAmt', 0))
                    except (TypeError, ValueError):
                        continue
                    if abs(amt) > 0:
                        open_pos[p['symbol']] = {'amt': amt, 'entry': float(p.get('entryPrice', 0))}

            # 1) صفقة في القاعدة بلا مركز على المنصة → أُغلقت أثناء التوقف
            for symbol, trade in list(self.active_trades.items()):
                pos = open_pos.get(symbol)
                step = self.step_sizes_cache.get(symbol) or 1.0
                if not pos or abs(pos['amt']) < step:
                    pnl = await self.get_last_realized_pnl(symbol, trade)
                    await self._finalize_trade(trade, trade['entry_price'],
                                               "🔄 أُغلق أثناء توقف البوت", pnl)

            # 2) تبنّي المراكز اليتيمة بهوية استراتيجيتها (من قاعدة كل استراتيجية)
            for key, sdb in (('TREND', self.trend_db), ('MARS', self.mars_db)):
                try:
                    await self._adopt_strategy_orphans(key, sdb, open_pos)
                except Exception as e:
                    logger.warning(f"⚠️ خطأ تبنّي صفقات {key}: {e}")

            # 3) تبنّي ما تبقّى بأسمٍ حقيقي (TREND أو MARS) — لا هوية عامة بعد اليوم
            try:
                await self._adopt_unknown_orphans(open_pos)
            except Exception as e:
                logger.warning(f"⚠️ خطأ تبنّي المراكز المجهولة: {e}")

            # 4) سجلات استراتيجية ميتة (مركزها أُغلق خارج البوت) → إغلاق نهائي
            for key, sdb in (('TREND', self.trend_db), ('MARS', self.mars_db)):
                try:
                    await self._close_stale_strategy_rows(key, sdb, open_pos)
                except Exception as e:
                    logger.warning(f"⚠️ خطأ تنظيف سجلات {key}: {e}")

            # 5) إلغاء أوامر يتيمة (ستوب/TP لا تطابق أي صفقة حية)
            orders = await self._fapi_request('GET', '/fapi/v1/openOrders', signed=True) or []
            try:
                orders += await self._fapi_request('GET', '/fapi/v1/algoOpenOrders',
                    signed=True, quiet=('-5000',)) or []
            except Exception:
                pass
            known_ids = set()
            for t in self.active_trades.values():
                if t.get('stop_order_id'): known_ids.add(t['stop_order_id'])
                if t.get('tp_order_id'): known_ids.add(t['tp_order_id'])
            cancelled = 0
            for o in orders:
                oid = o.get('orderId') or o.get('algoId')
                if oid in known_ids or o.get('type') not in ('STOP_MARKET', 'TAKE_PROFIT_MARKET'):
                    continue
                if o.get('algoId'):
                    await self._fapi_request('DELETE', '/fapi/v1/algoOrder',
                        {'symbol': o['symbol'], 'algoId': o['algoId']}, signed=True,
                        quiet=('-2011', '-2013'))
                else:
                    await self._fapi_request('DELETE', '/fapi/v1/order',
                        {'symbol': o['symbol'], 'orderId': o['orderId']}, signed=True,
                        quiet=('-2011', '-2013'))
                cancelled += 1
            if cancelled:
                await self.tg(f"🧹 *تنظيف ذاتي:* أُلغي {cancelled} أمر يتيم على المنصة")
            logger.info(f"🧾 المصالحة الذاتية: {len(open_pos)} مركز حي، {cancelled} أمر يتيم ملغى")
        except Exception as e:
            self._notify_error("فشل المصالحة الذاتية", exc=e, context="غير قاتل — تُعاد كل دورات")

    async def _adopt_strategy_orphans(self, key, sdb, open_pos):
        """تبنّي المراكز اليتيمة التي لها سجل مفتوح في قاعدة الاستراتيجية —
        بوقفها وهدفها وهامشها من قاعدة الاستراتيجية نفسها."""
        rows = await sdb.open_symbols()
        adopted = []
        cfg_s = self.strategy_cfg(key)
        risk_mult = float(cfg_s['sl_atr1h'])
        for sym, row in rows.items():
            if sym in self.active_trades or sym not in open_pos:
                continue
            pos = open_pos[sym]
            step = self.step_sizes_cache.get(sym) or 1.0
            if abs(pos['amt']) < step:
                continue
            entry = float(row.get('entry') or 0) or float(pos.get('entry') or 0)
            if entry <= 0:
                continue
            side = 'BUY' if pos['amt'] > 0 else 'SELL'
            # الهدف لكل جانب (MARS: 0.5R شراء / 1.75R بيع — التركيبة المعتمدة)
            tp_r = float(cfg_s.get('tp_r_buy' if side == 'BUY' else 'tp_r_sell',
                                   cfg_s.get('tp1_r' if key == 'TREND' else 'tp_r', 2.0)))
            tp_mult = tp_r * risk_mult
            atr_v = float(row.get('atr') or 0)
            sl = float(row.get('sl') or 0)
            if sl <= 0:
                sl = entry - risk_mult * atr_v if side == 'BUY' else entry + risk_mult * atr_v
            tp = float(row.get('tp1') or 0)
            if tp <= 0 and atr_v > 0:
                tp = entry + tp_mult * atr_v if side == 'BUY' else entry - tp_mult * atr_v
            trade = {
                'symbol': sym, 'side': side, 'entry_price': entry,
                'quantity': abs(pos['amt']), 'sl': sl, 'tp': tp or None, 'tp2': None,
                'trailing_active': False, 'highest_price': entry, 'lowest_price': entry,
                'entry_time': float(row.get('entry_ts') or time.time()),
                'partial_closed': False, 'realized_pnl': 0.0,
                'stop_order_id': None, 'tp_order_id': None,
                'stop_is_algo': False, 'tp_is_algo': False,
                'stop_synced_price': None, 'tp_skipped': False,
                'strategy': key, 'atr_ref': atr_v,
                'margin_usdt': float(row.get('margin') or 0) or self.strategy_margin(key),
                'components': {'strategy': key, 'trigger': 'تبنّي بعد إعادة تشغيل'},
            }
            self.active_trades[sym] = trade
            await self.db.save_trade(trade)
            try:
                await self._sync_stop_order(trade, entry)
            except Exception:
                pass
            adopted.append(sym)
            logger.info(f"🔄 تبنّي {key}: {sym} {side} @ {self.fmt_price(entry)} "
                        f"(وقف/هدف/هامش من قاعدة الاستراتيجية)")
        if adopted:
            label = self.STRATEGY_LABELS[key]
            await self.tg("🔄 *تبنّي " + label + "*\n"
                          + "، ".join(f"`{s}`" for s in adopted)
                          + "\nاستُعيدت بوقفها وهدفها وهامشها — ستظهر في لوحتها")

    async def _adopt_unknown_orphans(self, open_pos):
        """تبنّي أي مركز يتيم بلا سجل في قاعدتي الاستراتيجيتين —
        يُقيَّد فوراً باستراتيجية محددة (TREND أو MARS) يحددها resolve_strategy_for_symbol،
        فلا يظهر في اللوحتين أبداً، ويُدار بقواعد الاستراتيجية المسند إليها،
        ويُسجَّل في قاعدتها كي لا يُعاد تبنّيه من الصفر في كل إعادة تشغيل."""
        for symbol, pos in open_pos.items():
            if symbol in self.active_trades:
                continue
            key = await self.resolve_strategy_for_symbol(symbol)
            side = 'BUY' if pos['amt'] > 0 else 'SELL'
            entry = pos['entry'] or (self.live_prices.get(symbol, {}).get('bid', 0))
            if not entry or entry <= 0:
                await self.tg(f"⚠️ *تعذّر تبنّي مركز يتيم* (`{symbol}`)\n"
                              f"سعر الدخول غير متاح بعد — سيُعاد في إعادة تشغيل قادمة")
                continue
            cfg = self.strategy_cfg(key)
            df = await self.get_klines(symbol, '1h', 60)
            atr_v = self._compute_atr(df) if df is not None else None
            if not atr_v or atr_v <= 0 or math.isnan(atr_v):
                atr_v = entry * 0.01
            risk_mult = float(cfg['sl_atr1h'])
            tp_r = float(cfg.get('tp_r_buy' if side == 'BUY' else 'tp_r_sell',
                                 cfg.get('tp_r') or cfg.get('tp1_r') or 2.0))
            sl = entry - risk_mult * atr_v if side == 'BUY' else entry + risk_mult * atr_v
            tp = entry + tp_r * risk_mult * atr_v if side == 'BUY' else entry - tp_r * risk_mult * atr_v
            trade = {
                'symbol': symbol, 'side': side, 'entry_price': entry,
                'quantity': abs(pos['amt']), 'sl': sl, 'tp': tp, 'tp2': None,
                'trailing_active': False, 'highest_price': entry, 'lowest_price': entry,
                'entry_time': time.time(), 'partial_closed': False,
                'realized_pnl': 0.0, 'stop_order_id': None, 'tp_order_id': None,
                'stop_is_algo': False, 'tp_is_algo': False,
                'stop_synced_price': None, 'tp_skipped': False,
                'strategy': key, 'atr_ref': atr_v,
                'margin_usdt': self.strategy_margin(key),
                'components': {'strategy': key, 'trigger': f'تبنّي مركز يتيم → أُسند إلى {key}'},
            }
            self.active_trades[symbol] = trade
            await self.db.save_trade(trade)
            try:
                sdb = self.trend_db if key == 'TREND' else self.mars_db
                await sdb.open(trade)   # سجّله في قاعدة استراتيجيته — هوية دائمة الآن
            except Exception as e:
                logger.warning(f"تعذر تسجيل المتبنّى في قاعدة {key}: {e}")
            await self._sync_stop_order(trade, entry)
            if key == 'MARS' and trade.get('tp'):   # تثبيت الهدف على المنصة كصفقات الموجات
                try:
                    await self._place_tp_order(trade, entry,
                                               target=trade['tp'], qty=trade['quantity'])
                except Exception:
                    pass
            await self.db.save_trade(trade)
            self.strategy_stats(key)['trades'] += 1
            self.entry_history.append((time.time(), time.strftime("%Y-%m-%d")))
            self._log_event(key, 'ADOPT',
                            f"{symbol} {side} تبنّاه محرك {self.STRATEGY_LABELS[key]} "
                            f"بعد إعادة تشغيل — وقف {self.fmt_price(sl)} / هدف {self.fmt_price(tp)}")
            await self.tg(f"🔄 *تم تبنّي مركز يتيم* (`{symbol}`)\n"
                          f"أسند إلى {self.STRATEGY_LABELS[key]} — وقف/هدف بقواعد الاستراتيجية، "
                          f"وسيظهر في لوحتها فقط")

    async def _close_stale_strategy_rows(self, key, sdb, open_pos):
        """سجل مفتوح بلا مركز على المنصة وبلا صفقة حية → انتهى فعلاً؛
        يُسجَّل إغلاقه بمكسبه المحقق من المنصة (إن وُجد) حتى لا يعود شبحاً."""
        rows = await sdb.open_symbols()
        for sym, row in rows.items():
            if sym in self.active_trades:
                continue
            pos = open_pos.get(sym)
            step = self.step_sizes_cache.get(sym) or 1.0
            if pos and abs(pos['amt']) >= step:
                continue   # المركز حي — مسؤوليته التبنّي
            fake = {'symbol': sym, 'entry_time': float(row.get('entry_ts') or 0)}
            try:
                pnl = await self.get_last_realized_pnl(sym, fake)
            except Exception:
                pnl = None
            if pnl is None:
                pnl = 0.0
            await sdb.close(sym, time.time(), round(pnl, 4), 0.0,
                            pnl > 0, '🔄 أُغلق مركزه خارج البوت أثناء التوقف')
            logger.info(f"🧹 سجل {key} ميت نُظّف: {sym} ({pnl:+.4f}$)")

    # ═══ استعادة الصفقات مع هوية الاستراتيجية ═══
    async def _load_trades_with_strategy(self):
        trades = await self.db.load_active_trades()
        for key, sdb in (('TREND', self.trend_db), ('MARS', self.mars_db)):
            try:
                rows = await sdb.open_symbols()
            except Exception:
                rows = {}
            for sym, row in rows.items():
                if sym in trades and not trades[sym].get('strategy'):
                    trades[sym]['strategy'] = key
                    trades[sym]['atr_ref'] = row.get('atr') or 0.0
                    m = float(row.get('margin') or 0)
                    trades[sym]['margin_usdt'] = m if m > 0 else self.strategy_margin(key)
                    trades[sym]['tp2'] = None
                    logger.info(f"♻️ استُعيدت صفقة {key} مفتوحة: {sym}")
        for sym, t in trades.items():
            if t.get('strategy') not in ('TREND', 'MARS'):
                t['strategy'] = await self.resolve_strategy_for_symbol(sym)
                if not t.get('margin_usdt'):
                    t['margin_usdt'] = self.strategy_margin(t['strategy'])
                logger.info(f"♻️ صفقة بلا هوية أُسندت إلى {t['strategy']}: {sym}")
        return trades

    # ═══ نبض الحياة: يمنع Render من إسبان الخدمة بعد الخمول ═══
    # Render المجّاني يُسبِن الخدمة بعد ~15 دقيقة بلا زيارات خارجية، وعند الاستيقاظ
    # تُعاد تشغيل العملية وتُمسح الذاكرة — وهذا هو مصدر مشاكل المصالحة بعد الغياب.
    # الحل: نبضة كل 10 دقائق على /health (الرابط العام + محلياً) تحافظ على الخدمة صاحية.
    async def keep_alive_loop(self):
        urls = []
        ext = (os.environ.get('RENDER_EXTERNAL_URL') or os.environ.get('SELF_URL') or '').strip()
        if ext:
            urls.append(ext.rstrip('/') + '/health')
        extra = (os.environ.get('KEEPALIVE_URLS') or '').strip()
        for u in [x.strip() for x in extra.split(',') if x.strip()]:
            u = u if u.endswith('/health') else u.rstrip('/') + '/health'
            if u not in urls:
                urls.append(u)
        local = f"http://127.0.0.1:{self.port}/health"
        if local not in urls:
            urls.append(local)
        logger.info(f"💓 Keep-Alive نشط كل 600 ثانية → {urls}")
        while True:
            await asyncio.sleep(600)
            for u in urls:
                try:
                    async with self.session.get(u, timeout=aiohttp.ClientTimeout(total=15)) as r:
                        await r.read()
                except Exception:
                    pass

    # ═══ اللوب الرئيسي ═══
    async def main_loop(self):
        self.session = aiohttp.ClientSession()
        try:
            # لوحة العمليات — ملف واحد فيه لوحتا الاستراتيجيتين
            await start_web_panel(self)
            # ✅ نبض الحياة: يمنع إسبان الخدمة على Render بعد الخمول
            asyncio.create_task(self.keep_alive_loop())
            loop = asyncio.get_running_loop()
            for sig_name in ('SIGINT', 'SIGTERM'):
                try:
                    loop.add_signal_handler(getattr(signal, sig_name),
                        lambda: asyncio.ensure_future(self.request_shutdown('signal')))
                except (NotImplementedError, ValueError, AttributeError, RuntimeError):
                    pass

            await self.db.init_db()
            try:
                await self.trend_db.init()
            except Exception as e:
                logger.error(f"تعذر تهيئة قاعدة بيانات الترند: {e}")
            try:
                await self.mars_db.init()
            except Exception as e:
                logger.error(f"تعذر تهيئة قاعدة بيانات الموجات: {e}")

            # ✅ تحميل الإعدادات المحفوظة من اللوحة (تنجو من إعادة التشغيل والنشر)
            for param_key, strat, exit_mgr in (
                    ('trend_config', self.trend, self.trend_exit),
                    ('mars_config', self.mars, self.mars_exit)):
                try:
                    raw = await self.db.get_param(param_key)
                    if raw:
                        saved = json.loads(raw)
                        if int(saved.get('settings_version', 1) or 1) == \
                                int(strat.cfg.get('settings_version', 1) or 1):
                            strat.cfg.update({k: v for k, v in saved.items() if k in strat.cfg})
                            exit_mgr.cfg.update(strat.cfg)
                        else:
                            # إعدادات محفوظة من إصدار أقدم (قبل اعتماد التركيبة الجديدة)
                            # تُهمَل وتُستبدل بالإعدادات المعتمدة حرفياً من الاختبار الموسّع
                            logger.info(f"⚙️ {param_key}: إعدادات محفوظة قديمة (إصدار "
                                        f"{saved.get('settings_version', 1)}) — اعتماد "
                                        f"الإعدادات الجديدة v{strat.cfg.get('settings_version')}")
                            await self.db.set_param(param_key, json.dumps(dict(strat.cfg)))
                except Exception as e:
                    logger.warning(f"تعذر تحميل إعدادات محفوظة ({param_key}): {e}")
            self.trend_capacity = int(self.trend.cfg.get('max_open_trades', self.trend_capacity))
            self.mars_capacity = int(self.mars.cfg.get('max_open_trades', self.mars_capacity))
            logger.info(f"⚙️ السعة (لا سقف إجمالي — كل استراتيجية مستقلة) — "
                        f"ترند: {self.trend_capacity} | موجات: {self.mars_capacity} | "
                        f"الحالة: ترند {'مفعّل' if self.trend.cfg.get('enabled') else 'متوقف'} / "
                        f"موجات {'مفعّلة' if self.mars.cfg.get('enabled') else 'متوقفة'}")

            market_tries = 0
            while not self.all_futures_pairs:
                market_tries += 1
                await self.load_market_data()
                if self.all_futures_pairs: break
                if market_tries == 1 or market_tries % 5 == 0:
                    await self.tg(f"❌ *فشل تحميل بيانات السوق* (محاولة {market_tries})\n"
                                  f"⏳ إعادة خلال 30 ثانية...")
                logger.error(f"فشل تحميل بيانات السوق (محاولة {market_tries})")
                await asyncio.sleep(30)

            self.active_trades = await self._load_trades_with_strategy()
            await self.sync_server_time()

            try:
                dual = await self._fapi_request('GET', '/fapi/v1/positionSide/dual', signed=True)
                if dual and dual.get('dualSidePosition'):
                    if self.TRADE_ENABLED:
                        self.TRADE_ENABLED = False
                        logger.error("❌ الحساب في وضع Hedge Mode — التحويل للمراقبة فقط")
                        await self.tg("⚠️ *تنبيه:* Hedge Mode مفعّل — البوت لوضع One-way فقط. تم التحويل للمراقبة.")
            except Exception as e:
                logger.warning(f"تعذر فحص Hedge Mode: {e}")

            if self.TRADE_ENABLED and self.binance_api_key:
                await self.setup_futures_account()

            self.ws_task = asyncio.create_task(self.ws_manager())
            await asyncio.sleep(10)

            if self.TRADE_ENABLED and self.binance_api_key:
                await self.reconcile()
                await self.verify_positions()

            mode_trade = "⚔️ تداول تلقائي" + (" (TESTNET 🧪)" if self.TESTNET else "") \
                         if self.TRADE_ENABLED else "👁️ مراقبة فقط"
            msg = ("🤖 *البوت ثنائي الاستراتيجية — انطلق!*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                   f"📡 الوضع: {mode_trade} | رافعة {self.LEVERAGE}x | هامش {self.TRADE_SIZE_USDT:.0f}$\n"
                   f"🚀 راكب الترند: {'مفعّل' if self.trend.cfg.get('enabled') else 'متوقف'} — "
                   f"اختراق {self.trend.cfg.get('donch')} ساعة | دخول لمس شمعة الإشارة "
                   f"({self.trend.cfg.get('stop_validity_min')}د) | سعة {self.trend_capacity}\n"
                   f"📐 موجات 7/25/99: {'مفعّلة' if self.mars.cfg.get('enabled') else 'متوقفة'} — "
                   f"تقاطع + زخم | وقف {self.mars.cfg.get('sl_atr1h')}×ATR | "
                   f"أهداف {self.mars.cfg.get('tp_r_buy')}R/{self.mars.cfg.get('tp_r_sell')}R | سعة {self.mars_capacity}\n"
                   f"🛡️ لا سقف إجمالي — سعة كل استراتيجية مستقلة\n"
                   "━━━━━━━━━━━━━━━━━━━━━━━━\n⏰ بدء المسح...")
            await self.tg(msg)

            loop_count = 0
            while not self._shutdown_requested:
                try:
                    newest_ts = max((p.get('ts', 0) for p in self.live_prices.values()), default=0)
                    if newest_ts and (time.time() - newest_ts) > self.WS_STALE_ALERT:
                        self._notify_error("توقف تدفق الأسعار (WebSocket)",
                            context=f"لا تحديثات منذ {int(time.time() - newest_ts)} ثانية — ستوب المنصة يحمي المراكز")

                    await self.monitor_trades()
                    await self.check_trend_pending()
                    await self.scan_volatile_coins()

                    loop_count += 1
                    self.stats['total_scans'] = loop_count
                    if loop_count % self.VERIFY_EVERY_N_LOOPS == 0:
                        await self.verify_positions()
                    # ✅ مصالحة دورية كل 10 دقائق: أي مركز على المنصة لا يظهر في
                    # اللوحتين (بعد إعادة تشغيل/سبين-داون) يُتبنّى فوراً بدل انتظار
                    # إعادة تشغيل كاملة
                    if loop_count % 10 == 0:
                        await self.reconcile()

                    self._cleanup_memory()
                    await self._heartbeat_and_report(loop_count)
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    raise
                except Exception as loop_err:
                    logger.error(f"خطأ في الحلقة: {loop_err}")
                    self._notify_error("خطأ في الحلقة الرئيسية", exc=loop_err)
                    await asyncio.sleep(15)
        finally:
            if self.ws_task:
                self.ws_task.cancel()
            if self.session and not self.session.closed:
                await self.session.close()

    def start(self):
        asyncio.run(self.main_loop())


if __name__ == "__main__":
    bot = DualStrategyBot()
    bot.start()
