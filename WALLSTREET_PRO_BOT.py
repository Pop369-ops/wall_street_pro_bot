"""
═══════════════════════════════════════════════════════════════════════
  WALL STREET PRO BOT — V4.0 UNIFIED EDITION
═══════════════════════════════════════════════════════════════════════
  بوت موحّد يدمج:
    📰 الأخبار + التقويم الاقتصادي
    📊 التحليل الفني (ICT + Smart Money + RSI + MACD + EMA + BB)
    🐋 Smart Money (CFTC COT + TFF)
    🏦 Central Banks (Fed + ECB + BOE + BOJ)
    💎 Options Flow (Polygon)
    🌍 Macro (FRED + Trading Economics)
    📈 CME Tick Data (Databento)
    🧠 3 AI Brains (Claude + Gemini + OpenAI)
    🎯 Recommendation Engine (BUY/SELL/HOLD/ADD)
    📅 Daily Scheduler + News Monitor + Alerts
    💾 SQLite Memory (يتذكر كل توصية)
    📚 Performance Tracking
    
  ⚠️ تحليلات تعليمية — ليس نصيحة استثمارية
═══════════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import sqlite3
import logging
import asyncio
import math
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict

import requests
import feedparser
import yfinance as yf
import pandas as pd
import numpy as np
import pytz
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters,
)

# Smart Risk Management Module
import smart_risk

# ═══════════════════════════════════════════════════════════════════════
# CONFIG — Railway Variables
# ═══════════════════════════════════════════════════════════════════════
BOT_TOKEN              = os.environ.get("BOT_TOKEN", "")
CLAUDE_API_KEY         = os.environ.get("CLAUDE_API_KEY", "")
GEMINI_API_KEY         = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY         = os.environ.get("OPENAI_API_KEY", "")
POLYGON_API_KEY        = os.environ.get("POLYGON_API_KEY", "")
TRADING_ECON_KEY       = os.environ.get("TRADING_ECON_KEY", "")  # format: "user:pass"
DATABENTO_API_KEY      = os.environ.get("DATABENTO_API_KEY", "")
FRED_API_KEY           = os.environ.get("FRED_API_KEY", "")

# 💎 Options Sentiment toggle
# تشغيل/تعطيل ميزة Options Sentiment.
# اضبطها على "true" لو عندك اشتراك Options Starter ($29/m) أو أعلى.
# Default = False لأن خطة Currencies Starter ما تشمل Options.
ENABLE_OPTIONS = os.environ.get("ENABLE_OPTIONS", "false").lower() in ("true", "1", "yes")

# نماذج AI
CLAUDE_MODEL = "claude-sonnet-4-5"
GEMINI_MODEL = "gemini-2.0-flash-exp"
OPENAI_MODEL = "gpt-4o"

# مسار قاعدة البيانات
DB_PATH = os.environ.get("DB_PATH", "wallstreet_bot.db")

# توقيت افتراضي
DEFAULT_TZ        = "Asia/Riyadh"
DEFAULT_BRIEF_HR  = 7
DEFAULT_BRIEF_MIN = 0

# دورية المراقب
NEWS_MONITOR_INTERVAL = 1800   # 30 دقيقة
PRICE_CACHE_TTL       = 60     # ثانية واحدة - الأسعار

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("WallStreetBot")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36",
}
sess = requests.Session()
sess.headers.update(HEADERS)

# ═══════════════════════════════════════════════════════════════════════
# 1) DATABASE — SQLite للذاكرة الدائمة
# ═══════════════════════════════════════════════════════════════════════
def db_init():
    """تهيئة قاعدة البيانات."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # جدول المشتركين
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id TEXT PRIMARY KEY,
            hour INTEGER DEFAULT 7,
            minute INTEGER DEFAULT 0,
            tz TEXT DEFAULT 'Asia/Riyadh',
            alerts INTEGER DEFAULT 1,
            last_sent TEXT,
            created_at TEXT,
            metadata TEXT
        )
    """)
    
    # جدول التوصيات (تتبّع الأداء)
    c.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            asset TEXT,
            action TEXT,
            entry_price REAL,
            stop_loss REAL,
            take_profit_1 REAL,
            take_profit_2 REAL,
            take_profit_3 REAL,
            confidence INTEGER,
            timeframe TEXT,
            reasoning TEXT,
            status TEXT DEFAULT 'OPEN',
            outcome TEXT,
            pnl_pct REAL,
            closed_at TEXT,
            created_at TEXT,
            risk_data TEXT
        )
    """)
    
    # Migration: إضافة الأعمدة الجديدة لو الجدول قديم
    for col, col_type in [
        ("take_profit_3", "REAL"),
        ("risk_data", "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE recommendations ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # العمود موجود بالفعل
    
    # جدول الأخبار التي تم رؤيتها (تجنب التكرار)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen_news (
            news_id TEXT PRIMARY KEY,
            seen_at TEXT
        )
    """)
    
    # جدول ذاكرة المحادثات (للسياق)
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversation_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    """)
    
    # جدول cache للبيانات (أسعار، COT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT,
            expires_at TEXT
        )
    """)
    
    # تحسين الأداء
    c.execute("CREATE INDEX IF NOT EXISTS idx_recs_chat ON recommendations(chat_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_recs_status ON recommendations(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mem_chat ON conversation_memory(chat_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_time ON seen_news(seen_at)")
    
    # ═══ جدول الصفقات المتابَعة (Active Trade Tracking) ═══
    c.execute("""
        CREATE TABLE IF NOT EXISTS tracked_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            recommendation_id INTEGER,
            asset TEXT NOT NULL,
            action TEXT NOT NULL,
            entry_price REAL NOT NULL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            position_size REAL,
            capital_at_entry REAL,
            status TEXT DEFAULT 'ACTIVE',
            tp1_hit INTEGER DEFAULT 0,
            tp2_hit INTEGER DEFAULT 0,
            tp3_hit INTEGER DEFAULT 0,
            sl_moved_to_be INTEGER DEFAULT 0,
            partial_closed_pct REAL DEFAULT 0,
            exit_price REAL,
            exit_reason TEXT,
            pnl_dollars REAL,
            pnl_pct REAL,
            opened_at TEXT,
            closed_at TEXT,
            last_alert_at TEXT,
            last_check_at TEXT,
            notes TEXT,
            FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
        )
    """)
    
    # ═══ جدول التنبيهات (تجنب التكرار) ═══
    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_alerts_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            sent_at TEXT,
            FOREIGN KEY (trade_id) REFERENCES tracked_trades(id)
        )
    """)
    
    # ═══ جدول تتبع الأخبار العاجلة (User-level toggle) ═══
    c.execute("""
        CREATE TABLE IF NOT EXISTS news_tracking (
            chat_id TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            assets TEXT,                       -- comma-separated: Gold,EUR/USD,...
            min_impact INTEGER DEFAULT 2,      -- 1=low, 2=medium, 3=high only
            ai_analysis INTEGER DEFAULT 1,     -- include AI analysis
            started_at TEXT,
            last_alert_at TEXT
        )
    """)
    
    # ═══ جدول الأخبار اللي اتبعت (تجنب تكرار التحليل) ═══
    c.execute("""
        CREATE TABLE IF NOT EXISTS news_alerts_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            news_id TEXT NOT NULL,
            sent_at TEXT,
            UNIQUE(chat_id, news_id)
        )
    """)
    
    c.execute("CREATE INDEX IF NOT EXISTS idx_tracked_chat ON tracked_trades(chat_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tracked_status ON tracked_trades(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_trade ON trade_alerts_sent(trade_id, alert_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_alerts_chat ON news_alerts_sent(chat_id)")
    
    conn.commit()
    conn.close()
    log.info("Database initialized ✅")


def db_exec(query: str, params: tuple = (), fetch: str = None) -> Any:
    """تنفيذ استعلام DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute(query, params)
        if fetch == "one":
            result = c.fetchone()
            return dict(result) if result else None
        elif fetch == "all":
            return [dict(r) for r in c.fetchall()]
        else:
            conn.commit()
            return c.lastrowid
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 1.5) TRADE TRACKING HELPERS — إدارة الصفقات المتابَعة
# ═══════════════════════════════════════════════════════════════════════
def track_create_trade(
    chat_id: str,
    asset: str,
    action: str,
    entry: float,
    sl: float = None,
    tp1: float = None,
    tp2: float = None,
    tp3: float = None,
    position_size: float = None,
    capital: float = 4000,
    recommendation_id: int = None,
    notes: str = None,
) -> int:
    """ينشئ صفقة جديدة للتتبع.
    
    Returns: trade_id
    """
    now = datetime.now(timezone.utc).isoformat()
    return db_exec(
        """INSERT INTO tracked_trades 
           (chat_id, recommendation_id, asset, action, entry_price,
            sl, tp1, tp2, tp3, position_size, capital_at_entry,
            status, opened_at, last_check_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)""",
        (chat_id, recommendation_id, asset, action.upper(), entry,
         sl, tp1, tp2, tp3, position_size, capital,
         now, now, notes)
    )


def track_get_active_trades(chat_id: str = None) -> List[Dict]:
    """يجلب كل الصفقات النشطة (لمستخدم معين أو الكل)."""
    if chat_id:
        rows = db_exec(
            "SELECT * FROM tracked_trades WHERE status='ACTIVE' AND chat_id=? "
            "ORDER BY opened_at DESC",
            (chat_id,), fetch="all"
        )
    else:
        rows = db_exec(
            "SELECT * FROM tracked_trades WHERE status='ACTIVE' "
            "ORDER BY opened_at DESC",
            fetch="all"
        )
    return [dict(r) for r in (rows or [])]


def track_get_trade(trade_id: int) -> Optional[Dict]:
    """يجلب صفقة بالـID."""
    row = db_exec(
        "SELECT * FROM tracked_trades WHERE id=?",
        (trade_id,), fetch="one"
    )
    return dict(row) if row else None


def track_update_trade(trade_id: int, **kwargs) -> bool:
    """يحدّث حقول صفقة. مثال: track_update_trade(5, tp1_hit=1)."""
    if not kwargs:
        return False
    set_clause = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [trade_id]
    db_exec(
        f"UPDATE tracked_trades SET {set_clause} WHERE id=?",
        tuple(values)
    )
    return True


def track_close_trade(
    trade_id: int,
    exit_price: float,
    exit_reason: str,
    pnl_dollars: float = None,
    pnl_pct: float = None,
) -> bool:
    """إغلاق صفقة."""
    now = datetime.now(timezone.utc).isoformat()
    db_exec(
        """UPDATE tracked_trades 
           SET status='CLOSED', exit_price=?, exit_reason=?,
               pnl_dollars=?, pnl_pct=?, closed_at=?
           WHERE id=?""",
        (exit_price, exit_reason, pnl_dollars, pnl_pct, now, trade_id)
    )
    return True


def track_alert_was_sent(trade_id: int, alert_type: str) -> bool:
    """يتحقق هل التنبيه ده اتبعت قبل كده."""
    row = db_exec(
        "SELECT 1 FROM trade_alerts_sent WHERE trade_id=? AND alert_type=? LIMIT 1",
        (trade_id, alert_type), fetch="one"
    )
    return bool(row)


def track_mark_alert_sent(trade_id: int, alert_type: str):
    """يسجّل إرسال التنبيه."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        db_exec(
            "INSERT INTO trade_alerts_sent (trade_id, alert_type, sent_at) VALUES (?, ?, ?)",
            (trade_id, alert_type, now)
        )
    except Exception:
        pass


def track_calculate_pnl(trade: Dict, current_price: float) -> Tuple[float, float]:
    """يحسب PnL الحالي (دولار + نسبة).
    
    Returns: (pnl_dollars, pnl_pct)
    """
    entry = trade["entry_price"]
    is_buy = trade["action"] in ("BUY", "ADD")
    pos_size = trade.get("position_size") or 0
    
    if is_buy:
        pnl_pct = (current_price - entry) / entry * 100
    else:
        pnl_pct = (entry - current_price) / entry * 100
    
    # PnL بالدولار يعتمد على lot_value
    if pos_size:
        try:
            cfg = smart_risk.ASSET_CONFIG.get(trade["asset"], smart_risk.ASSET_CONFIG["default"])
            lot_value = cfg.get("lot_value_per_point", 100)
            price_diff = abs(current_price - entry)
            sign = 1 if (is_buy and current_price > entry) or (not is_buy and current_price < entry) else -1
            pnl_dollars = sign * price_diff * lot_value * pos_size
        except Exception:
            pnl_dollars = pnl_pct * (trade.get("capital_at_entry", 4000) * 0.01)
    else:
        pnl_dollars = pnl_pct * (trade.get("capital_at_entry", 4000) * 0.01)
    
    return round(pnl_dollars, 2), round(pnl_pct, 3)


# ═══════════════════════════════════════════════════════════════════════
# 1.6) NEWS TRACKING HELPERS — تتبع الأخبار العاجلة
# ═══════════════════════════════════════════════════════════════════════
def news_tracking_enable(
    chat_id: str,
    assets: List[str] = None,
    min_impact: int = 2,
    ai_analysis: bool = True,
) -> bool:
    """يفعّل تتبع الأخبار للمستخدم.
    
    Args:
        assets: ["Gold", "EUR/USD", ...] أو None للكل
        min_impact: 1=low, 2=medium, 3=high only
        ai_analysis: include quick AI analysis with each alert
    """
    now = datetime.now(timezone.utc).isoformat()
    assets_str = ",".join(assets) if assets else "ALL"
    db_exec(
        """INSERT OR REPLACE INTO news_tracking 
           (chat_id, enabled, assets, min_impact, ai_analysis, started_at)
           VALUES (?, 1, ?, ?, ?, ?)""",
        (chat_id, assets_str, min_impact, 1 if ai_analysis else 0, now)
    )
    return True


def news_tracking_disable(chat_id: str) -> bool:
    """يلغي تتبع الأخبار."""
    db_exec(
        "UPDATE news_tracking SET enabled=0 WHERE chat_id=?",
        (chat_id,)
    )
    return True


def news_tracking_get_subscribers() -> List[Dict]:
    """يجلب كل المستخدمين اللي مفعّلين تتبع الأخبار."""
    rows = db_exec(
        "SELECT * FROM news_tracking WHERE enabled=1",
        fetch="all"
    )
    return [dict(r) for r in (rows or [])]


def news_tracking_get_status(chat_id: str) -> Optional[Dict]:
    """يجلب حالة تتبع الأخبار للمستخدم."""
    row = db_exec(
        "SELECT * FROM news_tracking WHERE chat_id=?",
        (chat_id,), fetch="one"
    )
    return dict(row) if row else None


def news_alert_was_sent(chat_id: str, news_id: str) -> bool:
    """تحقق هل الخبر اتبعت قبل كده."""
    row = db_exec(
        "SELECT 1 FROM news_alerts_sent WHERE chat_id=? AND news_id=? LIMIT 1",
        (chat_id, news_id), fetch="one"
    )
    return bool(row)


def news_alert_mark_sent(chat_id: str, news_id: str):
    """تسجيل إرسال تنبيه خبر."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        db_exec(
            "INSERT OR IGNORE INTO news_alerts_sent (chat_id, news_id, sent_at) VALUES (?, ?, ?)",
            (chat_id, news_id, now)
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# 2) CACHE LAYER — تجنب الطلبات المتكررة
# ═══════════════════════════════════════════════════════════════════════
def cache_get(key: str) -> Optional[Any]:
    row = db_exec("SELECT value, expires_at FROM cache WHERE key=?", (key,), fetch="one")
    if not row:
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires:
            db_exec("DELETE FROM cache WHERE key=?", (key,))
            return None
        return json.loads(row["value"])
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_seconds: int = 60):
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    db_exec(
        "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
        (key, json.dumps(value, default=str), expires),
    )


# ═══════════════════════════════════════════════════════════════════════
# 3) NEWS FEEDS (RSS)
# ═══════════════════════════════════════════════════════════════════════
RSS_FEEDS = {
    "FXStreet — Forex":         "https://www.fxstreet.com/rss/news",
    "FXStreet — Commodities":   "https://www.fxstreet.com/rss/commodities",
    "Investing — Forex":        "https://www.investing.com/rss/news_1.rss",
    "Investing — Commodities":  "https://www.investing.com/rss/news_11.rss",
    "Investing — Economy":      "https://www.investing.com/rss/news_14.rss",
    "ForexLive":                "https://www.forexlive.com/feed/news/",
    "DailyFX":                  "https://www.dailyfx.com/feeds/market-news",
    "Kitco — Gold":             "https://www.kitco.com/rss/KitcoNews.xml",
    "Federal Reserve":          "https://www.federalreserve.gov/feeds/press_all.xml",
    "ECB":                      "https://www.ecb.europa.eu/rss/press.html",
}

HIGH_IMPACT_KEYWORDS = [
    "fomc", "fed ", "powell", "ecb", "lagarde", "boe", "bailey", "boj", "ueda",
    "rate decision", "rate cut", "rate hike", "interest rate",
    "cpi", "inflation", "nfp", "non-farm", "unemployment", "jobless",
    "gdp", "ppi", "retail sales", "ism", "pce",
    "war", "ceasefire", "sanctions", "tariff",
    "iran", "russia", "china trade", "opec",
    "treasury yield", "yield curve", "recession",
    "ath", "all-time high", "crash", "plunge", "surge", "soar", "tumble",
    "emergency", "bailout", "default",
]


def fetch_news(max_per_source: int = 5, hours_back: int = 24) -> List[Dict]:
    """جلب الأخبار من كل المصادر."""
    cached = cache_get(f"news_{max_per_source}_{hours_back}")
    if cached:
        for n in cached:
            n["date"] = datetime.fromisoformat(n["date"])
        return cached
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    all_news = []
    for source_name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                continue
            for entry in feed.entries[:max_per_source]:
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                else:
                    pub_dt = datetime.now(timezone.utc)
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:300]
                nid = entry.get("id") or entry.get("link", "") or entry.get("title", "")
                all_news.append({
                    "id": nid,
                    "source": source_name,
                    "title": entry.get("title", "—"),
                    "summary": summary,
                    "link": entry.get("link", ""),
                    "date": pub_dt,
                })
        except Exception as e:
            log.warning(f"RSS [{source_name}]: {e}")
    
    all_news.sort(key=lambda x: x["date"], reverse=True)
    
    # cache 5 minutes
    cache_data = [{**n, "date": n["date"].isoformat()} for n in all_news]
    cache_set(f"news_{max_per_source}_{hours_back}", cache_data, ttl_seconds=300)
    
    return all_news


def is_high_impact(news_item: Dict) -> Tuple[bool, List[str]]:
    text = (news_item["title"] + " " + news_item["summary"]).lower()
    matched = [kw for kw in HIGH_IMPACT_KEYWORDS if kw in text]
    return (len(matched) >= 1, matched)


def filter_news_by_topic(news: List[Dict], keywords: List[str]) -> List[Dict]:
    out = []
    for n in news:
        text = (n["title"] + " " + n["summary"]).lower()
        if any(kw in text for kw in keywords):
            out.append(n)
    return out


# ═══════════════════════════════════════════════════════════════════════
# 4) MARKET DATA — yfinance + Polygon
# ═══════════════════════════════════════════════════════════════════════
SYMBOLS = {
    "Gold (XAUUSD)":    "GC=F",
    "Silver (XAGUSD)":  "SI=F",
    "DXY (Dollar)":     "DX-Y.NYB",
    "EUR/USD":          "EURUSD=X",
    "GBP/USD":          "GBPUSD=X",
    "USD/JPY":          "JPY=X",
    "USD/CHF":          "CHF=X",
    "AUD/USD":          "AUDUSD=X",
    "Oil (WTI)":        "CL=F",
    "S&P 500":          "^GSPC",
    "VIX":              "^VIX",
    "13W Yield":        "^IRX",
    "5Y Yield":         "^FVX",
    "10Y Yield":        "^TNX",
    "30Y Yield":        "^TYX",
}


def get_gold_dataframe_scaled(period: str = "6mo", interval: str = "1d"):
    """Wrapper بسيط - يستدعي get_asset_dataframe_scaled للذهب.
    
    محفوظ للتوافق مع الكود القديم.
    """
    return get_asset_dataframe_scaled("XAU/USD", "GC=F", period, interval)


def fetch_prices() -> Dict[str, Dict]:
    """جلب الأسعار اللحظية + cache 60 ثانية.
    
    استراتيجية:
    1. للأصول المدعومة في Polygon (Gold, Silver, Forex, Oil): Polygon أولاً
    2. لو Polygon فشل: yfinance كـfallback مع تحذير لو السعر يبدو قديم
    3. للأصول غير المدعومة (S&P, VIX, Yields): yfinance مباشرة
    
    النتيجة: كل الأصول الرئيسية تكون أسعارها صحيحة دائماً.
    """
    cached = cache_get("prices_all")
    if cached:
        return cached
    
    out = {}
    
    # ═══ الأصول اللي ندعمها في Polygon ═══
    # كل واحد: (اسم في out, asset key في polygon, ticker yfinance)
    polygon_assets = [
        ("Gold (XAUUSD)",   "XAU/USD", "GC=F"),
        ("Silver (XAGUSD)", "XAG/USD", "SI=F"),
        ("EUR/USD",         "EUR/USD", "EURUSD=X"),
        ("GBP/USD",         "GBP/USD", "GBPUSD=X"),
        ("USD/JPY",         "USD/JPY", "JPY=X"),
        ("USD/CHF",         "USD/CHF", "CHF=X"),
        ("AUD/USD",         "AUD/USD", "AUDUSD=X"),
        ("Oil (WTI)",       "WTI",     "CL=F"),
    ]
    
    polygon_handled = set()
    for out_name, poly_asset, yf_ticker in polygon_assets:
        if out_name not in SYMBOLS:
            continue
        poly_data = polygon_get_asset_price(poly_asset)
        if poly_data and poly_data.get("price"):
            # ─── جبنا السعر من Polygon — نكمّل week_pct من yfinance ───
            week_pct = 0
            try:
                t = yf.Ticker(yf_ticker)
                hist = t.history(period="5d", interval="1d")
                if not hist.empty and len(hist) >= 2:
                    yf_last = float(hist["Close"].iloc[-1])
                    yf_week = float(hist["Close"].iloc[0])
                    poly_price = poly_data["price"]
                    # نتأكد إن yfinance مش outdated قبل ما نستخدم الـweekly
                    if abs(poly_price - yf_last) / poly_price < 0.05:
                        week_pct = (yf_last - yf_week) / yf_week * 100
                    else:
                        # yfinance قديم — نحسب week_pct من النسبة فقط
                        if yf_week > 0:
                            scale = poly_price / yf_last
                            scaled_week = yf_week * scale
                            week_pct = (poly_price - scaled_week) / scaled_week * 100
            except Exception as e:
                log.warning(f"yf weekly [{out_name}]: {e}")
            
            out[out_name] = {
                "price": poly_data["price"],
                "change_pct": poly_data.get("change_pct", 0),
                "week_pct": week_pct,
                "ticker": ASSET_POLYGON_CONFIG[poly_asset]["polygon"],
                "source": poly_data.get("source", "polygon"),
                "bid": poly_data.get("bid", 0),
                "ask": poly_data.get("ask", 0),
                "day_high": poly_data.get("day_high", 0),
                "day_low": poly_data.get("day_low", 0),
            }
            polygon_handled.add(out_name)
    
    # ═══ باقي الأصول (S&P, VIX, Yields, etc.) من yfinance ═══
    for name, ticker in SYMBOLS.items():
        if name in polygon_handled:
            continue
        
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            if hist.empty:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
            week = float(hist["Close"].iloc[0]) if len(hist) >= 5 else prev
            chg_d = (last - prev) / prev * 100 if prev else 0
            chg_w = (last - week) / week * 100 if week else 0
            out[name] = {
                "price": last,
                "change_pct": chg_d,
                "week_pct": chg_w,
                "ticker": ticker,
                "source": "yfinance",
            }
        except Exception as e:
            log.warning(f"price [{name}]: {e}")
    
    # ═══ Fallback: لو Polygon فشل لأي أصل، نجيبه من yfinance ═══
    for out_name, _, yf_ticker in polygon_assets:
        if out_name in out or out_name not in SYMBOLS:
            continue
        try:
            t = yf.Ticker(yf_ticker)
            hist = t.history(period="5d", interval="1d")
            if not hist.empty:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                week = float(hist["Close"].iloc[0]) if len(hist) >= 5 else prev
                
                # تحذير لو السعر يبدو قديم (للذهب فقط لأنه واضح)
                if "XAUUSD" in out_name and last < 3000:
                    log.warning(f"⚠️ {out_name} from yfinance looks outdated: ${last:.2f}")
                
                out[out_name] = {
                    "price": last,
                    "change_pct": (last - prev) / prev * 100 if prev else 0,
                    "week_pct": (last - week) / week * 100 if week else 0,
                    "ticker": yf_ticker,
                    "source": "yfinance_fallback",
                }
        except Exception as e:
            log.warning(f"yfinance fallback [{out_name}]: {e}")
    
    cache_set("prices_all", out, ttl_seconds=PRICE_CACHE_TTL)
    return out


# ═══════════════════════════════════════════════════════════════════════
# 5) POLYGON.IO — Forex + Options
# ═══════════════════════════════════════════════════════════════════════
def polygon_get(endpoint: str, params: Dict = None, return_error: bool = False) -> Optional[Dict]:
    """طلب عام لـPolygon API.
    
    إذا return_error=True، يرجع dict فيه error info بدل None في حالة الفشل.
    """
    if not POLYGON_API_KEY:
        if return_error:
            return {"_error": "no_key", "_message": "POLYGON_API_KEY غير موجود في Environment Variables"}
        return None
    if params is None:
        params = {}
    params["apiKey"] = POLYGON_API_KEY
    try:
        url = f"https://api.polygon.io{endpoint}"
        r = sess.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        # تفصيل الخطأ
        err_text = r.text[:500] if r.text else ""
        log.warning(f"Polygon HTTP {r.status_code}: {err_text[:200]}")
        if return_error:
            error_type = "unknown"
            error_msg = f"HTTP {r.status_code}"
            if r.status_code == 401:
                error_type = "auth"
                error_msg = "API Key غير صحيح أو منتهي"
            elif r.status_code == 403:
                error_type = "plan"
                error_msg = "خطتك على Polygon لا تشمل هذا الـEndpoint (محتاج خطة Options)"
            elif r.status_code == 429:
                error_type = "rate_limit"
                error_msg = "تجاوزت حد الطلبات (5/min على الخطة المجانية)"
            elif r.status_code == 404:
                error_type = "not_found"
                error_msg = "Endpoint غير موجود"
            return {"_error": error_type, "_message": error_msg, "_status": r.status_code, "_response": err_text}
    except Exception as e:
        log.warning(f"Polygon: {e}")
        if return_error:
            return {"_error": "exception", "_message": str(e)}
    return None


def polygon_get_gold_price() -> Optional[Dict]:
    """Wrapper بسيط - يستدعي polygon_get_asset_price للذهب.
    
    محفوظ للتوافق مع الكود القديم.
    """
    return polygon_get_asset_price("XAU/USD")


# ═══════════════════════════════════════════════════════════════════════
# 5b) UNIVERSAL POLYGON ASSET PRICE FETCHER (يدعم كل الأصول)
# ═══════════════════════════════════════════════════════════════════════
ASSET_POLYGON_CONFIG = {
    # Forex pairs
    "EUR/USD":    {"polygon": "C:EURUSD",  "type": "forex",  "decimals": 5, "min_price": 0.5},
    "GBP/USD":    {"polygon": "C:GBPUSD",  "type": "forex",  "decimals": 5, "min_price": 0.5},
    "USD/JPY":    {"polygon": "C:USDJPY",  "type": "forex",  "decimals": 3, "min_price": 50},
    "USD/CHF":    {"polygon": "C:USDCHF",  "type": "forex",  "decimals": 5, "min_price": 0.3},
    "AUD/USD":    {"polygon": "C:AUDUSD",  "type": "forex",  "decimals": 5, "min_price": 0.3},
    "USD/CAD":    {"polygon": "C:USDCAD",  "type": "forex",  "decimals": 5, "min_price": 0.5},
    # Metals (commodities via forex API)
    "XAU/USD":    {"polygon": "C:XAUUSD",  "type": "metal",  "decimals": 2, "min_price": 100,
                   "etf_ticker": "GLD",  "etf_multiplier": 10},
    "XAG/USD":    {"polygon": "C:XAGUSD",  "type": "metal",  "decimals": 3, "min_price": 5,
                   "etf_ticker": "SLV",  "etf_multiplier": 1.075},  # SLV ≈ Silver/0.93
    # Oil (futures - يحتاج معالجة خاصة)
    "WTI":        {"polygon": "CL",        "type": "futures", "decimals": 2, "min_price": 10,
                   "etf_ticker": "USO",  "etf_multiplier": None},  # USO/Oil ratio يتغير
}


def polygon_get_asset_price(asset: str) -> Optional[Dict]:
    """جلب السعر الفوري لأي أصل من Polygon بـ3 مسارات احتياطية.
    
    Args:
        asset: اسم الأصل (مثل "EUR/USD", "XAU/USD", "WTI")
    
    Returns:
        dict {price, bid, ask, change_pct, day_high, day_low, prev_close, source}
        أو None لو فشل
    """
    cache_key = f"poly_asset_{asset.replace('/', '_')}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    if not POLYGON_API_KEY:
        return None
    
    cfg = ASSET_POLYGON_CONFIG.get(asset)
    if not cfg:
        log.warning(f"polygon_get_asset_price: unknown asset '{asset}'")
        return None
    
    polygon_ticker = cfg["polygon"]
    asset_type = cfg["type"]
    min_price = cfg["min_price"]
    
    # ═══ المسار 1: Snapshot (forex/stocks) ═══
    if asset_type in ("forex", "metal"):
        endpoint = f"/v2/snapshot/locale/global/markets/forex/tickers/{polygon_ticker}"
    elif asset_type == "futures":
        # Futures محتاج treatment مختلف — هنفوّت ده ونروح لـETF
        endpoint = None
    else:
        endpoint = None
    
    if endpoint:
        data = polygon_get(endpoint)
        if data and data.get("status") == "OK":
            ticker_data = data.get("ticker", {})
            if ticker_data:
                last_quote = ticker_data.get("lastQuote", {}) or {}
                day = ticker_data.get("day", {}) or {}
                prev_day = ticker_data.get("prevDay", {}) or {}
                
                bid = last_quote.get("b", 0)
                ask = last_quote.get("a", 0)
                mid = (bid + ask) / 2 if (bid and ask) else (bid or ask)
                
                if mid and mid > min_price:  # sanity check
                    prev_close = prev_day.get("c", 0)
                    change_pct = ((mid - prev_close) / prev_close * 100) if (prev_close and mid) else 0
                    
                    result = {
                        "asset": asset,
                        "price": mid,
                        "bid": bid,
                        "ask": ask,
                        "spread": (ask - bid) if (ask and bid) else 0,
                        "day_high": day.get("h", 0) or mid,
                        "day_low": day.get("l", 0) or mid,
                        "prev_close": prev_close or mid,
                        "change_pct": change_pct,
                        "source": "polygon_forex_snapshot",
                    }
                    cache_set(cache_key, result, ttl_seconds=30)
                    return result
    
    # ═══ المسار 2: Currency Conversion (للـforex فقط) ═══
    if asset_type in ("forex", "metal") and "/" in asset:
        from_curr, to_curr = asset.split("/")
        data = polygon_get(f"/v1/conversion/{from_curr}/{to_curr}", {"amount": 1, "precision": 5})
        if data and data.get("converted") is not None:
            rate = float(data["converted"])
            if rate > min_price:
                result = {
                    "asset": asset,
                    "price": rate,
                    "bid": rate,
                    "ask": rate,
                    "spread": 0,
                    "day_high": rate,
                    "day_low": rate,
                    "prev_close": rate,
                    "change_pct": 0,
                    "source": "polygon_conversion",
                }
                cache_set(cache_key, result, ttl_seconds=30)
                return result
    
    # ═══ المسار 3: ETF Proxy (للأصول اللي عندها ETF) ═══
    etf_ticker = cfg.get("etf_ticker")
    etf_multiplier = cfg.get("etf_multiplier")
    if etf_ticker and etf_multiplier:
        data = polygon_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{etf_ticker}")
        if data and data.get("status") == "OK":
            ticker_data = data.get("ticker", {})
            if ticker_data:
                day = ticker_data.get("day", {}) or {}
                last_trade = ticker_data.get("lastTrade", {}) or {}
                prev_day = ticker_data.get("prevDay", {}) or {}
                
                etf_price = last_trade.get("p", 0) or day.get("c", 0)
                if etf_price > 5:  # ETF normally > $5
                    asset_price = etf_price * etf_multiplier
                    prev_etf = prev_day.get("c", 0)
                    change_pct = ((etf_price - prev_etf) / prev_etf * 100) if prev_etf else 0
                    
                    result = {
                        "asset": asset,
                        "price": asset_price,
                        "bid": asset_price,
                        "ask": asset_price,
                        "spread": 0,
                        "day_high": (day.get("h", 0) or etf_price) * etf_multiplier,
                        "day_low": (day.get("l", 0) or etf_price) * etf_multiplier,
                        "prev_close": prev_etf * etf_multiplier if prev_etf else asset_price,
                        "change_pct": change_pct,
                        "source": f"polygon_{etf_ticker.lower()}_etf",
                    }
                    cache_set(cache_key, result, ttl_seconds=30)
                    return result
    
    return None


def get_asset_dataframe_scaled(asset: str, yf_ticker: str,
                                period: str = "6mo",
                                interval: str = "1d"):
    """دالة عامة لجلب DataFrame مع scaling لو yfinance قديم.
    
    تعمل لأي أصل عنده config في ASSET_POLYGON_CONFIG.
    
    Returns: (df_scaled, scale_info)
    """
    try:
        t = yf.Ticker(yf_ticker)
        df = t.history(period=period, interval=interval)
        if df.empty:
            return None, {"applied": False, "error": "yfinance empty"}
        
        yf_last = float(df["Close"].iloc[-1])
        poly_data = polygon_get_asset_price(asset)
        
        if not poly_data:
            return df, {"applied": False, "yf_last": yf_last, "poly_price": None}
        
        poly_price = poly_data["price"]
        diff_pct = abs(poly_price - yf_last) / poly_price * 100
        
        if diff_pct < 5:
            return df, {
                "applied": False, "factor": 1.0,
                "yf_last": yf_last, "poly_price": poly_price,
            }
        
        # Multiplicative scaling - يحافظ على النسب
        scale_factor = poly_price / yf_last
        df_scaled = df.copy()
        for col in ["Open", "High", "Low", "Close"]:
            if col in df_scaled.columns:
                df_scaled[col] = df_scaled[col] * scale_factor
        
        log.warning(
            f"📊 {asset} DataFrame scaled: factor={scale_factor:.4f} "
            f"(yf={yf_last:.4f} → poly={poly_price:.4f})"
        )
        
        return df_scaled, {
            "applied": True,
            "factor": scale_factor,
            "yf_last": yf_last,
            "poly_price": poly_price,
            "diff_pct": diff_pct,
        }
    except Exception as e:
        log.warning(f"get_asset_dataframe_scaled [{asset}]: {e}")
        return None, {"applied": False, "error": str(e)}


def polygon_fx_quote(from_curr: str = "EUR", to_curr: str = "USD") -> Optional[Dict]:
    """آخر سعر FX من Polygon (currency conversion endpoint)."""
    cache_key = f"poly_fx_{from_curr}_{to_curr}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    data = polygon_get(f"/v1/conversion/{from_curr}/{to_curr}", {"amount": 1})
    if data and data.get("converted") is not None:
        result = {
            "rate": data.get("converted"),
            "last_updated": data.get("last", {}).get("timestamp"),
        }
        cache_set(cache_key, result, ttl_seconds=30)
        return result
    return None


def polygon_forex_realtime(pair: str = "C:EURUSD") -> Optional[Dict]:
    """
    أسعار Forex real-time من Polygon Currencies plan.
    Format: C:EURUSD, C:GBPUSD, C:USDJPY...
    يستفيد من اشتراك Currencies Starter ($49/شهر).
    """
    cache_key = f"poly_fx_rt_{pair}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    # snapshot endpoint للـcurrency
    data = polygon_get(f"/v2/snapshot/locale/global/markets/forex/tickers/{pair}")
    if not data or data.get("status") != "OK":
        return None
    
    ticker_data = data.get("ticker", {})
    if not ticker_data:
        return None
    
    last_quote = ticker_data.get("lastQuote", {})
    last_trade = ticker_data.get("lastTrade", {})
    day = ticker_data.get("day", {})
    prev_day = ticker_data.get("prevDay", {})
    
    bid = last_quote.get("b", 0) or last_trade.get("p", 0)
    ask = last_quote.get("a", 0) or last_trade.get("p", 0)
    mid = (bid + ask) / 2 if (bid and ask) else (bid or ask)
    
    prev_close = prev_day.get("c", 0)
    change_pct = ((mid - prev_close) / prev_close * 100) if (prev_close and mid) else 0
    
    result = {
        "pair": pair.replace("C:", ""),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": (ask - bid) if (ask and bid) else 0,
        "day_high": day.get("h", 0),
        "day_low": day.get("l", 0),
        "day_volume": day.get("v", 0),
        "prev_close": prev_close,
        "change_pct": change_pct,
        "updated": last_quote.get("t", 0),
    }
    cache_set(cache_key, result, ttl_seconds=30)
    return result


def polygon_options_aggregate(underlying: str = "GLD", return_error: bool = False) -> Dict:
    """
    تجميع بيانات الـoptions chain لتحليل Put/Call sentiment.
    GLD = Gold ETF (best proxy for gold options activity).
    """
    cache_key = f"poly_opts_{underlying}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    # نجيب snapshot للـoptions
    data = polygon_get(
        f"/v3/snapshot/options/{underlying}",
        {"limit": 250},
        return_error=return_error,
    )
    
    # حالة الخطأ المفصّل
    if isinstance(data, dict) and data.get("_error"):
        if return_error:
            return data  # يرجّع error info
        return {}
    
    if not data or "results" not in data:
        if return_error:
            return {"_error": "no_data", "_message": "لم يتم استلام بيانات (السوق مغلق أو لا يوجد options)"}
        return {}
    
    results = data["results"]
    calls_vol  = sum(r.get("day", {}).get("volume", 0) for r in results
                     if r.get("details", {}).get("contract_type") == "call")
    puts_vol   = sum(r.get("day", {}).get("volume", 0) for r in results
                     if r.get("details", {}).get("contract_type") == "put")
    calls_oi   = sum(r.get("open_interest", 0) for r in results
                     if r.get("details", {}).get("contract_type") == "call")
    puts_oi    = sum(r.get("open_interest", 0) for r in results
                     if r.get("details", {}).get("contract_type") == "put")
    
    total_vol = calls_vol + puts_vol
    pc_vol_ratio = puts_vol / calls_vol if calls_vol else 0
    pc_oi_ratio  = puts_oi / calls_oi if calls_oi else 0
    
    # تفسير
    if pc_vol_ratio < 0.7:
        sentiment = "🟢 Bullish قوي (Calls تتفوق)"
    elif pc_vol_ratio < 1.0:
        sentiment = "🟡 Bullish معتدل"
    elif pc_vol_ratio < 1.3:
        sentiment = "🟠 Bearish معتدل"
    else:
        sentiment = "🔴 Bearish قوي (Puts تتفوق)"
    
    result = {
        "underlying": underlying,
        "calls_volume": calls_vol,
        "puts_volume": puts_vol,
        "calls_oi": calls_oi,
        "puts_oi": puts_oi,
        "total_volume": total_vol,
        "pc_volume_ratio": round(pc_vol_ratio, 3),
        "pc_oi_ratio": round(pc_oi_ratio, 3),
        "sentiment": sentiment,
    }
    cache_set(cache_key, result, ttl_seconds=900)  # 15 min
    return result


# ═══════════════════════════════════════════════════════════════════════
# 6) FRED API — Federal Reserve Data
# ═══════════════════════════════════════════════════════════════════════
def fred_get_series(series_id: str, limit: int = 30) -> Optional[List[Dict]]:
    """جلب سلسلة بيانات من FRED."""
    if not FRED_API_KEY:
        return None
    cache_key = f"fred_{series_id}_{limit}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        r = sess.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=15,
        )
        if r.status_code == 200:
            obs = r.json().get("observations", [])
            out = [{"date": o["date"], "value": o["value"]}
                   for o in obs if o["value"] != "."]
            cache_set(cache_key, out, ttl_seconds=3600)  # ساعة
            return out
    except Exception as e:
        log.warning(f"FRED [{series_id}]: {e}")
    return None


def fred_get_macro_snapshot() -> Dict:
    """لقطة شاملة للماكرو الأمريكي من FRED."""
    series = {
        "Fed Funds Rate":      "DFF",          # Federal Funds Effective Rate
        "CPI YoY":             "CPIAUCSL",
        "Core PCE":            "PCEPILFE",
        "Unemployment":        "UNRATE",
        "10Y-2Y Spread":       "T10Y2Y",
        "Real GDP YoY":        "A191RL1Q225SBEA",
        "M2 Money Supply":     "M2SL",
    }
    out = {}
    for name, sid in series.items():
        data = fred_get_series(sid, limit=2)
        if data and len(data) > 0:
            try:
                latest = float(data[0]["value"])
                prev = float(data[1]["value"]) if len(data) > 1 else latest
                out[name] = {
                    "value": latest,
                    "previous": prev,
                    "change": latest - prev,
                    "date": data[0]["date"],
                }
            except (ValueError, IndexError):
                continue
    return out


# ═══════════════════════════════════════════════════════════════════════
# 7) TRADING ECONOMICS API
# ═══════════════════════════════════════════════════════════════════════
def trading_econ_get(endpoint: str, params: Dict = None) -> Optional[Any]:
    """طلب عام لـTrading Economics API."""
    if not TRADING_ECON_KEY:
        return None
    if params is None:
        params = {}
    params["c"] = TRADING_ECON_KEY  # format: "user:pass"
    params["f"] = "json"
    try:
        url = f"https://api.tradingeconomics.com{endpoint}"
        r = sess.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        log.warning(f"TradingEcon HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"TradingEcon: {e}")
    return None


def fetch_te_calendar(days_ahead: int = 7) -> List[Dict]:
    """التقويم الاقتصادي من Trading Economics — High importance only."""
    cache_key = f"te_cal_{days_ahead}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    today = datetime.now().strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    data = trading_econ_get(
        f"/calendar",
        {"d1": today, "d2": end, "importance": 3},
    )
    if not data:
        # fallback to ForexFactory
        try:
            r = sess.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=10,
            )
            if r.status_code == 200:
                events = r.json()
                data = [{
                    "Date": e.get("date"),
                    "Country": e.get("country"),
                    "Event": e.get("title"),
                    "Importance": 3 if e.get("impact") == "High" else 2,
                    "Forecast": e.get("forecast"),
                    "Previous": e.get("previous"),
                } for e in events if e.get("impact") in ("High", "Medium")]
        except Exception as e:
            log.warning(f"FF fallback: {e}")
            data = []
    
    cache_set(cache_key, data, ttl_seconds=3600)
    return data or []


def fetch_te_central_banks() -> List[Dict]:
    """معدلات البنوك المركزية الحالية من TE."""
    cache_key = "te_cb_rates"
    cached = cache_get(cache_key)
    if cached:
        return cached
    data = trading_econ_get("/markets/intrates")
    if data:
        cache_set(cache_key, data, ttl_seconds=86400)  # 24h
    return data or []


# ═══════════════════════════════════════════════════════════════════════
# 8) DATABENTO — CME Tick Data (on-demand)
# ═══════════════════════════════════════════════════════════════════════
def databento_get_dataset_summary(dataset: str = "GLBX.MDP3") -> Optional[Dict]:
    """
    Databento للـCME data الاحترافية.
    GLBX.MDP3 = CME Globex MDP 3.0 (Gold/FX/Equities futures).
    """
    if not DATABENTO_API_KEY:
        return None
    cache_key = f"db_{dataset}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        r = sess.get(
            f"https://hist.databento.com/v0/metadata.list_datasets",
            auth=(DATABENTO_API_KEY, ""),
            timeout=15,
        )
        if r.status_code == 200:
            datasets = r.json()
            cache_set(cache_key, datasets, ttl_seconds=86400)
            return datasets
    except Exception as e:
        log.warning(f"Databento: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════
# 9) CFTC COT REPORTS (Free)
# ═══════════════════════════════════════════════════════════════════════
def fetch_cot_data() -> Dict:
    """تقارير CFTC COT الأسبوعية."""
    cached = cache_get("cftc_cot")
    if cached:
        return cached
    
    cot = {}
    targets = {
        "Gold":   "088691",
        "Silver": "084691",
        "DXY":    "098662",
        "EUR":    "099741",
        "JPY":    "097741",
        "GBP":    "096742",
    }
    try:
        url = ("https://publicreporting.cftc.gov/resource/6dca-aqww.json"
               "?$limit=100&$order=report_date_as_yyyy_mm_dd DESC")
        r = sess.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        data = r.json()
        for asset, code in targets.items():
            for row in data:
                if row.get("cftc_contract_market_code") == code:
                    long_  = int(float(row.get("noncomm_positions_long_all", 0) or 0))
                    short_ = int(float(row.get("noncomm_positions_short_all", 0) or 0))
                    chg_l  = int(float(row.get("change_in_noncomm_long_all", 0) or 0))
                    chg_s  = int(float(row.get("change_in_noncomm_short_all", 0) or 0))
                    cot[asset] = {
                        "long": long_,
                        "short": short_,
                        "net": long_ - short_,
                        "change_long": chg_l,
                        "change_short": chg_s,
                        "weekly_change": chg_l - chg_s,
                        "date": row.get("report_date_as_yyyy_mm_dd", "")[:10],
                        "bias": "صاعد" if (long_ - short_) > 0 else "هابط",
                    }
                    break
    except Exception as e:
        log.warning(f"COT: {e}")
    
    cache_set("cftc_cot", cot, ttl_seconds=86400)
    return cot


# ═══════════════════════════════════════════════════════════════════════
# 10) TECHNICAL ANALYSIS — RSI/MACD/EMA/BB + ICT
# ═══════════════════════════════════════════════════════════════════════
def calc_rsi(closes: pd.Series, period: int = 14) -> float:
    """RSI."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def calc_macd(closes: pd.Series) -> Tuple[float, float, float]:
    """MACD: returns (macd, signal, histogram)."""
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return (float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1]))


def calc_emas(closes: pd.Series) -> Dict[str, float]:
    """EMAs 20/50/200."""
    return {
        "ema_20":  float(closes.ewm(span=20).mean().iloc[-1]),
        "ema_50":  float(closes.ewm(span=50).mean().iloc[-1]),
        "ema_200": float(closes.ewm(span=200).mean().iloc[-1]),
    }


def calc_bollinger(closes: pd.Series, period: int = 20, std: float = 2.0) -> Dict[str, float]:
    """Bollinger Bands."""
    ma = closes.rolling(period).mean()
    sd = closes.rolling(period).std()
    upper = ma + std * sd
    lower = ma - std * sd
    return {
        "middle": float(ma.iloc[-1]),
        "upper":  float(upper.iloc[-1]),
        "lower":  float(lower.iloc[-1]),
    }


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range — لحساب Stop Loss."""
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1]) if not atr.empty else 0.0


def find_order_blocks(df: pd.DataFrame, lookback: int = 20) -> Tuple[List, List]:
    """ICT Order Blocks — مناطق المؤسسات."""
    if len(df) < lookback + 2:
        return [], []
    bull_obs, bear_obs = [], []
    for i in range(lookback, len(df) - 1):
        if df["Close"].iloc[i] > df["Open"].iloc[i]:  # شمعة صاعدة
            if i > 0 and df["Close"].iloc[i-1] < df["Open"].iloc[i-1]:
                bull_obs.append({
                    "level": float(df["Low"].iloc[i-1]),
                    "type":  "Bullish OB",
                })
        else:  # شمعة هابطة
            if i > 0 and df["Close"].iloc[i-1] > df["Open"].iloc[i-1]:
                bear_obs.append({
                    "level": float(df["High"].iloc[i-1]),
                    "type":  "Bearish OB",
                })
    return bull_obs[-3:], bear_obs[-3:]


def find_fvg(df: pd.DataFrame) -> Tuple[List, List]:
    """Fair Value Gaps (ICT)."""
    if len(df) < 3:
        return [], []
    bull_fvg, bear_fvg = [], []
    for i in range(2, len(df)):
        # Bullish FVG: low[i] > high[i-2]
        if df["Low"].iloc[i] > df["High"].iloc[i-2]:
            bull_fvg.append({
                "gap_top": float(df["Low"].iloc[i]),
                "gap_bottom": float(df["High"].iloc[i-2]),
            })
        # Bearish FVG: high[i] < low[i-2]
        if df["High"].iloc[i] < df["Low"].iloc[i-2]:
            bear_fvg.append({
                "gap_top": float(df["Low"].iloc[i-2]),
                "gap_bottom": float(df["High"].iloc[i]),
            })
    return bull_fvg[-3:], bear_fvg[-3:]


def detect_market_structure(df: pd.DataFrame, lookback: int = 30) -> str:
    """تحديد BOS/CHOCH (Break of Structure)."""
    if len(df) < lookback:
        return "غير محدد"
    recent_high = df["High"].iloc[-lookback:].max()
    recent_low = df["Low"].iloc[-lookback:].min()
    last_close = df["Close"].iloc[-1]
    
    if last_close >= recent_high * 0.999:
        return "🟢 BOS صاعد (اختراق قمة)"
    elif last_close <= recent_low * 1.001:
        return "🔴 BOS هابط (كسر قاع)"
    else:
        mid = (recent_high + recent_low) / 2
        if last_close > mid:
            return "🟡 محايد - مائل للصعود"
        else:
            return "🟡 محايد - مائل للهبوط"


def technical_analysis(ticker: str = "GC=F") -> Dict:
    """تحليل فني شامل.
    
    للذهب (GC=F):
    - السعر الحالي من Polygon (XAU/USD) — أدق
    - DataFrame من yfinance، مع scaling لو yfinance contract منتهي
    - كل المؤشرات (RSI/MACD/EMA/BB/ATR/OBs/FVGs) تُحسب من DataFrame المُحدَّث
    - النتيجة: كل القيم متناسقة مع السعر الحالي الصحيح
    
    للأصول الأخرى: yfinance طبيعي.
    """
    cache_key = f"ta_{ticker}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        # ─── جلب البيانات ───
        scale_info = {"applied": False}
        
        if ticker == "GC=F":
            # للذهب: استخدم scaled DataFrame
            df_1d, scale_info = get_gold_dataframe_scaled(period="6mo", interval="1d")
            df_4h, _ = get_gold_dataframe_scaled(period="60d", interval="1h")
            if df_1d is None or df_1d.empty:
                # fallback: yfinance خام بدون scaling
                t = yf.Ticker(ticker)
                df_1d = t.history(period="6mo", interval="1d")
                df_4h = t.history(period="60d", interval="1h")
        else:
            # باقي الأصول: yfinance طبيعي
            t = yf.Ticker(ticker)
            df_1d = t.history(period="6mo", interval="1d")
            df_4h = t.history(period="60d", interval="1h")
        
        if df_1d is None or df_1d.empty:
            return {}
        
        # ─── حساب المؤشرات ───
        closes = df_1d["Close"]
        rsi = calc_rsi(closes)
        macd, signal, hist = calc_macd(closes)
        emas = calc_emas(closes)
        bb = calc_bollinger(closes)
        atr = calc_atr(df_1d)
        bull_obs, bear_obs = find_order_blocks(df_4h if (df_4h is not None and not df_4h.empty) else df_1d)
        bull_fvg, bear_fvg = find_fvg(df_1d)
        structure = detect_market_structure(df_1d)
        
        last_price = float(closes.iloc[-1])
        price_source = "yfinance"
        warning = None
        
        # تحديد المصدر والتحذير
        if ticker == "GC=F":
            if scale_info.get("applied"):
                price_source = "polygon_with_scaled_history"
                warning = (
                    f"تم تعديل التاريخ التلقائي: yfinance contract منتهي "
                    f"(${scale_info['yf_last']:.2f}) → Polygon (${scale_info['poly_price']:.2f}). "
                    f"النسب والـpatterns محفوظة."
                )
            elif scale_info.get("poly_price"):
                price_source = "polygon"
        
        # ─── تفسير المؤشرات ───
        if rsi > 70:
            rsi_signal = "🔴 ذروة شراء"
        elif rsi < 30:
            rsi_signal = "🟢 ذروة بيع"
        else:
            rsi_signal = "🟡 محايد"
        
        if hist > 0 and macd > signal:
            macd_signal = "🟢 Bullish"
        elif hist < 0 and macd < signal:
            macd_signal = "🔴 Bearish"
        else:
            macd_signal = "🟡 محايد"
        
        # EMAs (الكل في نفس الـscale دلوقتي)
        if last_price > emas["ema_20"] > emas["ema_50"] > emas["ema_200"]:
            ema_trend = "🟢 صعودي قوي (كل EMAs مرتبة)"
        elif last_price < emas["ema_20"] < emas["ema_50"] < emas["ema_200"]:
            ema_trend = "🔴 هبوطي قوي (كل EMAs مرتبة)"
        else:
            ema_trend = "🟡 مختلط"
        
        # Bollinger Bands
        if last_price > bb["upper"]:
            bb_signal = "🔴 فوق Upper Band - تشبع شرائي"
        elif last_price < bb["lower"]:
            bb_signal = "🟢 تحت Lower Band - تشبع بيعي"
        else:
            position = (last_price - bb["lower"]) / (bb["upper"] - bb["lower"]) * 100
            bb_signal = f"🟡 وسط BB ({position:.0f}%)"
        
        result = {
            "ticker": ticker,
            "price": last_price,
            "price_source": price_source,
            "warning": warning,
            "rsi": rsi,
            "rsi_signal": rsi_signal,
            "macd": macd,
            "macd_signal": macd_signal,
            "ema_20": emas["ema_20"],
            "ema_50": emas["ema_50"],
            "ema_200": emas["ema_200"],
            "ema_trend": ema_trend,
            "bb_upper": bb["upper"],
            "bb_lower": bb["lower"],
            "bb_signal": bb_signal,
            "atr": atr,
            "structure": structure,
            "order_blocks": {
                "bullish": bull_obs,
                "bearish": bear_obs,
            },
            "fvg": {
                "bullish": bull_fvg,
                "bearish": bear_fvg,
            },
        }
        cache_set(cache_key, result, ttl_seconds=300)
        return result
    except Exception as e:
        log.warning(f"TA [{ticker}]: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 11) ANALYSIS HELPERS
# ═══════════════════════════════════════════════════════════════════════
def analyze_yield_curve(prices: Dict) -> Dict:
    y3m = prices.get("13W Yield", {}).get("price")
    y10 = prices.get("10Y Yield", {}).get("price")
    if not (y3m and y10):
        return {"status": "غير متاح"}
    spread = y10 - y3m
    return {
        "spread_3M_10Y": spread,
        "inverted": spread < 0,
        "signal": ("🔴 منحنى مقلوب — مؤشر ركود" if spread < 0
                   else "🟡 منحنى مسطح" if spread < 0.5
                   else "🟢 منحنى طبيعي"),
    }


def derive_fed_expectations(prices: Dict) -> Dict:
    y3m = prices.get("13W Yield", {}).get("price")
    y5  = prices.get("5Y Yield", {}).get("price")
    y10 = prices.get("10Y Yield", {}).get("price")
    if not (y3m and y10):
        return {"status": "غير متاح"}
    spread_5y_3m = (y5 - y3m) if (y5 and y3m) else None
    if spread_5y_3m is not None and spread_5y_3m < -0.3:
        bias = "Dovish"
        signal = "🟢 السوق يتوقع خفض فائدة قريباً"
    elif spread_5y_3m is not None and spread_5y_3m > 0.5:
        bias = "Hawkish"
        signal = "🔴 السوق يتوقع تشديد إضافي"
    else:
        bias = "Neutral"
        signal = "🟡 السوق يتوقع ثبات الفائدة"
    return {
        "y3m": y3m, "y5y": y5, "y10y": y10,
        "spread_5y_3m": spread_5y_3m,
        "bias": bias,
        "signal": signal,
    }


# ═══════════════════════════════════════════════════════════════════════
# 11.5) SCALPING MODULE — للذهب والفضة والفوركس والبترول
# ═══════════════════════════════════════════════════════════════════════
"""
استراتيجية Scalping احترافية بـ7 مؤشرات على فريمي 1m + 5m:
1. RSI(7) على 1m       — ذروة شراء/بيع سريعة
2. EMA Cross (5/13)    — Golden/Death Cross فوري
3. Bollinger Bands 5m  — Bounce/Squeeze
4. Volume Spike        — ضغط حقيقي (×2 المتوسط)
5. Stochastic (14,3)   — تأكيد إضافي
6. ATR Momentum        — سرعة الحركة
7. Candle Pattern      — Engulfing/Hammer/Star

SL/TP مخصص للـScalping:
  - SL: 0.7×ATR (ضيق جداً)
  - TP1 = 1:1, TP2 = 1:1.5, TP3 = 1:2.5
  - الإطار الزمني: 5-30 دقيقة
"""

SCALP_TIMEFRAMES = {
    "1m":  {"period": "1d",  "interval": "1m",  "label": "1 دقيقة"},
    "5m":  {"period": "5d",  "interval": "5m",  "label": "5 دقائق"},
    "15m": {"period": "5d",  "interval": "15m", "label": "15 دقيقة"},
}


def _scalp_rsi(close: pd.Series, period: int = 7) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _scalp_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _scalp_bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    upper = ma + sd * std
    lower = ma - sd * std
    return upper, ma, lower


def _scalp_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1] or 0)


def _scalp_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_n = df["Low"].rolling(k_period).min()
    high_n = df["High"].rolling(k_period).max()
    k = 100 * (df["Close"] - low_n) / (high_n - low_n).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def fetch_scalp_data(asset: str, ticker: str) -> Dict:
    """جلب بيانات 1m + 5m للـScalping.
    
    للذهب: استخدم Polygon ticker لسعر دقيق + yfinance للـintraday
    للأصول الأخرى: yfinance مباشرة
    
    Returns: {df_1m, df_5m, current_price, source}
    """
    try:
        # نجيب بيانات 1m (آخر يوم)
        t = yf.Ticker(ticker)
        df_1m = t.history(period="1d", interval="1m")
        df_5m = t.history(period="5d", interval="5m")
        
        if df_1m.empty or df_5m.empty:
            return None
        
        current_price = float(df_1m["Close"].iloc[-1])
        source = "yfinance"
        
        # للأصول المدعومة في Polygon: نتحقق من السعر
        asset_to_poly = {
            "Gold": "XAU/USD",
            "Silver": "XAG/USD",
            "EUR/USD": "EUR/USD",
            "GBP/USD": "GBP/USD",
            "USD/JPY": "USD/JPY",
            "USD/CHF": "USD/CHF",
            "AUD/USD": "AUD/USD",
            "Oil": "WTI",
        }
        poly_key = asset_to_poly.get(asset)
        if poly_key:
            poly_data = polygon_get_asset_price(poly_key)
            if poly_data:
                poly_price = poly_data["price"]
                diff_pct = abs(poly_price - current_price) / poly_price * 100
                # إذا فرق كبير، نطبق scaling
                if diff_pct > 5:
                    scale_factor = poly_price / current_price
                    for col in ["Open", "High", "Low", "Close"]:
                        df_1m[col] = df_1m[col] * scale_factor
                        df_5m[col] = df_5m[col] * scale_factor
                    current_price = poly_price
                    source = "polygon_scaled"
                else:
                    current_price = poly_price
                    source = "polygon"
        
        return {
            "df_1m": df_1m,
            "df_5m": df_5m,
            "current_price": current_price,
            "source": source,
        }
    except Exception as e:
        log.warning(f"fetch_scalp_data [{asset}]: {e}")
        return None


def analyze_scalp(asset: str, ticker: str) -> Optional[Dict]:
    """تحليل Scalping شامل بـ7 مؤشرات.
    
    Returns: {
        "decision": "LONG" / "SHORT" / "WAIT",
        "score": (bull_score, bear_score),
        "signals": [...],
        "warnings": [...],
        "current_price": float,
        "sl": float, "tp1": float, "tp2": float, "tp3": float,
        "duration": "1-15 دقيقة",
        "leverage_suggestion": "x10-x20",
    }
    """
    data = fetch_scalp_data(asset, ticker)
    if not data:
        return None
    
    df_1m = data["df_1m"]
    df_5m = data["df_5m"]
    price = data["current_price"]
    
    if len(df_1m) < 20 or len(df_5m) < 20:
        return None
    
    R = {
        "asset": asset,
        "current_price": price,
        "source": data["source"],
        "bull": 0,
        "bear": 0,
        "signals": [],
        "warnings": [],
    }
    
    cl1 = df_1m["Close"]
    hi1 = df_1m["High"]
    lo1 = df_1m["Low"]
    op1 = df_1m["Open"]
    vo1 = df_1m["Volume"] if "Volume" in df_1m.columns else None
    
    # ─── 1. RSI(7) على 1m ───
    rsi7 = float(_scalp_rsi(cl1, 7).iloc[-1])
    R["rsi7"] = rsi7
    if rsi7 <= 25:
        R["bull"] += 2
        R["signals"].append({"name": "RSI(7) 1m", "icon": "✅", "value": f"{rsi7:.1f}", "note": "ذروة بيع قوية ⚡"})
    elif rsi7 <= 35:
        R["bull"] += 1
        R["signals"].append({"name": "RSI(7) 1m", "icon": "✅", "value": f"{rsi7:.1f}", "note": "ذروة بيع"})
    elif rsi7 >= 75:
        R["bear"] += 2
        R["signals"].append({"name": "RSI(7) 1m", "icon": "🔴", "value": f"{rsi7:.1f}", "note": "ذروة شراء قوية ⚡"})
    elif rsi7 >= 65:
        R["bear"] += 1
        R["signals"].append({"name": "RSI(7) 1m", "icon": "🔴", "value": f"{rsi7:.1f}", "note": "ذروة شراء"})
    else:
        R["signals"].append({"name": "RSI(7) 1m", "icon": "⚪", "value": f"{rsi7:.1f}", "note": "محايد"})
    
    # ─── 2. EMA Cross (5/13) على 1m ───
    ema5 = _scalp_ema(cl1, 5)
    ema13 = _scalp_ema(cl1, 13)
    ema5_now = float(ema5.iloc[-1])
    ema13_now = float(ema13.iloc[-1])
    ema5_prev = float(ema5.iloc[-2])
    ema13_prev = float(ema13.iloc[-2])
    
    if ema5_now > ema13_now and ema5_prev <= ema13_prev:
        R["bull"] += 2
        R["signals"].append({"name": "EMA Cross 1m", "icon": "✅", "value": "Golden Cross", "note": "اختراق صعودي ⚡"})
    elif ema5_now < ema13_now and ema5_prev >= ema13_prev:
        R["bear"] += 2
        R["signals"].append({"name": "EMA Cross 1m", "icon": "🔴", "value": "Death Cross", "note": "اختراق هبوطي ⚡"})
    elif ema5_now > ema13_now:
        R["bull"] += 1
        R["signals"].append({"name": "EMA Cross 1m", "icon": "✅", "value": "EMA5 > EMA13", "note": "صعودي"})
    elif ema5_now < ema13_now:
        R["bear"] += 1
        R["signals"].append({"name": "EMA Cross 1m", "icon": "🔴", "value": "EMA5 < EMA13", "note": "هبوطي"})
    else:
        R["signals"].append({"name": "EMA Cross 1m", "icon": "⚪", "value": "متشابك", "note": "محايد"})
    
    # ─── 3. Bollinger Bands على 5m ───
    cl5 = df_5m["Close"]
    bb_upper, bb_mid, bb_lower = _scalp_bollinger(cl5, 20, 2.0)
    bb_u = float(bb_upper.iloc[-1])
    bb_m = float(bb_mid.iloc[-1])
    bb_l = float(bb_lower.iloc[-1])
    
    bb_width = (bb_u - bb_l) / bb_m * 100
    R["bb_width"] = bb_width
    
    if price <= bb_l * 1.001:
        R["bull"] += 2
        R["signals"].append({"name": "Bollinger 5m", "icon": "✅", "value": "Lower Band", "note": "ارتداد محتمل ⚡"})
    elif price >= bb_u * 0.999:
        R["bear"] += 2
        R["signals"].append({"name": "Bollinger 5m", "icon": "🔴", "value": "Upper Band", "note": "ارتداد هبوطي ⚡"})
    elif bb_width < 1.0:
        R["signals"].append({"name": "Bollinger 5m", "icon": "⚠️", "value": f"Squeeze {bb_width:.2f}%", "note": "اختراق وشيك"})
        R["warnings"].append("Bollinger Squeeze — اختراق قوي وشيك")
    else:
        position = (price - bb_l) / (bb_u - bb_l) * 100
        R["signals"].append({"name": "Bollinger 5m", "icon": "⚪", "value": f"{position:.0f}%", "note": "وسط الباند"})
    
    # ─── 4. Volume Spike (لو متاح) ───
    if vo1 is not None and len(vo1) >= 20:
        vol_avg = float(vo1.iloc[-20:].mean())
        vol_now = float(vo1.iloc[-1])
        if vol_avg > 0:
            vol_ratio = vol_now / vol_avg
            R["vol_ratio"] = vol_ratio
            
            # اتجاه الشمعة الحالية
            candle_bullish = cl1.iloc[-1] > op1.iloc[-1]
            
            if vol_ratio >= 3.0:
                if candle_bullish:
                    R["bull"] += 2
                    R["signals"].append({"name": "Volume Spike", "icon": "✅", "value": f"×{vol_ratio:.1f}", "note": "ضغط شراء قوي ⚡"})
                else:
                    R["bear"] += 2
                    R["signals"].append({"name": "Volume Spike", "icon": "🔴", "value": f"×{vol_ratio:.1f}", "note": "ضغط بيع قوي ⚡"})
            elif vol_ratio >= 1.8:
                if candle_bullish:
                    R["bull"] += 1
                    R["signals"].append({"name": "Volume", "icon": "✅", "value": f"×{vol_ratio:.1f}", "note": "حجم شراء جيد"})
                else:
                    R["bear"] += 1
                    R["signals"].append({"name": "Volume", "icon": "🔴", "value": f"×{vol_ratio:.1f}", "note": "حجم بيع جيد"})
            else:
                R["signals"].append({"name": "Volume", "icon": "⚪", "value": f"×{vol_ratio:.1f}", "note": "حجم عادي"})
    else:
        R["signals"].append({"name": "Volume", "icon": "⚪", "value": "—", "note": "غير متاح للفوركس"})
    
    # ─── 5. Stochastic (14,3) على 1m ───
    k, d = _scalp_stochastic(df_1m, 14, 3)
    k_now = float(k.iloc[-1]) if not pd.isna(k.iloc[-1]) else 50
    d_now = float(d.iloc[-1]) if not pd.isna(d.iloc[-1]) else 50
    R["stoch_k"] = k_now
    R["stoch_d"] = d_now
    
    if k_now < 20 and k_now > d_now:
        R["bull"] += 1
        R["signals"].append({"name": "Stochastic", "icon": "✅", "value": f"K={k_now:.0f}", "note": "ذروة بيع + Cross صعودي"})
    elif k_now > 80 and k_now < d_now:
        R["bear"] += 1
        R["signals"].append({"name": "Stochastic", "icon": "🔴", "value": f"K={k_now:.0f}", "note": "ذروة شراء + Cross هبوطي"})
    else:
        R["signals"].append({"name": "Stochastic", "icon": "⚪", "value": f"K={k_now:.0f}", "note": "محايد"})
    
    # ─── 6. ATR Momentum على 1m ───
    atr_now = _scalp_atr(df_1m, 14)
    atr_avg = float(_scalp_atr(df_1m.iloc[:-5], 14)) if len(df_1m) > 20 else atr_now
    R["atr"] = atr_now
    
    atr_pct = (atr_now / price * 100) if price > 0 else 0
    R["atr_pct"] = atr_pct
    
    if atr_avg > 0 and atr_now / atr_avg > 1.4:
        R["signals"].append({"name": "ATR Momentum", "icon": "⚠️", "value": f"{atr_pct:.3f}%", "note": "تقلّب عالي - Volatility"})
        R["warnings"].append("ATR مرتفع — احذر الـwhipsaws")
    else:
        R["signals"].append({"name": "ATR Momentum", "icon": "⚪", "value": f"{atr_pct:.3f}%", "note": "تقلّب طبيعي"})
    
    # ─── 7. Candle Pattern على 1m (Engulfing/Hammer/Star) ───
    if len(df_1m) >= 3:
        c0 = df_1m.iloc[-1]  # الحالية
        c1 = df_1m.iloc[-2]  # السابقة
        c2 = df_1m.iloc[-3]
        
        body0 = abs(c0["Close"] - c0["Open"])
        body1 = abs(c1["Close"] - c1["Open"])
        wick_top0 = c0["High"] - max(c0["Open"], c0["Close"])
        wick_bot0 = min(c0["Open"], c0["Close"]) - c0["Low"]
        
        # Bullish Engulfing
        if (c1["Close"] < c1["Open"] and c0["Close"] > c0["Open"] 
            and c0["Close"] > c1["Open"] and c0["Open"] < c1["Close"]):
            R["bull"] += 2
            R["signals"].append({"name": "Candle Pattern", "icon": "✅", "value": "Bullish Engulfing", "note": "ابتلاع صعودي ⚡"})
        # Bearish Engulfing
        elif (c1["Close"] > c1["Open"] and c0["Close"] < c0["Open"]
              and c0["Close"] < c1["Open"] and c0["Open"] > c1["Close"]):
            R["bear"] += 2
            R["signals"].append({"name": "Candle Pattern", "icon": "🔴", "value": "Bearish Engulfing", "note": "ابتلاع هبوطي ⚡"})
        # Hammer (bullish reversal)
        elif body0 > 0 and wick_bot0 > body0 * 2 and wick_top0 < body0 * 0.5:
            R["bull"] += 1
            R["signals"].append({"name": "Candle Pattern", "icon": "✅", "value": "Hammer", "note": "مطرقة - انعكاس صعودي"})
        # Shooting Star
        elif body0 > 0 and wick_top0 > body0 * 2 and wick_bot0 < body0 * 0.5:
            R["bear"] += 1
            R["signals"].append({"name": "Candle Pattern", "icon": "🔴", "value": "Shooting Star", "note": "نجمة هابطة"})
        else:
            R["signals"].append({"name": "Candle Pattern", "icon": "⚪", "value": "—", "note": "لا نمط واضح"})
    
    # ─── القرار النهائي ───
    score_diff = R["bull"] - R["bear"]
    if score_diff >= 4:
        R["decision"] = "LONG"
        R["decision_strength"] = "STRONG"
        R["decision_icon"] = "🟢⚡"
    elif score_diff >= 2:
        R["decision"] = "LONG"
        R["decision_strength"] = "MEDIUM"
        R["decision_icon"] = "🟢"
    elif score_diff <= -4:
        R["decision"] = "SHORT"
        R["decision_strength"] = "STRONG"
        R["decision_icon"] = "🔴⚡"
    elif score_diff <= -2:
        R["decision"] = "SHORT"
        R["decision_strength"] = "MEDIUM"
        R["decision_icon"] = "🔴"
    else:
        R["decision"] = "WAIT"
        R["decision_strength"] = "—"
        R["decision_icon"] = "⏳"
    
    # ─── SL/TP المحسوب على ATR ───
    is_long = R["decision"] == "LONG"
    sl_distance = atr_now * 0.7  # ضيّق
    tp1_distance = atr_now * 0.7    # 1:1
    tp2_distance = atr_now * 1.05   # 1:1.5
    tp3_distance = atr_now * 1.75   # 1:2.5
    
    if R["decision"] in ("LONG", "SHORT"):
        if is_long:
            R["sl"] = price - sl_distance
            R["tp1"] = price + tp1_distance
            R["tp2"] = price + tp2_distance
            R["tp3"] = price + tp3_distance
        else:
            R["sl"] = price + sl_distance
            R["tp1"] = price - tp1_distance
            R["tp2"] = price - tp2_distance
            R["tp3"] = price - tp3_distance
        
        R["sl_pct"] = sl_distance / price * 100
    else:
        R["sl"] = R["tp1"] = R["tp2"] = R["tp3"] = None
        R["sl_pct"] = 0
    
    # ─── المدة المتوقعة + الرافعة المقترحة ───
    if R["decision_strength"] == "STRONG":
        R["duration"] = "5-15 دقيقة"
        R["leverage_suggestion"] = "x5-x10 (للفوركس) | x10-x20 (للذهب)"
    elif R["decision_strength"] == "MEDIUM":
        R["duration"] = "10-30 دقيقة"
        R["leverage_suggestion"] = "x3-x5 (محافظ)"
    else:
        R["duration"] = "—"
        R["leverage_suggestion"] = "لا تدخل"
    
    return R


def format_scalp(R: Dict) -> str:
    """تنسيق رسالة الـScalping للـTelegram."""
    if not R:
        return "⚠️ تعذّر تحليل Scalping — تأكد من توفر البيانات"
    
    asset = R["asset"]
    decision = R["decision"]
    icon = R["decision_icon"]
    price = R["current_price"]
    
    # تحديد عدد الـdecimals حسب الأصل
    decimals = 5 if "/" in asset and "JPY" not in asset else 3 if "JPY" in asset else 2
    
    lines = []
    lines.append(f"⚡ *SCALPING — {asset}* {icon}")
    lines.append("═" * 33)
    lines.append(f"💰 السعر: `{price:,.{decimals}f}`")
    lines.append(f"🕐 الوقت: {datetime.now(pytz.timezone(DEFAULT_TZ)).strftime('%H:%M:%S')}")
    if R.get("source") == "polygon" or R.get("source") == "polygon_scaled":
        lines.append(f"📡 المصدر: Polygon Real-time ✅")
    lines.append("")
    
    # القرار
    if decision == "WAIT":
        lines.append("⏳ *القرار: انتظر*")
        lines.append(f"_السوق محايد حالياً ({R['bull']} bull vs {R['bear']} bear)_")
        lines.append("")
    else:
        strength = R["decision_strength"]
        decision_ar = "صفقة شراء سريعة" if decision == "LONG" else "صفقة بيع سريعة"
        lines.append(f"🎯 *القرار: {decision} — {decision_ar}*")
        lines.append(f"💪 قوة الإشارة: {strength}")
        lines.append(f"⏱️ المدة المتوقعة: `{R['duration']}`")
        lines.append("")
    
    # المؤشرات
    lines.append("📊 *المؤشرات السبعة:*")
    lines.append("─" * 33)
    for s in R["signals"]:
        lines.append(f"{s['icon']} *{s['name']}*: `{s['value']}` — {s['note']}")
    lines.append("")
    
    # Score
    lines.append(f"📈 *النقاط:* Bull={R['bull']} | Bear={R['bear']}")
    lines.append("")
    
    # SL/TP
    if R.get("sl"):
        lines.append("🎯 *مستويات الصفقة:*")
        lines.append("─" * 33)
        lines.append(f"🛑 SL: `{R['sl']:,.{decimals}f}` ({R['sl_pct']:.2f}% بعيد)")
        lines.append(f"🟢 TP1: `{R['tp1']:,.{decimals}f}` (R:R 1:1)")
        lines.append(f"🟡 TP2: `{R['tp2']:,.{decimals}f}` (R:R 1:1.5)")
        lines.append(f"🔴 TP3: `{R['tp3']:,.{decimals}f}` (R:R 1:2.5)")
        lines.append("")
        lines.append(f"⚙️ *الرافعة المقترحة:* {R['leverage_suggestion']}")
        lines.append("")
        lines.append("📋 *إدارة الصفقة:*")
        lines.append("• اقفل 50% عند TP1")
        lines.append("• اقفل 30% عند TP2 + حرّك SL لـbreakeven")
        lines.append("• اترك 20% للـTP3 (runner)")
        lines.append("")
    
    # تحذيرات
    if R.get("warnings"):
        lines.append("⚠️ *تحذيرات:*")
        for w in R["warnings"]:
            lines.append(f"• {w}")
        lines.append("")
    
    lines.append("⚠️ _Scalping = مخاطرة عالية — لا تستخدم >1% من رأس المال_")
    lines.append("⚠️ _تحليل تعليمي — ليس نصيحة استثمارية_")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 12) AI BRAINS — Claude + Gemini + OpenAI
# ═══════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """أنت محلل تنفيذي في صندوق تحوّط Wall Street ($5B AUM).
خبرتك 20+ سنة في FX و Precious Metals.
تطبق منهجية Bridgewater (All Weather) + Goldman Sachs FX Research.

تركيزك:
  • علاقة Fed Policy ↔ Yield Curve ↔ Gold ↔ DXY
  • Smart Money positioning (CFTC COT/TFF)
  • Options Flow sentiment (Put/Call ratios)
  • السياق الماكرو والجيوسياسي
  • Multi-timeframe analysis (D1/H4/H1)

أسلوبك:
  • مهني، دقيق، عملي
  • سيناريوهات احتمالية بأرقام
  • مستويات محددة (Entry/SL/TP)
  • R:R واضح
  • العربية الفصحى + المصطلحات الإنجليزية المهنية

⚠️ تحليلات تعليمية فقط — ليست نصيحة استثمارية.
"""


def ask_claude(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 1500) -> str:
    if not CLAUDE_API_KEY:
        return "⚪ Claude غير مكوّن"
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if r.status_code == 200:
            return r.json()["content"][0]["text"]
        return f"⚠️ Claude HTTP {r.status_code}"
    except Exception as e:
        return f"⚠️ Claude: {e}"


def ask_gemini(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 1500) -> str:
    if not GEMINI_API_KEY:
        return "⚪ Gemini غير مكوّن"
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        r = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.7,
                },
            },
            timeout=60,
        )
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"⚠️ Gemini HTTP {r.status_code}"
    except Exception as e:
        return f"⚠️ Gemini: {e}"


def ask_openai(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 1500) -> str:
    if not OPENAI_API_KEY:
        return "⚪ OpenAI غير مكوّن"
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=60,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"⚠️ OpenAI HTTP {r.status_code}"
    except Exception as e:
        return f"⚠️ OpenAI: {e}"


def multi_ai(prompt: str, system: str = SYSTEM_PROMPT) -> Dict[str, str]:
    """تشغيل الـ3 AIs بالتوازي."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            "Claude": pool.submit(ask_claude, prompt, system),
            "Gemini": pool.submit(ask_gemini, prompt, system),
            "OpenAI": pool.submit(ask_openai, prompt, system),
        }
        return {k: f.result() for k, f in futures.items()}


# ═══════════════════════════════════════════════════════════════════════
# 13) MASTER RECOMMENDATION ENGINE
# ═══════════════════════════════════════════════════════════════════════
RECOMMENDATION_PROMPT = """مهمتك: بعد قراءة كل البيانات أدناه، أعطِ توصية تداول
نهائية كما يفعل محلل تنفيذي في صندوق تحوّط محترف.

البيانات الكاملة:
{data}

تنسيق الإجابة بدقة (التزم بكل الأقسام):

🎯 **التوصية:** [BUY / SELL / HOLD / ADD / REDUCE]
💪 **الثقة:** [قوية/متوسطة/ضعيفة] (X/10)
⏱️ **الإطار:** [قصير 1-7 أيام / متوسط 1-4 أسابيع / طويل]

═══════════════════════════════════════
📅 **رأي اليوم (Today's View):**
═══════════════════════════════════════

🔍 **الاتجاه المُتَوقَّع لليوم:**
[Bullish / Bearish / Neutral / متذبذب] — جملة واحدة واضحة

🌅 **سيناريو الجلسة:**
• الجلسة الآسيوية: [التوقع + المستوى]
• الجلسة الأوروبية: [التوقع + المستوى]
• الجلسة الأمريكية: [التوقع + المستوى]

📰 **الأخبار المؤثرة اليوم:**
[اقرأ من التقويم الاقتصادي والـRSS - حدّد كل خبر هام لليوم/الغد]
• [وقت الخبر] [اسم الخبر] — التأثير المتوقع: [Bullish/Bearish] على [الأصل]
• [وقت ثاني] [خبر ثاني] — التأثير: ...
• [خبر ثالث إن وُجد] — ...

⚡ **خطة التداول اليوم (Intraday Plan):**
1. **قبل الأخبار:** [إيه تعمل دلوقتي - دخول/انتظار/خروج]
2. **أثناء الأخبار:** [تجنب الدخول / فرصة محتملة]
3. **بعد الأخبار:** [إيه تتوقع تشوفه]

═══════════════════════════════════════
📊 **التحليل الشامل (5 نقاط):**
═══════════════════════════════════════
• [نقطة فندامنتل - macro/CPI/Fed]
• [نقطة Smart Money - COT/Options]
• [نقطة Yield Curve / Fed expectations]
• [نقطة Options Sentiment - P/C ratio]
• [نقطة فني - RSI/MACD/EMAs/Order Blocks/FVG]

🎲 **السيناريوهات (الأسبوع القادم):**
• Bull (X%): [الوصف + المستوى المستهدف]
• Base (X%): [الوصف + المستوى الأرجح]
• Bear (X%): [الوصف + مستوى الخطر]

🛡️ **مستوى الدخول:**
• Entry: [رقم واحد فقط - السعر الأمثل للدخول]
• المنطق: [ليه الدخول هنا - ربط بـTechnical level]

⚠️ **العوامل الحاسمة (Top 3 Catalysts):**
1. **[تاريخ/وقت]** [الحدث] — التأثير المحتمل: [...]
2. **[تاريخ/وقت]** [الحدث] — التأثير: [...]
3. **[تاريخ/وقت]** [الحدث] — التأثير: [...]

🎯 **خلاصة الرأي بجملة واحدة:**
[ملخص حاسم: إيه تعمل اليوم وعلى أي مستوى]

⚡ **ملاحظة:** لا تعطي SL/TP — البوت يحسبها تلقائياً بـSmart Risk
(Order Blocks + Liquidity Pools + ATR + Round Numbers).

📝 _تحليل تعليمي — ليس نصيحة استثمارية._
"""


def gather_all_data(asset: str = "Gold", chat_id: str = None) -> str:
    """جمع كل البيانات للـAI."""
    prices = fetch_prices()
    cot = fetch_cot_data()
    yc = analyze_yield_curve(prices)
    fed = derive_fed_expectations(prices)
    macro = fred_get_macro_snapshot() if FRED_API_KEY else {}
    cal = fetch_te_calendar(days_ahead=7)[:8]
    
    # Options data للذهب (فقط لو الميزة مُفعّلة + اشتراك Options Starter)
    opts = polygon_options_aggregate("GLD") if (ENABLE_OPTIONS and POLYGON_API_KEY) else {}
    
    # Technical analysis
    ta_ticker = "GC=F" if asset == "Gold" else "DX-Y.NYB"
    ta = technical_analysis(ta_ticker)
    
    # News
    news_kw = (["gold", "fed", "fomc", "inflation", "cpi"] if asset == "Gold"
               else ["dollar", "dxy", "fed", "ecb", "boe", "rate"])
    news = filter_news_by_topic(
        fetch_news(max_per_source=4, hours_back=48), news_kw
    )[:6]
    
    # Memory: آخر توصية للـuser
    last_rec = None
    if chat_id:
        last_rec = db_exec(
            "SELECT * FROM recommendations WHERE chat_id=? AND asset=? "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id, asset), fetch="one")
    
    # تجميع
    p_text = "\n".join(
        f"  {k}: {v['price']:.4f} (يومي {v['change_pct']:+.2f}%, أسبوعي {v['week_pct']:+.2f}%)"
        for k, v in prices.items()
    )
    
    cot_text = "\n".join(
        f"  {a}: Net={d['net']:+,} | تغيّر أسبوعي={d['weekly_change']:+,}"
        for a, d in cot.items()
    ) if cot else "  غير متاح"
    
    macro_text = "\n".join(
        f"  {k}: {v['value']:.2f} (سابق {v['previous']:.2f}, تغيّر {v['change']:+.2f})"
        for k, v in macro.items()
    ) if macro else "  غير متاح"
    
    # تقسيم التقويم: اليوم / غداً / هذا الأسبوع
    now_tz = datetime.now(pytz.timezone(DEFAULT_TZ))
    today_str = now_tz.strftime('%Y-%m-%d')
    tomorrow_str = (now_tz + timedelta(days=1)).strftime('%Y-%m-%d')
    
    cal_today = []
    cal_tomorrow = []
    cal_week = []
    for e in cal:
        date_field = e.get('Date', '')[:10]
        if date_field == today_str:
            cal_today.append(e)
        elif date_field == tomorrow_str:
            cal_tomorrow.append(e)
        else:
            cal_week.append(e)
    
    def fmt_event(e):
        time_part = e.get('Date', '—')[11:16] if len(e.get('Date', '')) > 10 else ''
        importance = e.get('Importance', '') or e.get('importance', '')
        imp_icon = "🔴" if str(importance) == "3" else "🟡" if str(importance) == "2" else "⚪"
        return f"  {imp_icon} {time_part} [{e.get('Country','—')}] {e.get('Event','—')[:60]}"
    
    cal_today_text = "\n".join(fmt_event(e) for e in cal_today) if cal_today else "  لا أحداث مؤثرة اليوم"
    cal_tomorrow_text = "\n".join(fmt_event(e) for e in cal_tomorrow) if cal_tomorrow else "  لا أحداث غداً"
    cal_week_text = "\n".join(fmt_event(e) for e in cal_week[:5]) if cal_week else "  —"
    
    # نصف القائمة العامة كـbackup
    cal_text = "\n".join(
        f"  {e.get('Date','—')[:16]} [{e.get('Country','—')}] {e.get('Event','—')[:60]}"
        for e in cal
    ) if cal else "  غير متاح"
    
    opts_text = (f"  P/C Volume: {opts.get('pc_volume_ratio','—')}\n"
                 f"  P/C Open Interest: {opts.get('pc_oi_ratio','—')}\n"
                 f"  Sentiment: {opts.get('sentiment','—')}\n"
                 f"  Calls Vol: {opts.get('calls_volume','—')} | "
                 f"Puts Vol: {opts.get('puts_volume','—')}") if opts else "  غير متاح"
    
    ta_text = ""
    if ta:
        ta_text = (f"  السعر: {ta['price']:.4f}\n"
                   f"  RSI: {ta['rsi']:.1f} ({ta['rsi_signal']})\n"
                   f"  MACD: {ta['macd_signal']}\n"
                   f"  EMAs: {ta['ema_trend']}\n"
                   f"  EMA20={ta['ema_20']:.2f} | EMA50={ta['ema_50']:.2f} | "
                   f"EMA200={ta['ema_200']:.2f}\n"
                   f"  BB: {ta['bb_signal']}\n"
                   f"  Upper={ta['bb_upper']:.2f} | Lower={ta['bb_lower']:.2f}\n"
                   f"  ATR(14): {ta['atr']:.2f}\n"
                   f"  Structure: {ta['structure']}\n")
        if ta["order_blocks"]["bullish"]:
            ta_text += f"  Bullish OB: {ta['order_blocks']['bullish'][-1]['level']:.2f}\n"
        if ta["order_blocks"]["bearish"]:
            ta_text += f"  Bearish OB: {ta['order_blocks']['bearish'][-1]['level']:.2f}\n"
    
    # تقسيم الأخبار: آخر 6 ساعات (urgent) vs أقدم
    now_utc = datetime.now(pytz.UTC)
    news_urgent = []
    news_today = []
    for n in news:
        try:
            pub_time = n.get('published_at') or n.get('pubDate', '')
            if pub_time:
                if isinstance(pub_time, str):
                    pub_dt = datetime.fromisoformat(pub_time.replace('Z', '+00:00'))
                else:
                    pub_dt = pub_time
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=pytz.UTC)
                hours_ago = (now_utc - pub_dt).total_seconds() / 3600
                if hours_ago <= 6:
                    news_urgent.append(n)
                else:
                    news_today.append(n)
            else:
                news_today.append(n)
        except Exception:
            news_today.append(n)
    
    news_urgent_text = "\n".join(
        f"  🔴 [{n['source']}] {n['title'][:90]}"
        for n in news_urgent[:4]
    ) if news_urgent else "  لا أخبار عاجلة في آخر 6 ساعات"
    
    news_today_text = "\n".join(
        f"  • [{n['source']}] {n['title'][:90]}"
        for n in news_today[:4]
    ) if news_today else "  —"
    
    # القائمة الكاملة كـbackup
    news_text = "\n".join(
        f"  • [{n['source']}] {n['title'][:90]}"
        for n in news
    ) if news else "  لا توجد"
    
    fed_text = (f"  3M={fed.get('y3m','—')}% | 5Y={fed.get('y5y','—')}% | 10Y={fed.get('y10y','—')}%\n"
                f"  Bias: {fed.get('bias','—')} | {fed.get('signal','—')}") if fed.get('y3m') else "غير متاح"
    
    yc_text = (f"  Spread 3M-10Y: {yc.get('spread_3M_10Y','—')}\n"
               f"  {yc.get('signal','—')}") if yc.get('signal') else "غير متاح"
    
    vix = prices.get("VIX", {}).get("price", 0)
    fear = ("🔴 خوف شديد" if vix > 25 else "🟡 خوف معتدل" if vix > 18 else "🟢 هدوء")
    
    last_rec_text = ""
    if last_rec:
        last_rec_text = (f"\n📌 آخر توصية لك على {asset}:\n"
                         f"  Action: {last_rec['action']} @ {last_rec.get('entry_price','—')}\n"
                         f"  Status: {last_rec['status']}\n"
                         f"  PnL: {last_rec.get('pnl_pct','—')}%\n"
                         f"  Reasoning: {last_rec.get('reasoning','—')[:200]}\n")
    
    return f"""━━━ الأصل المستهدف: {asset} ━━━
📅 التاريخ والوقت: {now_tz.strftime('%A %d/%m/%Y %H:%M')} ({DEFAULT_TZ})

📊 الأسعار اللحظية:
{p_text}

📈 التحليل الفني (Daily):
{ta_text}

🐋 Smart Money (CFTC COT الأسبوعي):
{cot_text}

💎 Options Sentiment ({opts.get('underlying','GLD')}):
{opts_text}

🏦 توقعات الفيدرالي (Yield Curve):
{fed_text}

📈 منحنى العائد:
{yc_text}

🌍 Macro Snapshot (FRED):
{macro_text}

═══ التقويم الاقتصادي ═══

🔴 *أحداث اليوم* ({today_str}):
{cal_today_text}

🟡 *أحداث غداً* ({tomorrow_str}):
{cal_tomorrow_text}

⚪ *باقي الأسبوع*:
{cal_week_text}

═══ الأخبار ═══

🔴 *أخبار عاجلة* (آخر 6 ساعات):
{news_urgent_text}

📰 *أخبار اليوم/الأمس*:
{news_today_text}

😰 مؤشر الخوف:
  VIX: {vix:.2f} ← {fear}
{last_rec_text}

═══════════════════════════════════════
⚡ تذكير للـAI:
- اقرأ "أحداث اليوم" و"أخبار عاجلة" بدقة
- في "رأي اليوم"، اربط التوقعات بالأحداث المحددة (مش عام)
- في "Top 3 Catalysts" حدّد أوقات/تواريخ من القائمة فعلياً
- لو في خبر FOMC/CPI/NFP اليوم → ركز عليه!
═══════════════════════════════════════
"""


def build_recommendation(asset: str = "Gold", chat_id: str = None) -> Dict:
    """يبني توصية كاملة من 3 AIs + إجماع + Smart Risk + يحفظها في DB."""
    data_block = gather_all_data(asset, chat_id)
    prompt = RECOMMENDATION_PROMPT.format(data=data_block)
    
    sys_p = (f"أنت محلل تنفيذي في صندوق تحوّط $5B AUM.\n"
             f"الأصل المستهدف: {asset}.\n"
             f"تطبّق Bridgewater + Goldman Sachs methodology.\n"
             f"استخدم *كل* البيانات المعطاة في توصيتك.")
    
    analyses = multi_ai(prompt, sys_p)
    
    # طلب الإجماع من Claude
    valid = {n: t for n, t in analyses.items()
             if not t.startswith(("⚪", "⚠️"))}
    if not valid:
        return {"asset": asset, "analyses": analyses, "final": "❌ كل AIs فشلوا",
                "data_block": data_block, "smart_risk_text": ""}
    
    consensus_prompt = f"""3 محللين خبراء أعطوا توصياتهم لـ{asset}:

{chr(10).join(f'### {n}:{chr(10)}{t}' for n, t in valid.items())}

كرئيس قسم البحث، استخرج:
1. الإجماع (التوصية الموحّدة)
2. نقاط الاتفاق والاختلاف
3. الحكم النهائي بهذا التنسيق:

🎯 **الحكم النهائي:** [BUY / SELL / HOLD / ADD / REDUCE]
💪 **درجة الإجماع:** [قوي/متوسط/ضعيف]
📌 **النقاط الموحّدة (3-5 نقاط):**
🎲 **السيناريو الأرجح + الاحتمال:**
🛡️ **مستوى الدخول الموصى به:**
• Entry: [رقم واحد فقط]
• المنطق: [ليه]
⚠️ **شروط إعادة التقييم:**

⚡ **ملاحظة:** البوت سيحسب SL/TP تلقائياً بناءً على Order Blocks
والـLiquidity Pools — لا تحتاج تعطيها.

تحليل تعليمي فقط.
"""
    final = ask_claude(
        consensus_prompt,
        system="أنت رئيس قسم البحث في صندوق تحوّط — تستخلص الإجماع.",
        max_tokens=1500,
    )
    
    # ─── SMART RISK MANAGEMENT ───
    smart_risk_text = ""
    risk_data = None
    rec_data = parse_recommendation(final)
    
    if rec_data.get("action") and rec_data.get("entry"):
        action = rec_data["action"]
        entry = rec_data["entry"]
        
        # تخطّي HOLD/REDUCE لأنها لا تحتاج SL/TP جديد
        if action in ("BUY", "SELL", "ADD"):
            try:
                # جلب TA + DataFrame
                ta_ticker = "GC=F" if asset == "Gold" else "DX-Y.NYB"
                ta_full = technical_analysis(ta_ticker)
                
                # نحتاج DataFrame خام للـSwing detection
                # للذهب: نستخدم scaled DataFrame ليكون متناسق مع السعر الصحيح
                if asset == "Gold":
                    df_daily, _ = get_gold_dataframe_scaled(period="6mo", interval="1d")
                    if df_daily is None or df_daily.empty:
                        # fallback لو فشل
                        t = yf.Ticker(ta_ticker)
                        df_daily = t.history(period="6mo", interval="1d")
                else:
                    t = yf.Ticker(ta_ticker)
                    df_daily = t.history(period="6mo", interval="1d")
                
                if ta_full and df_daily is not None and not df_daily.empty:
                    risk_data = smart_risk.build_full_risk_analysis(
                        entry=entry,
                        action=action,
                        ta=ta_full,
                        df=df_daily,
                        asset=asset,
                        capital=4000,  # default
                    )
                    smart_risk_text = smart_risk.format_smart_risk_advanced(risk_data)
                    
                    # استخراج SL/TPs الموصى بها للحفظ
                    rec_sl_key = risk_data["sl"]["recommended"]
                    rec_data["sl"] = risk_data["sl"][rec_sl_key]["price"]
                    rec_data["tp1"] = risk_data["tp"]["tp1"]["price"]
                    rec_data["tp2"] = risk_data["tp"]["tp2"]["price"]
                    rec_data["tp3"] = risk_data["tp"]["tp3"]["price"]
            except Exception as e:
                log.warning(f"Smart Risk failed: {e}")
                smart_risk_text = f"⚠️ Smart Risk Analysis تعذّر: {e}"
    
    # حفظ في DB
    if chat_id and rec_data.get("action"):
        risk_json = json.dumps(risk_data, default=str) if risk_data else None
        db_exec(
            """INSERT INTO recommendations 
               (chat_id, asset, action, entry_price, stop_loss, 
                take_profit_1, take_profit_2, take_profit_3, confidence, timeframe, 
                reasoning, created_at, risk_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, asset, rec_data["action"],
             rec_data.get("entry"), rec_data.get("sl"),
             rec_data.get("tp1"), rec_data.get("tp2"), rec_data.get("tp3"),
             rec_data.get("confidence", 5),
             rec_data.get("timeframe", "متوسط"),
             final[:1000],
             datetime.now(timezone.utc).isoformat(),
             risk_json),
        )
    
    return {
        "asset": asset,
        "analyses": analyses,
        "final": final,
        "data_block": data_block,
        "parsed": rec_data,
        "smart_risk_text": smart_risk_text,
        "risk_data": risk_data,
    }


def parse_recommendation(text: str) -> Dict:
    """استخراج Entry/SL/TP من نص التوصية."""
    out = {}
    
    # Action
    for kw in ["BUY", "SELL", "HOLD", "ADD", "REDUCE"]:
        if kw in text.upper():
            out["action"] = kw
            break
    
    # Confidence
    conf_match = re.search(r"(\d+)/10", text)
    if conf_match:
        out["confidence"] = int(conf_match.group(1))
    
    # Entry/SL/TP أرقام
    patterns = {
        "entry": r"Entry[:\s]+\$?([\d,]+\.?\d*)",
        "sl":    r"Stop[\s_]?Loss[:\s]+\$?([\d,]+\.?\d*)",
        "tp1":   r"Take[\s_]?Profit[\s_]?1[:\s]+\$?([\d,]+\.?\d*)",
        "tp2":   r"Take[\s_]?Profit[\s_]?2[:\s]+\$?([\d,]+\.?\d*)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                out[key] = float(m.group(1).replace(",", ""))
            except:
                pass
    
    return out


# ═══════════════════════════════════════════════════════════════════════
# 14) PERFORMANCE TRACKING
# ═══════════════════════════════════════════════════════════════════════
def update_recommendation_status(chat_id: str = None) -> int:
    """تحديث حالة التوصيات المفتوحة."""
    if chat_id:
        recs = db_exec(
            "SELECT * FROM recommendations WHERE status='OPEN' AND chat_id=?",
            (chat_id,), fetch="all")
    else:
        recs = db_exec(
            "SELECT * FROM recommendations WHERE status='OPEN'", fetch="all")
    
    if not recs:
        return 0
    
    updated = 0
    prices = fetch_prices()
    
    for rec in recs:
        ticker_map = {"Gold": "Gold (XAUUSD)", "USD/DXY": "DXY (Dollar)"}
        price_key = ticker_map.get(rec["asset"], rec["asset"])
        
        cur = prices.get(price_key, {}).get("price")
        if not cur or not rec.get("entry_price"):
            continue
        
        entry = rec["entry_price"]
        sl    = rec.get("stop_loss")
        tp1   = rec.get("take_profit_1")
        tp2   = rec.get("take_profit_2")
        tp3   = rec.get("take_profit_3")
        
        outcome = None
        pnl_pct = (cur - entry) / entry * 100
        
        if rec["action"] in ("BUY", "ADD"):
            if sl and cur <= sl:
                outcome, pnl_pct = "SL_HIT", (sl - entry) / entry * 100
            elif tp3 and cur >= tp3:
                outcome, pnl_pct = "TP3_HIT", (tp3 - entry) / entry * 100
            elif tp2 and cur >= tp2:
                outcome, pnl_pct = "TP2_HIT", (tp2 - entry) / entry * 100
            elif tp1 and cur >= tp1:
                outcome, pnl_pct = "TP1_HIT", (tp1 - entry) / entry * 100
        elif rec["action"] in ("SELL", "REDUCE"):
            pnl_pct = (entry - cur) / entry * 100
            if sl and cur >= sl:
                outcome, pnl_pct = "SL_HIT", (entry - sl) / entry * 100
            elif tp3 and cur <= tp3:
                outcome, pnl_pct = "TP3_HIT", (entry - tp3) / entry * 100
            elif tp2 and cur <= tp2:
                outcome, pnl_pct = "TP2_HIT", (entry - tp2) / entry * 100
            elif tp1 and cur <= tp1:
                outcome, pnl_pct = "TP1_HIT", (entry - tp1) / entry * 100
        
        if outcome:
            db_exec(
                "UPDATE recommendations SET status='CLOSED', outcome=?, "
                "pnl_pct=?, closed_at=? WHERE id=?",
                (outcome, pnl_pct, datetime.now(timezone.utc).isoformat(), rec["id"]),
            )
            updated += 1
    
    return updated


def performance_report(chat_id: str = None) -> str:
    """تقرير أداء التوصيات."""
    update_recommendation_status(chat_id)
    
    if chat_id:
        all_recs = db_exec(
            "SELECT * FROM recommendations WHERE chat_id=? "
            "ORDER BY created_at DESC LIMIT 50",
            (chat_id,), fetch="all")
    else:
        all_recs = db_exec(
            "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 50",
            fetch="all")
    
    if not all_recs:
        return "📊 *تقرير الأداء*\n\nلا توجد توصيات مسجلة بعد"
    
    closed = [r for r in all_recs if r["status"] == "CLOSED"]
    open_  = [r for r in all_recs if r["status"] == "OPEN"]
    
    wins   = [r for r in closed if r.get("outcome") in ("TP1_HIT", "TP2_HIT")]
    losses = [r for r in closed if r.get("outcome") == "SL_HIT"]
    
    total_pnl  = sum(r.get("pnl_pct", 0) or 0 for r in closed)
    avg_win    = sum(r.get("pnl_pct", 0) or 0 for r in wins) / len(wins) if wins else 0
    avg_loss   = sum(r.get("pnl_pct", 0) or 0 for r in losses) / len(losses) if losses else 0
    
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    
    msg = "📊 *تقرير الأداء*\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📌 *إجمالي التوصيات:* `{len(all_recs)}`\n"
    msg += f"✅ مغلقة: `{len(closed)}` | 🔄 مفتوحة: `{len(open_)}`\n\n"
    
    if closed:
        msg += f"🏆 *دقة التوصيات:* `{win_rate:.1f}%`\n"
        msg += f"   ✅ Wins: `{len(wins)}` (متوسط `+{avg_win:.2f}%`)\n"
        msg += f"   ❌ Losses: `{len(losses)}` (متوسط `{avg_loss:.2f}%`)\n\n"
        msg += f"💰 *إجمالي PnL النظري:* `{total_pnl:+.2f}%`\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    msg += "*آخر 5 توصيات:*\n\n"
    for r in all_recs[:5]:
        status_icon = "🔄" if r["status"] == "OPEN" else (
            "✅" if r.get("outcome") in ("TP1_HIT", "TP2_HIT") else "❌")
        date = r["created_at"][:10] if r.get("created_at") else "—"
        msg += f"{status_icon} `{date}` {r['action']} {r['asset']}"
        if r.get("pnl_pct") is not None:
            msg += f" (`{r['pnl_pct']:+.2f}%`)"
        msg += "\n"
    
    msg += "\n⚠️ _تتبع تعليمي - PnL نظري فقط_"
    return msg


# ═══════════════════════════════════════════════════════════════════════
# 15) FORMATTERS
# ═══════════════════════════════════════════════════════════════════════
def format_prices(prices: Dict[str, Dict]) -> str:
    msg = "💹 *الأسعار اللحظية:*\n\n"
    groups = {
        "💰 المعادن": ["Gold (XAUUSD)", "Silver (XAGUSD)"],
        "💵 العملات": ["DXY (Dollar)", "EUR/USD", "GBP/USD",
                      "USD/JPY", "USD/CHF", "AUD/USD"],
        "📊 المخاطر": ["S&P 500", "VIX", "Oil (WTI)"],
        "📈 العوائد": ["13W Yield", "5Y Yield", "10Y Yield", "30Y Yield"],
    }
    for group_name, items in groups.items():
        msg += f"*{group_name}*\n"
        for name in items:
            if name not in prices:
                continue
            d = prices[name]
            icon = "🟢" if d["change_pct"] >= 0 else "🔴"
            sign = "+" if d["change_pct"] >= 0 else ""
            msg += f"{icon} {name}: `{d['price']:.4f}` `{sign}{d['change_pct']:.2f}%`\n"
        msg += "\n"
    return msg


def format_news_list(news: List[Dict], title: str = "الأخبار") -> str:
    if not news:
        return f"📭 *{title}*\n\nلا توجد أخبار"
    msg = f"📰 *{title}*\n"
    msg += f"🕐 {datetime.now().strftime('%H:%M %d/%m')}\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    for i, n in enumerate(news[:10], 1):
        delta = datetime.now(timezone.utc) - n["date"]
        hrs = int(delta.total_seconds() / 3600)
        ago = f"{hrs}س" if hrs < 24 else f"{hrs//24}ي"
        msg += f"*{i}.* {n['title'][:90]}\n"
        msg += f"   📡 _{n['source']}_ · ⏱ {ago}\n"
        if n.get("link"):
            msg += f"   [مقال كامل]({n['link']})\n"
        msg += "\n"
    return msg


def format_cot(cot: Dict) -> str:
    if not cot:
        return "🐋 *COT*\n\nغير متاح"
    msg = "🐋 *Smart Money — CFTC COT*\n"
    any_date = next(iter(cot.values())).get("date", "—")
    msg += f"📅 آخر تقرير: `{any_date}`\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    for asset, d in cot.items():
        icon = "🟢" if d["net"] > 0 else "🔴"
        chg_icon = "📈" if d["weekly_change"] > 0 else "📉"
        msg += f"{icon} *{asset}*\n"
        msg += f"   Long: `{d['long']:,}` | Short: `{d['short']:,}`\n"
        msg += f"   Net: `{d['net']:+,}` ({d['bias']})\n"
        msg += f"   {chg_icon} تغيّر أسبوعي: `{d['weekly_change']:+,}`\n\n"
    return msg


def format_options_sentiment(opts: Dict) -> str:
    if not opts:
        return ("💎 *Options Sentiment*\n\n"
                "غير متاح (Polygon API مطلوب)\n\n"
                "💡 جرّب أمر `فحص_polygon` لمعرفة السبب الدقيق")
    
    # عرض الخطأ المفصّل لو موجود
    if opts.get("_error"):
        err_type = opts.get("_error")
        err_msg = opts.get("_message", "غير معروف")
        msg = "💎 *Options Sentiment*\n━━━━━━━━━━━━━━━━━━━\n\n"
        msg += "❌ *المشكلة:*\n"
        msg += f"   {err_msg}\n\n"
        if err_type == "no_key":
            msg += "🔧 *الحل:*\n"
            msg += "   • تأكد من إضافة `POLYGON_API_KEY` في Railway Variables\n"
            msg += "   • Restart الـBot بعد الإضافة\n"
        elif err_type == "auth":
            msg += "🔧 *الحل:*\n"
            msg += "   • الـAPI Key غلط — راجع من polygon.io/dashboard\n"
            msg += "   • انسخه مرة تانية بدون مسافات\n"
        elif err_type == "plan":
            msg += "🔧 *الموقف:*\n"
            msg += "   • اشتراكك الحالي = *Currencies Starter* ($49/شهر)\n"
            msg += "   • يشمل: Forex + Crypto فقط\n"
            msg += "   • لا يشمل: Options (محتاج اشتراك منفصل)\n\n"
            msg += "💡 *للحصول على Options Sentiment:*\n"
            msg += "   • اشترك إضافياً في *Options Starter* ($29/شهر)\n"
            msg += "   • من polygon.io/dashboard\n\n"
            msg += "✅ *البوت شغّال 100% بدون Options*\n"
            msg += "Options Sentiment ميزة إضافية فقط — كل التحليلات الأخرى تعمل بكفاءة"
        elif err_type == "rate_limit":
            msg += "🔧 *الحل:*\n"
            msg += "   • انتظر دقيقة وحاول تاني\n"
            msg += "   • أو ارفع الخطة لتجاوز حد الـ5 طلبات/دقيقة\n"
        return msg
    
    msg = f"💎 *Options Sentiment — {opts['underlying']}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📊 *Volume:*\n"
    msg += f"   Calls: `{opts['calls_volume']:,}`\n"
    msg += f"   Puts:  `{opts['puts_volume']:,}`\n"
    msg += f"   Total: `{opts['total_volume']:,}`\n\n"
    msg += f"📈 *Open Interest:*\n"
    msg += f"   Calls: `{opts['calls_oi']:,}`\n"
    msg += f"   Puts:  `{opts['puts_oi']:,}`\n\n"
    msg += f"🎯 *P/C Ratios:*\n"
    msg += f"   Volume: `{opts['pc_volume_ratio']}`\n"
    msg += f"   OI: `{opts['pc_oi_ratio']}`\n\n"
    msg += f"💡 *الإشارة:* {opts['sentiment']}\n\n"
    msg += "_P/C < 0.7 = Bullish | > 1.3 = Bearish_"
    return msg


def format_technical(ta: Dict) -> str:
    if not ta:
        return "📈 *التحليل الفني*\n\nغير متاح"
    msg = f"📈 *التحليل الفني — {ta['ticker']}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"💰 السعر: `{ta['price']:.4f}`\n\n"
    msg += f"📊 *المؤشرات:*\n"
    msg += f"   RSI(14): `{ta['rsi']:.1f}` {ta['rsi_signal']}\n"
    msg += f"   MACD: {ta['macd_signal']}\n"
    msg += f"   EMAs: {ta['ema_trend']}\n"
    msg += f"   • EMA20: `{ta['ema_20']:.2f}`\n"
    msg += f"   • EMA50: `{ta['ema_50']:.2f}`\n"
    msg += f"   • EMA200: `{ta['ema_200']:.2f}`\n\n"
    msg += f"📉 *Bollinger Bands:*\n"
    msg += f"   Upper: `{ta['bb_upper']:.2f}`\n"
    msg += f"   Lower: `{ta['bb_lower']:.2f}`\n"
    msg += f"   {ta['bb_signal']}\n\n"
    msg += f"📐 *ATR(14):* `{ta['atr']:.2f}`\n"
    msg += f"🏗️ *Structure:* {ta['structure']}\n\n"
    if ta["order_blocks"]["bullish"]:
        msg += f"🟢 *Bullish OBs:*\n"
        for ob in ta["order_blocks"]["bullish"][-2:]:
            msg += f"   • `{ob['level']:.2f}`\n"
    if ta["order_blocks"]["bearish"]:
        msg += f"🔴 *Bearish OBs:*\n"
        for ob in ta["order_blocks"]["bearish"][-2:]:
            msg += f"   • `{ob['level']:.2f}`\n"
    return msg


def format_central_banks(fed: Dict, yc: Dict, cb: List = None) -> str:
    msg = "🏦 *عقلية البنوك المركزية*\n━━━━━━━━━━━━━━━━━━━\n\n"
    if fed.get("y3m"):
        msg += "*🇺🇸 الفيدرالي الأمريكي*\n"
        msg += f"   3M: `{fed['y3m']:.2f}%` | 5Y: `{fed.get('y5y','—')}` | 10Y: `{fed['y10y']:.2f}%`\n"
        msg += f"   📊 توقع السوق: {fed['signal']}\n"
        msg += f"   🎯 Bias: *{fed['bias']}*\n\n"
    if yc.get("signal"):
        msg += "*📈 منحنى العائد*\n"
        msg += f"   Spread 3M-10Y: `{yc.get('spread_3M_10Y', 0):+.2f}%`\n"
        msg += f"   {yc['signal']}\n\n"
    if cb:
        msg += "*🌍 معدلات البنوك العالمية*\n"
        for c in cb[:6]:
            country = c.get("Country", "—")
            rate = c.get("LatestValue", "—")
            msg += f"   {country}: `{rate}%`\n"
    return msg


def format_recommendation(rec: Dict) -> List[str]:
    """تنسيق التوصية في رسائل منفصلة."""
    out = []
    icons = {"Claude": "🧠", "Gemini": "💎", "OpenAI": "🤖"}
    
    out.append(f"📋 *البيانات المستخدمة لتوصية {rec['asset']}*\n"
               f"━━━━━━━━━━━━━━━━━━━\n"
               f"```\n{rec['data_block'][:3500]}\n```")
    
    for name, txt in rec["analyses"].items():
        if txt.startswith(("⚪", "⚠️")):
            continue
        ic = icons.get(name, "🔵")
        out.append(f"{ic} *توصية {name}*\n━━━━━━━━━━━━━━━━━━━\n\n{txt[:3700]}")
    
    if rec.get("final") and not rec["final"].startswith(("⚪", "⚠️")):
        out.append(f"⚖️ *الحكم النهائي للجنة*\n━━━━━━━━━━━━━━━━━━━\n\n"
                   f"{rec['final'][:3700]}\n\n"
                   f"⚠️ _تحليل تعليمي — ليس نصيحة استثمارية_")
    
    # ✨ Smart Risk Management — رسالة منفصلة
    if rec.get("smart_risk_text"):
        # نقسّم لو طويلة جداً
        srt = rec["smart_risk_text"]
        if len(srt) > 3800:
            # نقسّم عند نصف منطقي
            mid = srt.find("📋 *PARTIAL CLOSE")
            if mid > 0:
                out.append(srt[:mid])
                out.append(srt[mid:])
            else:
                out.append(srt[:3800])
                out.append(srt[3800:])
        else:
            out.append(srt)
    
    return out


# ═══════════════════════════════════════════════════════════════════════
# 16) DAILY MORNING BRIEFING
# ═══════════════════════════════════════════════════════════════════════
def build_morning_briefing() -> List[str]:
    msgs = []
    now = datetime.now(pytz.timezone(DEFAULT_TZ)).strftime("%A %d/%m/%Y - %H:%M")
    
    msgs.append(
        f"🌅 *تقرير الصباح — Wall Street Pro*\n"
        f"📅 {now}\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    
    prices = fetch_prices()
    if prices:
        msgs.append(format_prices(prices))
    
    news = fetch_news(max_per_source=3, hours_back=18)[:6]
    if news:
        n_msg = "📰 *أهم العناوين (آخر 18 ساعة):*\n\n"
        for i, n in enumerate(news, 1):
            n_msg += f"{i}. {n['title'][:90]}\n   📡 _{n['source']}_\n\n"
        msgs.append(n_msg)
    
    cal = fetch_te_calendar(days_ahead=2)[:5]
    if cal:
        c_msg = "📅 *أحداث اليوم/غداً:*\n\n"
        for e in cal:
            c_msg += f"• `{e.get('Country','—')}` {e.get('Event','—')[:60]}\n"
            c_msg += f"  ⏰ {str(e.get('Date','—'))[:16]}\n\n"
        msgs.append(c_msg)
    
    fed = derive_fed_expectations(prices)
    yc  = analyze_yield_curve(prices)
    msgs.append(format_central_banks(fed, yc))
    
    msgs.append("⏳ *جاري إعداد توصية الذهب...*")
    rec = build_recommendation(asset="Gold")
    if rec.get("final") and not rec["final"].startswith(("⚪", "⚠️")):
        msgs.append(f"🎯 *توصية الصباح — الذهب*\n━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{rec['final'][:3500]}\n\n"
                    f"⚠️ _تعليمي فقط_")
    
    return msgs


# ═══════════════════════════════════════════════════════════════════════
# 17) HIGH-IMPACT NEWS MONITOR
# ═══════════════════════════════════════════════════════════════════════
async def monitor_high_impact_news(context: ContextTypes.DEFAULT_TYPE):
    """يفحص الأخبار كل 30 دقيقة."""
    try:
        news = fetch_news(max_per_source=4, hours_back=2)
        new_hi = []
        
        seen_ids = {r["news_id"] for r in
                    db_exec("SELECT news_id FROM seen_news", fetch="all") or []}
        
        for n in news:
            if n["id"] in seen_ids:
                continue
            is_hi, kws = is_high_impact(n)
            db_exec(
                "INSERT OR IGNORE INTO seen_news (news_id, seen_at) VALUES (?, ?)",
                (n["id"], datetime.now(timezone.utc).isoformat()),
            )
            if is_hi:
                n["matched_keywords"] = kws
                new_hi.append(n)
        
        # تنظيف الأخبار القديمة (أكثر من 7 أيام)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        db_exec("DELETE FROM seen_news WHERE seen_at < ?", (cutoff,))
        
        if not new_hi:
            return
        
        for n in new_hi[:3]:
            prompt = f"""خبر عاجل:
العنوان: {n['title']}
المصدر: {n['source']}
الملخص: {n['summary']}
الكلمات: {', '.join(n['matched_keywords'])}

تحليل سريع (200 كلمة):
1. ما المتأثر مباشرة؟
2. الاتجاه الفوري المتوقع
3. تحرّك سريع: BUY/SELL/WAIT
4. مستويات حاسمة"""
            
            analysis = ask_claude(prompt, max_tokens=600)
            
            alert = (f"🚨 *تنبيه عاجل*\n━━━━━━━━━━━━━━━━━━━\n\n"
                     f"📰 *{n['title'][:120]}*\n"
                     f"📡 _{n['source']}_\n"
                     f"🏷️ `{', '.join(n['matched_keywords'][:3])}`\n\n"
                     f"━━━━━━━━━━━━━━━━━━━\n"
                     f"🧠 *تحليل سريع:*\n\n{analysis[:2500]}\n\n"
                     f"⚠️ _تعليمي_")
            
            subs = db_exec(
                "SELECT chat_id FROM subscribers WHERE alerts=1",
                fetch="all") or []
            
            for s in subs:
                try:
                    await context.bot.send_message(
                        chat_id=int(s["chat_id"]),
                        text=alert,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                    await asyncio.sleep(0.3)
                except Exception as e:
                    log.warning(f"alert {s['chat_id']}: {e}")
    except Exception as e:
        log.warning(f"monitor: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 17.5) TRADE MONITOR — يفحص الصفقات النشطة كل 5 دقائق
# ═══════════════════════════════════════════════════════════════════════
# Mapping: asset → (yfinance_ticker, polygon_asset_key)
ASSET_TICKERS = {
    "Gold":    ("GC=F",      "XAU/USD"),
    "Silver":  ("SI=F",      "XAG/USD"),
    "EUR/USD": ("EURUSD=X",  "EUR/USD"),
    "GBP/USD": ("GBPUSD=X",  "GBP/USD"),
    "USD/JPY": ("JPY=X",     "USD/JPY"),
    "USD/CHF": ("CHF=X",     "USD/CHF"),
    "AUD/USD": ("AUDUSD=X",  "AUD/USD"),
    "Oil":     ("CL=F",      "WTI"),
    "USD/DXY": ("DX-Y.NYB",  None),
}


def trade_get_current_price(asset: str) -> Optional[float]:
    """يجلب السعر الحالي للأصل (Polygon أولاً، yfinance fallback)."""
    ticker_info = ASSET_TICKERS.get(asset)
    if not ticker_info:
        return None
    
    yf_ticker, poly_key = ticker_info
    
    # Polygon أولاً
    if poly_key:
        try:
            data = polygon_get_asset_price(poly_key)
            if data and data.get("price"):
                return float(data["price"])
        except Exception:
            pass
    
    # yfinance fallback
    try:
        t = yf.Ticker(yf_ticker)
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    
    return None


async def trade_send_alert(
    bot, chat_id: str, trade: Dict, alert_type: str,
    title: str, message: str
):
    """يرسل تنبيه للمستخدم ويسجّله."""
    try:
        full_msg = (
            f"🔔 *تنبيه صفقة #{trade['id']}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{title}\n\n"
            f"{message}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *{trade['asset']}* | {trade['action']}\n"
            f"💰 Entry: `{trade['entry_price']:.4f}`"
        )
        await bot.send_message(chat_id=int(chat_id), text=full_msg, parse_mode="Markdown")
        track_mark_alert_sent(trade["id"], alert_type)
        track_update_trade(
            trade["id"],
            last_alert_at=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        log.warning(f"trade alert {chat_id}: {e}")


async def trade_check_single(trade: Dict, send_alert: bool = True, bot=None) -> Dict:
    """يفحص صفقة واحدة ويرجّع الحالة (يرسل تنبيهات لو send_alert=True).
    
    Returns: {
        "current_price": float,
        "alerts": [list of alert strings],
        "should_close": bool,
    }
    """
    asset = trade["asset"]
    entry = trade["entry_price"]
    is_buy = trade["action"] in ("BUY", "ADD")
    sl = trade.get("sl")
    tp1 = trade.get("tp1")
    tp2 = trade.get("tp2")
    tp3 = trade.get("tp3")
    
    current_price = trade_get_current_price(asset)
    if not current_price:
        return {"current_price": None, "alerts": [], "should_close": False}
    
    # تحديث آخر فحص
    track_update_trade(
        trade["id"],
        last_check_at=datetime.now(timezone.utc).isoformat()
    )
    
    alerts = []
    should_close = False
    
    # ─── 1. فحص SL ───
    if sl is not None:
        sl_hit = (is_buy and current_price <= sl) or (not is_buy and current_price >= sl)
        if sl_hit and not track_alert_was_sent(trade["id"], "SL_HIT"):
            pnl_d, pnl_p = track_calculate_pnl(trade, current_price)
            alerts.append({
                "type": "SL_HIT",
                "title": "🛑 *SL HIT — تم ضرب وقف الخسارة*",
                "msg": (
                    f"السعر الحالي: `{current_price:.4f}`\n"
                    f"SL: `{sl:.4f}`\n"
                    f"📉 الخسارة: `{pnl_p:+.2f}%` (`${pnl_d:+.2f}`)\n\n"
                    f"⚠️ *الصفقة مغلقة تلقائياً*\n"
                    f"تذكر: SL = حماية، ضربه جزء من الإستراتيجية ✓"
                ),
            })
            should_close = True
            if send_alert and bot:
                track_close_trade(trade["id"], current_price, "SL", pnl_d, pnl_p)
    
    # ─── 2. فحص TP3 (الأهم - إغلاق كامل) ───
    if not should_close and tp3 and not trade.get("tp3_hit"):
        tp3_hit = (is_buy and current_price >= tp3) or (not is_buy and current_price <= tp3)
        if tp3_hit and not track_alert_was_sent(trade["id"], "TP3_HIT"):
            pnl_d, pnl_p = track_calculate_pnl(trade, current_price)
            alerts.append({
                "type": "TP3_HIT",
                "title": "🎯🎯🎯 *TP3 HIT — الهدف الأقصى!*",
                "msg": (
                    f"السعر الحالي: `{current_price:.4f}`\n"
                    f"TP3: `{tp3:.4f}`\n"
                    f"💰 الربح: `{pnl_p:+.2f}%` (`${pnl_d:+.2f}`)\n\n"
                    f"✅ *مبروك! الصفقة وصلت أعلى هدف*\n"
                    f"اقفل المتبقي (20%) — الصفقة مكتملة 🏆"
                ),
            })
            track_update_trade(trade["id"], tp3_hit=1)
            should_close = True
            if send_alert and bot:
                track_close_trade(trade["id"], current_price, "TP3", pnl_d, pnl_p)
    
    # ─── 3. فحص TP2 ───
    if not should_close and tp2 and not trade.get("tp2_hit"):
        tp2_hit = (is_buy and current_price >= tp2) or (not is_buy and current_price <= tp2)
        if tp2_hit and not track_alert_was_sent(trade["id"], "TP2_HIT"):
            pnl_d, pnl_p = track_calculate_pnl(trade, current_price)
            alerts.append({
                "type": "TP2_HIT",
                "title": "🎯🎯 *TP2 HIT — الهدف الثاني!*",
                "msg": (
                    f"السعر الحالي: `{current_price:.4f}`\n"
                    f"TP2: `{tp2:.4f}`\n"
                    f"💰 الربح: `{pnl_p:+.2f}%` (`${pnl_d:+.2f}`)\n\n"
                    f"✅ *إجراءات مقترحة:*\n"
                    f"• اقفل 30% إضافية (مجموع 80%)\n"
                    f"• حرّك SL إلى TP1 (`{tp1:.4f}`) — لقفل الربح\n"
                    f"• اترك 20% للـTP3"
                ),
            })
            track_update_trade(trade["id"], tp2_hit=1, partial_closed_pct=80)
    
    # ─── 4. فحص TP1 ───
    if not should_close and tp1 and not trade.get("tp1_hit"):
        tp1_hit = (is_buy and current_price >= tp1) or (not is_buy and current_price <= tp1)
        if tp1_hit and not track_alert_was_sent(trade["id"], "TP1_HIT"):
            pnl_d, pnl_p = track_calculate_pnl(trade, current_price)
            alerts.append({
                "type": "TP1_HIT",
                "title": "🎯 *TP1 HIT — الهدف الأول!*",
                "msg": (
                    f"السعر الحالي: `{current_price:.4f}`\n"
                    f"TP1: `{tp1:.4f}`\n"
                    f"💰 الربح: `{pnl_p:+.2f}%` (`${pnl_d:+.2f}`)\n\n"
                    f"✅ *إجراءات مقترحة:*\n"
                    f"• اقفل 50% من الصفقة (Partial Close)\n"
                    f"• حرّك SL إلى Breakeven (`{entry:.4f}`)\n"
                    f"• الباقي (50%) للـTP2 و TP3"
                ),
            })
            track_update_trade(trade["id"], tp1_hit=1, partial_closed_pct=50,
                              sl_moved_to_be=1)
    
    # ─── 5. تنبيه قرب TP1 (1% بعيد) ───
    if not should_close and tp1 and not trade.get("tp1_hit"):
        distance_to_tp1 = abs(current_price - tp1) / current_price * 100
        if distance_to_tp1 < 1.0:
            in_direction = (is_buy and current_price < tp1) or (not is_buy and current_price > tp1)
            if in_direction and not track_alert_was_sent(trade["id"], "NEAR_TP1"):
                alerts.append({
                    "type": "NEAR_TP1",
                    "title": "⚠️ *قريب من TP1 — استعد!*",
                    "msg": (
                        f"السعر الحالي: `{current_price:.4f}`\n"
                        f"TP1: `{tp1:.4f}`\n"
                        f"📏 المسافة: `{distance_to_tp1:.2f}%`\n\n"
                        f"💡 جهّز أمر إغلاق جزئي 50%"
                    ),
                })
    
    # ─── 6. تنبيه قرب SL (1% بعيد) ───
    if not should_close and sl is not None:
        distance_to_sl = abs(current_price - sl) / current_price * 100
        if distance_to_sl < 1.0:
            in_danger = (is_buy and current_price > sl) or (not is_buy and current_price < sl)
            if in_danger and not track_alert_was_sent(trade["id"], "NEAR_SL"):
                pnl_d, pnl_p = track_calculate_pnl(trade, current_price)
                alerts.append({
                    "type": "NEAR_SL",
                    "title": "⚠️ *قريب من SL — حذر!*",
                    "msg": (
                        f"السعر الحالي: `{current_price:.4f}`\n"
                        f"SL: `{sl:.4f}`\n"
                        f"📏 المسافة: `{distance_to_sl:.2f}%`\n"
                        f"📉 PnL الحالي: `{pnl_p:+.2f}%`\n\n"
                        f"💡 *خياراتك:*\n"
                        f"• انتظر تأكيد الكسر\n"
                        f"• اقفل يدوياً لتقليل الخسارة\n"
                        f"• راقب البيانات الفنية"
                    ),
                })
    
    # ─── إرسال التنبيهات ───
    if send_alert and bot:
        for alert in alerts:
            await trade_send_alert(
                bot, trade["chat_id"], trade,
                alert["type"], alert["title"], alert["msg"]
            )
            await asyncio.sleep(0.3)
    
    return {
        "current_price": current_price,
        "alerts": alerts,
        "should_close": should_close,
    }


async def trade_monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    """Monitor الرئيسي للصفقات — يشتغل كل 5 دقائق."""
    try:
        active_trades = track_get_active_trades()
        if not active_trades:
            return
        
        log.info(f"📊 Trade Monitor: فحص {len(active_trades)} صفقة نشطة")
        
        for trade in active_trades:
            try:
                await trade_check_single(trade, send_alert=True, bot=context.bot)
                await asyncio.sleep(0.5)  # تجنب rate limits
            except Exception as e:
                log.warning(f"trade {trade['id']} check: {e}")
        
        # ─── فحص Smart Money / Liquidity changes (مرة كل ساعة) ───
        # نتحقق هل عدّى ساعة من آخر فحص متقدم
        last_advanced = cache_get("last_advanced_trade_check")
        if not last_advanced:
            await trade_advanced_check(context.bot, active_trades)
            cache_set("last_advanced_trade_check", "1", ttl_seconds=3600)
            
    except Exception as e:
        log.warning(f"trade monitor: {e}")


async def trade_advanced_check(bot, active_trades: List[Dict]):
    """فحص متقدم: تغير Smart Money + ADD opportunities (كل ساعة)."""
    for trade in active_trades:
        try:
            asset = trade["asset"]
            ticker_info = ASSET_TICKERS.get(asset)
            if not ticker_info:
                continue
            yf_ticker, poly_key = ticker_info
            
            # نجلب DataFrame
            if poly_key:
                df, _ = get_asset_dataframe_scaled(poly_key, yf_ticker, "3mo", "1d")
            else:
                t = yf.Ticker(yf_ticker)
                df = t.history(period="3mo", interval="1d")
            
            if df is None or df.empty:
                continue
            
            # نستخدم Smart Money detection من smart_risk
            sm_zones = smart_risk.find_smart_money_zones(df, asset)
            liq_pools = smart_risk.find_liquidity_pools(df, asset)
            
            entry = trade["entry_price"]
            is_buy = trade["action"] in ("BUY", "ADD")
            
            # ─── ADD Opportunity: السعر رجع لـbullish OB قوي ───
            current_price = float(df["Close"].iloc[-1])
            
            if is_buy:
                # نشوف هل في bullish OB قريب من السعر الحالي
                for ob in sm_zones.get("bullish_obs", [])[:3]:
                    ob_low = ob.get("low", 0)
                    ob_high = ob.get("high", 0)
                    in_ob = ob_low <= current_price <= ob_high
                    if in_ob and ob["bars_ago"] < 10:  # OB حديث
                        if not track_alert_was_sent(trade["id"], f"ADD_OB_{ob_low:.2f}"):
                            await trade_send_alert(
                                bot, trade["chat_id"], trade,
                                f"ADD_OB_{ob_low:.2f}",
                                "🐋 *فرصة ADD — Bullish Order Block*",
                                (
                                    f"السعر دخل في Bullish Order Block!\n\n"
                                    f"💰 السعر: `{current_price:.4f}`\n"
                                    f"🐋 OB Range: `{ob_low:.4f}` - `{ob_high:.4f}`\n"
                                    f"📅 منذ: {ob['bars_ago']} bars\n"
                                    f"💪 القوة: {ob['strength']}\n\n"
                                    f"💡 *قد تكون فرصة ADD*\n"
                                    f"• راقب الـreaction\n"
                                    f"• حجم إضافي 30-50% من الأصلي\n"
                                    f"• SL: تحت الـOB low"
                                )
                            )
                            break
            else:
                # SELL → نشوف bearish OBs
                for ob in sm_zones.get("bearish_obs", [])[:3]:
                    ob_low = ob.get("low", 0)
                    ob_high = ob.get("high", 0)
                    in_ob = ob_low <= current_price <= ob_high
                    if in_ob and ob["bars_ago"] < 10:
                        if not track_alert_was_sent(trade["id"], f"ADD_OB_{ob_high:.2f}"):
                            await trade_send_alert(
                                bot, trade["chat_id"], trade,
                                f"ADD_OB_{ob_high:.2f}",
                                "🐋 *فرصة ADD — Bearish Order Block*",
                                (
                                    f"السعر دخل في Bearish Order Block!\n\n"
                                    f"💰 السعر: `{current_price:.4f}`\n"
                                    f"🐋 OB Range: `{ob_low:.4f}` - `{ob_high:.4f}`\n"
                                    f"📅 منذ: {ob['bars_ago']} bars\n\n"
                                    f"💡 فرصة ADD للـSHORT"
                                )
                            )
                            break
            
            # ─── تنبيه: Liquidity Sweep حصل في الاتجاه ───
            # نشوف هل في pool في اتجاه TP اتمسح حديثاً
            if is_buy:
                for pool in liq_pools.get("buy_side", [])[:3]:
                    if pool.get("is_swept") and pool["price"] < trade.get("tp1", float('inf')):
                        if not track_alert_was_sent(trade["id"], f"SWEEP_{pool['price']:.2f}"):
                            await trade_send_alert(
                                bot, trade["chat_id"], trade,
                                f"SWEEP_{pool['price']:.2f}",
                                "💧 *Liquidity Sweep — في صالحك*",
                                (
                                    f"الحيتان مسحت liquidity pool في اتجاه صفقتك!\n\n"
                                    f"📍 المستوى: `{pool['price']:.4f}`\n"
                                    f"📊 النوع: {pool['type']}\n\n"
                                    f"💡 الاحتمالية ارتفعت لوصول TP"
                                )
                            )
                            break
            
        except Exception as e:
            log.warning(f"advanced check {trade.get('id')}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 17.6) NEWS TRACKING MONITOR — أخبار عاجلة + تحليل AI فوري
# ═══════════════════════════════════════════════════════════════════════
def quick_ai_news_analysis(news_item: Dict, related_assets: List[str]) -> str:
    """تحليل AI سريع لخبر عاجل (10-15 ثانية).
    
    يستخدم Claude فقط (الأسرع) لإعطاء رأي فوري.
    """
    title = news_item.get("title", "")
    source = news_item.get("source", "")
    summary = news_item.get("summary", "")[:500]
    
    assets_text = ", ".join(related_assets) if related_assets else "Gold/Forex"
    
    prompt = f"""خبر عاجل من {source}:

"{title}"

{summary if summary else ''}

الأصول المتأثرة: {assets_text}

مهمتك: تحليل سريع (تحت 200 كلمة) كمحلل صناديق تحوّط:

1️⃣ **التأثير المتوقع** (Bullish/Bearish/Neutral) على كل أصل
2️⃣ **القوة** (قوي/متوسط/ضعيف)
3️⃣ **التوقيت** (فوري / تدريجي / مؤجل)
4️⃣ **توصية فورية:**
   • BUY/SELL/HOLD/تجنّب الدخول
   • مستويات حرجة للمراقبة
   • أسباب موجزة (3 أسباب فقط)

⚡ كن مباشر ومحدد - ليس تنظير عام."""
    
    try:
        return ask_claude(prompt, max_tokens=600)
    except Exception as e:
        log.warning(f"AI news analysis: {e}")
        return ""


def get_affected_assets(news_item: Dict) -> List[str]:
    """يحدد الأصول المتأثرة بالخبر بناء على keywords."""
    text = (news_item.get("title", "") + " " + news_item.get("summary", "")).lower()
    
    affected = []
    
    # Gold keywords
    if any(k in text for k in ["gold", "xauusd", "ذهب", "precious metals", "bullion"]):
        affected.append("Gold")
    # Silver
    if any(k in text for k in ["silver", "xagusd", "فضة"]):
        affected.append("Silver")
    # USD
    if any(k in text for k in ["dollar", "usd", "fed", "fomc", "powell", "treasury", "yields"]):
        affected.extend(["EUR/USD", "GBP/USD", "USD/JPY"])
    # Euro
    if any(k in text for k in ["euro", "eur", "ecb", "lagarde", "europe"]):
        affected.append("EUR/USD")
    # GBP
    if any(k in text for k in ["pound", "gbp", "sterling", "boe", "bailey", "uk", "britain"]):
        affected.append("GBP/USD")
    # JPY
    if any(k in text for k in ["yen", "jpy", "boj", "ueda", "japan"]):
        affected.append("USD/JPY")
    # Oil
    if any(k in text for k in ["oil", "crude", "wti", "brent", "opec", "بترول", "نفط"]):
        affected.append("Oil")
    # General macro affecting all
    if any(k in text for k in ["cpi", "ppi", "nfp", "gdp", "unemployment", "inflation"]):
        if not affected:
            affected = ["Gold", "EUR/USD", "USD/JPY"]
    
    return list(set(affected))[:4]  # Deduplicate, limit to 4


async def news_tracking_monitor(context: ContextTypes.DEFAULT_TYPE):
    """Monitor للأخبار العاجلة — يشتغل كل 5 دقائق."""
    try:
        subscribers = news_tracking_get_subscribers()
        if not subscribers:
            return
        
        # جلب أخبار آخر 15 دقيقة فقط (الأكثر طزاجة)
        news = fetch_news(max_per_source=5, hours_back=1)
        if not news:
            return
        
        # فلترة عالية التأثير فقط
        urgent = []
        for n in news:
            is_high, _ = is_high_impact(n)
            if not is_high:
                continue
            # عمر الخبر
            try:
                pub_str = n.get("published_at") or n.get("pubDate", "")
                if pub_str:
                    pub_dt = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=pytz.UTC)
                    age_minutes = (datetime.now(pytz.UTC) - pub_dt).total_seconds() / 60
                    if age_minutes > 60:  # أقدم من ساعة
                        continue
            except Exception:
                pass
            urgent.append(n)
        
        if not urgent:
            return
        
        log.info(f"📰 News Monitor: {len(urgent)} خبر عاجل، {len(subscribers)} مشترك")
        
        # نتعامل مع كل مشترك
        for sub in subscribers:
            chat_id = sub["chat_id"]
            user_assets = sub.get("assets", "ALL")
            wants_ai = bool(sub.get("ai_analysis", 1))
            
            for news_item in urgent:
                # ID فريد للخبر (لتجنب التكرار)
                news_id = news_item.get("link") or news_item.get("title", "")[:100]
                
                if news_alert_was_sent(chat_id, news_id):
                    continue
                
                # فلترة بالأصول
                affected = get_affected_assets(news_item)
                if not affected:
                    continue
                
                if user_assets != "ALL":
                    user_asset_list = [a.strip() for a in user_assets.split(",")]
                    if not any(a in user_asset_list for a in affected):
                        continue
                
                # ─── تحضير الرسالة ───
                title = news_item.get("title", "")[:200]
                source = news_item.get("source", "?")
                link = news_item.get("link", "")
                
                msg = f"🚨 *خبر عاجل — {source}*\n"
                msg += "━━━━━━━━━━━━━━━━━━━\n\n"
                msg += f"📰 *{title}*\n\n"
                msg += f"🎯 الأصول المتأثرة: {', '.join(affected)}\n\n"
                
                # ─── تحليل AI سريع ───
                if wants_ai:
                    msg += "━━━━━━━━━━━━━━━━━━━\n"
                    msg += "🧠 *تحليل AI سريع:*\n\n"
                    try:
                        analysis = quick_ai_news_analysis(news_item, affected)
                        if analysis:
                            # نقصّ التحليل لو طويل جداً
                            if len(analysis) > 1500:
                                analysis = analysis[:1500] + "..."
                            msg += analysis
                        else:
                            msg += "_التحليل غير متاح حالياً_"
                    except Exception as e:
                        log.warning(f"AI analysis: {e}")
                        msg += "_التحليل تأخر — راجع الخبر يدوياً_"
                
                msg += "\n\n━━━━━━━━━━━━━━━━━━━\n"
                if link:
                    msg += f"🔗 [اقرأ الخبر الكامل]({link})\n\n"
                msg += "_⚠️ تحليل تعليمي — ليس نصيحة استثمارية_"
                
                # ─── إرسال ───
                try:
                    # نقسّم الرسالة لو طويلة
                    if len(msg) > 4000:
                        await context.bot.send_message(
                            chat_id=int(chat_id),
                            text=msg[:4000] + "...",
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=int(chat_id),
                            text=msg,
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                    news_alert_mark_sent(chat_id, news_id)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    log.warning(f"news alert send {chat_id}: {e}")
                    # في حالة فشل markdown، نرسل بلا تنسيق
                    try:
                        plain = msg.replace("*", "").replace("`", "").replace("_", "")
                        await context.bot.send_message(
                            chat_id=int(chat_id),
                            text=plain[:4000],
                            disable_web_page_preview=True,
                        )
                        news_alert_mark_sent(chat_id, news_id)
                    except Exception:
                        pass
            
            # تأخير صغير بين المشتركين
            await asyncio.sleep(0.3)
            
    except Exception as e:
        log.warning(f"news tracking monitor: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 18) DAILY BRIEFING SCHEDULER
# ═══════════════════════════════════════════════════════════════════════
async def daily_briefing_callback(context: ContextTypes.DEFAULT_TYPE):
    """يفحص كل دقيقة المشتركين."""
    now_utc = datetime.now(timezone.utc)
    subs = db_exec("SELECT * FROM subscribers", fetch="all") or []
    
    for sub in subs:
        try:
            tz = pytz.timezone(sub.get("tz", DEFAULT_TZ))
            local = now_utc.astimezone(tz)
            if (local.hour == sub.get("hour", DEFAULT_BRIEF_HR) and
                local.minute == sub.get("minute", DEFAULT_BRIEF_MIN)):
                
                key = f"{local.date()}-{sub['chat_id']}"
                if sub.get("last_sent") == key:
                    continue
                
                db_exec(
                    "UPDATE subscribers SET last_sent=? WHERE chat_id=?",
                    (key, sub["chat_id"]),
                )
                
                msgs = build_morning_briefing()
                for m in msgs:
                    try:
                        await context.bot.send_message(
                            chat_id=int(sub["chat_id"]),
                            text=m[:4000],
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        log.warning(f"brief send: {e}")
        except Exception as e:
            log.warning(f"sched: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 19) TELEGRAM HANDLERS
# ═══════════════════════════════════════════════════════════════════════
async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🌟 *WALL STREET PRO BOT V4.1*\n"
        "_3 AI Brains + Smart Money + Smart Risk_\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🎯 *التوصيات الذكية:*\n"
        "`توصية` — توصية الذهب + Smart Risk\n"
        "`توصية دولار` — توصية الدولار/DXY\n"
        "`أداء` — تقرير دقة التوصيات\n\n"
        "🛡️ *إدارة المخاطر الذكية:*\n"
        "`مخاطر ذهب buy 4600 4000` — تحليل مخاطر يدوي\n"
        "`مخاطر فضة sell 30 4000` — كل الأصول مدعومة\n"
        "`مخاطر eurusd buy 1.085 4000`\n"
        "  ▸ Liquidity Pools (BSL/SSL) + Smart Money\n"
        "  ▸ 3 مستويات SL خلف الـpools\n"
        "  ▸ 3 أهداف TP عند الـpools\n"
        "  ▸ Position Sizing + Partial Close\n\n"
        "⚡ *Scalping Analysis:*\n"
        "`سكالب ذهب` — تحليل 7 مؤشرات على 1m/5m\n"
        "`سكالب eurusd` / `سكالب gbpusd`\n"
        "`سكالب فضة` / `سكالب بترول`\n"
        "  ▸ RSI(7) + EMA Cross + Bollinger\n"
        "  ▸ Volume + Stochastic + ATR + Candle\n"
        "  ▸ قرار LONG/SHORT/WAIT + SL/TP ضيق\n\n"
        "📊 *Live Trade Tracking* ✨ جديد:\n"
        "`تتبع` — عرض آخر توصية\n"
        "`تتبع ذهب 0.05` — تفعيل تتبع نشط\n"
        "`صفقاتي` — كل صفقاتك المتابَعة\n"
        "`حالة_صفقة [ID]` — تحديث فوري\n"
        "`الغاء_تتبع [ID]` — إيقاف التتبع\n"
        "`اقفل_صفقة [ID] [سعر]` — إغلاق يدوي\n"
        "  ▸ تنبيه عند TP1/TP2/TP3/SL\n"
        "  ▸ نصيحة تحريك SL لـBreakeven\n"
        "  ▸ فرص ADD عند Order Blocks\n"
        "  ▸ تنبيه Liquidity Sweeps\n\n"
        "📰 *Live News Tracking* ✨ جديد:\n"
        "`تتبع_اخبار` — كل الأصول\n"
        "`تتبع_اخبار ذهب فوركس` — مخصّص\n"
        "`حالة_اخبار` — عرض الإعدادات\n"
        "`وقف_اخبار` — إيقاف\n"
        "  ▸ خبر عاجل + تحليل AI فوري\n"
        "  ▸ تأثير على الأصول + توصية\n"
        "  ▸ مستويات حرجة للمراقبة\n\n"
        "📊 *التحليل العميق:*\n"
        "`تحليل` — تحليل سوق شامل\n"
        "`فني` — التحليل الفني (RSI/MACD/EMA/BB/ICT)\n"
        "`سؤال [نص]` — اسأل الـ3 AIs\n\n"
        "🐋 *Smart Money:*\n"
        "`حيتان` — COT + TFF\n"
        "`خيارات` — Options Sentiment (P/C)\n"
        "`بنوك` — البنوك المركزية + Yield Curve\n"
        "`ماكرو` — FRED data + Fed/CPI/GDP\n\n"
        "💱 *Forex Live:*\n"
        "`فوركس_مباشر` — أسعار 6 أزواج Real-time (Polygon)\n"
        "`فحص_polygon` — تشخيص Polygon API\n\n"
        "📰 *الأخبار:*\n"
        "`أخبار` / `أخبار ذهب` / `أخبار فوركس`\n"
        "`عاجل` — High-Impact فقط\n\n"
        "💹 *البيانات:*\n"
        "`أسعار` / `تقويم`\n\n"
        "📅 *الاشتراك:*\n"
        "`اشترك` — تقرير 7 ص (الرياض)\n"
        "`اشترك 8 30` — مخصص\n"
        "`الغاء` — إلغاء\n"
        "`يومي` — تشغيل التقرير الآن\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ _تحليلات تعليمية فقط_"
    )
    await u.message.reply_text(msg, parse_mode="Markdown")


async def send_long(u: Update, text: str):
    MAX = 4000
    chunks = [text[i:i+MAX] for i in range(0, len(text), MAX)] if len(text) > MAX else [text]
    for ch in chunks:
        await u.message.reply_text(
            ch, parse_mode="Markdown", disable_web_page_preview=True)


async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    text = u.message.text.strip()
    chat_id = str(u.effective_chat.id)
    
    # حفظ في memory
    db_exec(
        "INSERT INTO conversation_memory (chat_id, role, content, created_at) "
        "VALUES (?, 'user', ?, ?)",
        (chat_id, text, datetime.now(timezone.utc).isoformat()),
    )
    
    # ═══ الاشتراك ═══
    if text.startswith(("اشترك", "subscribe")):
        parts = text.split()
        hour = DEFAULT_BRIEF_HR
        minute = DEFAULT_BRIEF_MIN
        if len(parts) >= 2:
            try: hour = int(parts[1])
            except: pass
        if len(parts) >= 3:
            try: minute = int(parts[2])
            except: pass
        
        db_exec(
            "INSERT OR REPLACE INTO subscribers "
            "(chat_id, hour, minute, tz, alerts, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (chat_id, hour, minute, DEFAULT_TZ,
             datetime.now(timezone.utc).isoformat()),
        )
        await u.message.reply_text(
            f"✅ *تم الاشتراك*\n\n"
            f"📅 التقرير الصباحي: `{hour:02d}:{minute:02d}` ({DEFAULT_TZ})\n"
            f"🚨 تنبيهات الأخبار: مفعّلة\n\n"
            f"للإلغاء: `الغاء`",
            parse_mode="Markdown")
        return
    
    if text in ("الغاء", "unsubscribe", "إلغاء"):
        db_exec("DELETE FROM subscribers WHERE chat_id=?", (chat_id,))
        await u.message.reply_text("❌ تم إلغاء الاشتراك")
        return
    
    # ═══ التقرير الصباحي يدوياً ═══
    if text in ("يومي", "صباحي", "تقرير", "morning"):
        await u.message.reply_text(
            "⏳ *جاري إعداد التقرير الصباحي...*\n_(60-90 ثانية)_",
            parse_mode="Markdown")
        msgs = build_morning_briefing()
        for m in msgs:
            await send_long(u, m)
            await asyncio.sleep(0.4)
        return
    
    # ═══════════════════════════════════════════════════════════════════
    # 📊 LIVE TRADE TRACKING — تتبع الصفقات النشطة
    # ═══════════════════════════════════════════════════════════════════
    
    # ─── أمر "تتبع آخر توصية" ───
    # الصيغة: تتبع [الأصل] [position_size اختياري]
    # مثال: تتبع ذهب 0.05    → يتتبع آخر توصية ذهب بحجم 0.05 لوت
    # مثال: تتبع              → يعرض آخر توصية ويسأل
    if text.startswith(("تتبع", "track", "متابعة")) and not text.startswith(("تتبع_اخبار", "تتبع اخبار", "تتبع أخبار", "track_news", "تتبع_أخبار")):
        parts = text.split()
        
        # ─── حالة 1: "تتبع" بدون أصل = عرض آخر توصية ───
        if len(parts) == 1:
            last_rec = db_exec(
                "SELECT * FROM recommendations WHERE chat_id=? AND status='OPEN' "
                "AND action IN ('BUY', 'SELL', 'ADD') ORDER BY created_at DESC LIMIT 1",
                (chat_id,), fetch="one"
            )
            if not last_rec:
                await u.message.reply_text(
                    "⚠️ *لا توجد توصية نشطة لتتبعها*\n\n"
                    "أرسل `ذهب` أو `توصية دولار` للحصول على توصية جديدة، "
                    "ثم استخدم `تتبع` لمتابعتها.",
                    parse_mode="Markdown"
                )
                return
            
            asset = last_rec["asset"]
            action = last_rec["action"]
            entry = last_rec["entry_price"]
            
            await u.message.reply_text(
                f"🎯 *آخر توصية:*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📊 الأصل: *{asset}*\n"
                f"⚡ Action: `{action}`\n"
                f"💰 Entry: `{entry:.4f}`\n"
                f"🛑 SL: `{last_rec.get('stop_loss', '—')}`\n"
                f"🎯 TP1/2/3: `{last_rec.get('take_profit_1','—')}` / "
                f"`{last_rec.get('take_profit_2','—')}` / `{last_rec.get('take_profit_3','—')}`\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"*لتفعيل التتبع:*\n"
                f"`تتبع {asset.lower().replace(' ', '').replace('/', '')} 0.05`\n"
                f"_(0.05 = حجم الصفقة بالـlots)_\n\n"
                f"_إذا لم تفعّل التتبع، البوت لن يعطيك إرشادات على هذه الصفقة._",
                parse_mode="Markdown"
            )
            return
        
        # ─── حالة 2: "تتبع [أصل] [حجم]" = تفعيل تتبع ───
        if len(parts) >= 2:
            asset_input = parts[1].lower()
            position_size = float(parts[2]) if len(parts) >= 3 else 0.01
            
            # خريطة الأصول
            asset_map = {
                "ذهب": "Gold", "gold": "Gold", "xauusd": "Gold",
                "فضة": "Silver", "silver": "Silver",
                "دولار": "USD/DXY", "dxy": "USD/DXY",
                "eurusd": "EUR/USD", "eur": "EUR/USD",
                "gbpusd": "GBP/USD", "gbp": "GBP/USD",
                "usdjpy": "USD/JPY", "jpy": "USD/JPY",
                "usdchf": "USD/CHF", "chf": "USD/CHF",
                "audusd": "AUD/USD", "aud": "AUD/USD",
                "بترول": "Oil", "oil": "Oil", "wti": "Oil",
            }
            asset = asset_map.get(asset_input)
            if not asset:
                await u.message.reply_text(
                    "⚠️ الأصل غير مدعوم.\n\n"
                    "*الصيغ المتاحة:*\n"
                    "• `تتبع ذهب 0.05`\n"
                    "• `تتبع eurusd 0.10`\n"
                    "• `تتبع بترول 0.05`",
                    parse_mode="Markdown"
                )
                return
            
            # ابحث عن آخر توصية على هذا الأصل
            last_rec = db_exec(
                "SELECT * FROM recommendations WHERE chat_id=? AND asset=? "
                "AND status='OPEN' AND action IN ('BUY', 'SELL', 'ADD') "
                "ORDER BY created_at DESC LIMIT 1",
                (chat_id, asset), fetch="one"
            )
            
            if not last_rec:
                await u.message.reply_text(
                    f"⚠️ *لا توجد توصية نشطة على {asset}*\n\n"
                    f"اطلب توصية جديدة أولاً:\n"
                    f"`{asset_input}` أو `توصية {asset_input}`",
                    parse_mode="Markdown"
                )
                return
            
            # تحقق من وجود تتبع نشط لنفس الأصل
            existing = db_exec(
                "SELECT id FROM tracked_trades WHERE chat_id=? AND asset=? AND status='ACTIVE'",
                (chat_id, asset), fetch="one"
            )
            if existing:
                await u.message.reply_text(
                    f"⚠️ *عندك صفقة نشطة بالفعل على {asset}!*\n"
                    f"Trade ID: `{existing['id']}`\n\n"
                    f"اكتب `صفقاتي` لرؤيتها، أو `الغاء_تتبع {existing['id']}` للإلغاء.",
                    parse_mode="Markdown"
                )
                return
            
            # ─── إنشاء التتبع ───
            trade_id = track_create_trade(
                chat_id=chat_id,
                asset=asset,
                action=last_rec["action"],
                entry=last_rec["entry_price"],
                sl=last_rec.get("stop_loss"),
                tp1=last_rec.get("take_profit_1"),
                tp2=last_rec.get("take_profit_2"),
                tp3=last_rec.get("take_profit_3"),
                position_size=position_size,
                capital=4000,
                recommendation_id=last_rec["id"],
                notes=f"Tracked from rec #{last_rec['id']}",
            )
            
            await u.message.reply_text(
                f"✅ *تم تفعيل التتبع!*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 Trade ID: `{trade_id}`\n"
                f"📊 الأصل: *{asset}*\n"
                f"⚡ Action: `{last_rec['action']}`\n"
                f"💰 Entry: `{last_rec['entry_price']:.4f}`\n"
                f"📏 الحجم: `{position_size}` lot\n"
                f"🛑 SL: `{last_rec.get('stop_loss', '—')}`\n"
                f"🎯 TPs: `{last_rec.get('take_profit_1','—')}` / "
                f"`{last_rec.get('take_profit_2','—')}` / `{last_rec.get('take_profit_3','—')}`\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 *البوت سيراقب الصفقة الآن:*\n"
                f"• يفحص السعر كل 5 دقائق\n"
                f"• يرسل تنبيه عند TP/SL\n"
                f"• يخبرك بفرص ADD وتغيرات Smart Money\n"
                f"• ينصحك بتحريك SL لـbreakeven بعد TP1\n\n"
                f"*أوامر مفيدة:*\n"
                f"• `صفقاتي` — كل صفقاتك النشطة\n"
                f"• `الغاء_تتبع {trade_id}` — إلغاء التتبع\n"
                f"• `حالة_صفقة {trade_id}` — تحديث فوري",
                parse_mode="Markdown"
            )
            return
    
    # ─── أمر "صفقاتي" ───
    if text in ("صفقاتي", "صفقات", "trades", "my_trades", "متابعاتي", "تتبعاتي"):
        trades = track_get_active_trades(chat_id)
        if not trades:
            await u.message.reply_text(
                "📭 *لا توجد صفقات نشطة*\n\n"
                "اطلب توصية ثم استخدم `تتبع [أصل] [حجم]`",
                parse_mode="Markdown"
            )
            return
        
        msg = f"📊 *صفقاتك النشطة ({len(trades)})*\n"
        msg += "═══════════════════════════\n\n"
        
        # نجلب الأسعار الحالية للحساب
        try:
            prices = fetch_prices()
        except Exception:
            prices = {}
        
        for t in trades:
            # نحاول إيجاد السعر الحالي
            current_price = None
            asset = t["asset"]
            
            # mapping للـasset → key in prices dict
            price_key_map = {
                "Gold": "Gold (XAUUSD)",
                "Silver": "Silver (XAGUSD)",
                "EUR/USD": "EUR/USD",
                "GBP/USD": "GBP/USD",
                "USD/JPY": "USD/JPY",
                "USD/CHF": "USD/CHF",
                "AUD/USD": "AUD/USD",
                "Oil": "Oil (WTI)",
            }
            price_key = price_key_map.get(asset)
            if price_key and price_key in prices:
                current_price = prices[price_key].get("price")
            
            entry = t["entry_price"]
            action = t["action"]
            tps_hit = sum([t.get("tp1_hit", 0), t.get("tp2_hit", 0), t.get("tp3_hit", 0)])
            
            msg += f"━━━ *Trade #{t['id']}* ━━━\n"
            msg += f"📊 *{asset}* | {action}\n"
            msg += f"💰 Entry: `{entry:.4f}`\n"
            
            if current_price:
                pnl_dollars, pnl_pct = track_calculate_pnl(t, current_price)
                pnl_icon = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
                msg += f"📈 الحالي: `{current_price:.4f}` ({pnl_icon} {pnl_pct:+.2f}%)\n"
                msg += f"💵 PnL: `${pnl_dollars:+.2f}`\n"
            
            msg += f"📏 الحجم: `{t.get('position_size', 0)}` lot\n"
            msg += f"🛑 SL: `{t.get('sl', '—')}`"
            if t.get("sl_moved_to_be"):
                msg += " (BE ✓)"
            msg += "\n"
            
            tp1_mark = "✅" if t.get("tp1_hit") else "⏳"
            tp2_mark = "✅" if t.get("tp2_hit") else "⏳"
            tp3_mark = "✅" if t.get("tp3_hit") else "⏳"
            msg += f"🎯 TP1: `{t.get('tp1', '—')}` {tp1_mark}\n"
            msg += f"🎯 TP2: `{t.get('tp2', '—')}` {tp2_mark}\n"
            msg += f"🎯 TP3: `{t.get('tp3', '—')}` {tp3_mark}\n"
            
            partial = t.get("partial_closed_pct", 0)
            if partial > 0:
                msg += f"📋 مغلق جزئياً: {partial}%\n"
            
            msg += "\n"
        
        msg += "═══════════════════════════\n"
        msg += "*أوامر:*\n"
        msg += "• `حالة_صفقة [ID]` — تحديث فوري\n"
        msg += "• `الغاء_تتبع [ID]` — إيقاف التتبع\n"
        msg += "• `اقفل_صفقة [ID] [سعر]` — إغلاق يدوي"
        
        await send_long(u, msg)
        return
    
    # ─── أمر "حالة_صفقة [ID]" ───
    if text.startswith(("حالة_صفقة", "حالة صفقة", "trade_status", "صفقة")):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text(
                "⚠️ الصيغة: `حالة_صفقة [ID]`\nمثال: `حالة_صفقة 1`",
                parse_mode="Markdown"
            )
            return
        try:
            trade_id = int(parts[1])
        except ValueError:
            await u.message.reply_text("⚠️ ID لازم يكون رقم")
            return
        
        trade = track_get_trade(trade_id)
        if not trade or trade["chat_id"] != chat_id:
            await u.message.reply_text(f"⚠️ صفقة #{trade_id} غير موجودة")
            return
        
        # نفحص حالتها فوراً
        from_track = await trade_check_single(trade, send_alert=False)
        
        msg = f"🔍 *تحديث Trade #{trade_id}*\n"
        msg += "━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📊 *{trade['asset']}* | {trade['action']}\n"
        msg += f"📅 الحالة: {trade['status']}\n"
        msg += f"💰 Entry: `{trade['entry_price']:.4f}`\n"
        
        if from_track and from_track.get("current_price"):
            cp = from_track["current_price"]
            pnl_d, pnl_p = track_calculate_pnl(trade, cp)
            pnl_icon = "🟢" if pnl_p > 0 else "🔴" if pnl_p < 0 else "⚪"
            msg += f"📈 السعر الحالي: `{cp:.4f}`\n"
            msg += f"{pnl_icon} PnL: `{pnl_p:+.2f}%` (`${pnl_d:+.2f}`)\n\n"
        
        msg += f"🛑 SL: `{trade.get('sl', '—')}`\n"
        msg += f"🎯 TP1: `{trade.get('tp1', '—')}` {'✅' if trade.get('tp1_hit') else '⏳'}\n"
        msg += f"🎯 TP2: `{trade.get('tp2', '—')}` {'✅' if trade.get('tp2_hit') else '⏳'}\n"
        msg += f"🎯 TP3: `{trade.get('tp3', '—')}` {'✅' if trade.get('tp3_hit') else '⏳'}\n"
        
        await u.message.reply_text(msg, parse_mode="Markdown")
        return
    
    # ─── أمر "الغاء_تتبع [ID]" ───
    if text.startswith(("الغاء_تتبع", "إلغاء_تتبع", "untrack", "وقف_تتبع")):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text(
                "⚠️ الصيغة: `الغاء_تتبع [ID]`",
                parse_mode="Markdown"
            )
            return
        try:
            trade_id = int(parts[1])
        except ValueError:
            await u.message.reply_text("⚠️ ID لازم يكون رقم")
            return
        
        trade = track_get_trade(trade_id)
        if not trade or trade["chat_id"] != chat_id:
            await u.message.reply_text(f"⚠️ صفقة #{trade_id} غير موجودة")
            return
        
        track_update_trade(trade_id, status="CANCELED",
                          closed_at=datetime.now(timezone.utc).isoformat(),
                          exit_reason="MANUAL_CANCEL")
        
        await u.message.reply_text(
            f"✅ *تم إلغاء تتبع Trade #{trade_id}*\n"
            f"({trade['asset']} {trade['action']})",
            parse_mode="Markdown"
        )
        return
    
    # ─── أمر "اقفل_صفقة [ID] [سعر]" ───
    if text.startswith(("اقفل_صفقة", "إغلاق_صفقة", "close_trade", "اقفل")):
        parts = text.split()
        if len(parts) < 3:
            await u.message.reply_text(
                "⚠️ الصيغة: `اقفل_صفقة [ID] [سعر_الإغلاق]`",
                parse_mode="Markdown"
            )
            return
        try:
            trade_id = int(parts[1])
            exit_price = float(parts[2])
        except ValueError:
            await u.message.reply_text("⚠️ ID وسعر يجب أن يكونا أرقام")
            return
        
        trade = track_get_trade(trade_id)
        if not trade or trade["chat_id"] != chat_id:
            await u.message.reply_text(f"⚠️ صفقة #{trade_id} غير موجودة")
            return
        
        pnl_d, pnl_p = track_calculate_pnl(trade, exit_price)
        track_close_trade(trade_id, exit_price, "MANUAL", pnl_d, pnl_p)
        
        result_icon = "🟢" if pnl_p > 0 else "🔴"
        await u.message.reply_text(
            f"✅ *تم إغلاق Trade #{trade_id}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {trade['asset']} | {trade['action']}\n"
            f"💰 Entry: `{trade['entry_price']:.4f}`\n"
            f"🚪 Exit: `{exit_price:.4f}`\n"
            f"{result_icon} PnL: `{pnl_p:+.2f}%` (`${pnl_d:+.2f}`)",
            parse_mode="Markdown"
        )
        return
    
    # ═══════════════════════════════════════════════════════════════════
    # 📰 LIVE NEWS TRACKING — تتبع الأخبار العاجلة
    # ═══════════════════════════════════════════════════════════════════
    if text.startswith(("تتبع_اخبار", "تتبع اخبار", "تتبع أخبار", "تتبع_أخبار",
                        "track_news", "متابعة_اخبار", "اخبار_مباشر")):
        parts = text.split()
        # ─── تحديد الأصول من الأمر ───
        # تتبع اخبار            = كل الأصول
        # تتبع اخبار ذهب       = الذهب فقط
        # تتبع اخبار ذهب فوركس = الذهب + الفوركس
        
        assets_filter = None
        if len(parts) >= 3:
            asset_args = [p.lower() for p in parts[2:]]
            assets_filter = []
            for a in asset_args:
                if a in ("ذهب", "gold", "xau"):
                    assets_filter.append("Gold")
                elif a in ("فضة", "silver"):
                    assets_filter.append("Silver")
                elif a in ("فوركس", "forex"):
                    assets_filter.extend(["EUR/USD", "GBP/USD", "USD/JPY"])
                elif a in ("بترول", "oil"):
                    assets_filter.append("Oil")
                elif a in ("الكل", "all"):
                    assets_filter = None
                    break
        
        news_tracking_enable(
            chat_id=chat_id,
            assets=assets_filter,
            min_impact=2,
            ai_analysis=True,
        )
        
        assets_text = ", ".join(assets_filter) if assets_filter else "كل الأصول"
        
        await u.message.reply_text(
            f"✅ *تفعيل تتبع الأخبار العاجلة*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📰 الأصول: {assets_text}\n"
            f"⚡ التأثير: متوسط أو عالي\n"
            f"🧠 تحليل AI تلقائي: ✅\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 *البوت سيرسل لك الآن:*\n"
            f"• كل خبر عاجل (high-impact) فور صدوره\n"
            f"• تحليل AI سريع لتأثير الخبر\n"
            f"• توصية فورية (BUY/SELL/HOLD/تجنّب)\n"
            f"• المستويات المهمة للمراقبة\n\n"
            f"*أوامر:*\n"
            f"• `وقف_اخبار` — إلغاء التتبع\n"
            f"• `حالة_اخبار` — عرض الإعدادات",
            parse_mode="Markdown"
        )
        return
    
    if text in ("وقف_اخبار", "وقف_أخبار", "stop_news", "الغاء_اخبار", "إلغاء_اخبار"):
        status = news_tracking_get_status(chat_id)
        if not status or not status.get("enabled"):
            await u.message.reply_text(
                "⚠️ ما عندك تتبع أخبار مفعّل أصلاً.",
                parse_mode="Markdown"
            )
            return
        
        news_tracking_disable(chat_id)
        await u.message.reply_text(
            "✅ *تم إيقاف تتبع الأخبار العاجلة*\n\n"
            "_لإعادة التفعيل: `تتبع_اخبار`_",
            parse_mode="Markdown"
        )
        return
    
    if text in ("حالة_اخبار", "حالة_أخبار", "news_status"):
        status = news_tracking_get_status(chat_id)
        if not status or not status.get("enabled"):
            await u.message.reply_text(
                "📭 *تتبع الأخبار غير مفعّل*\n\n"
                "للتفعيل: `تتبع_اخبار`",
                parse_mode="Markdown"
            )
            return
        
        assets = status.get("assets", "ALL")
        impact_text = {1: "كل الأخبار", 2: "متوسط+عالي", 3: "عالي فقط"}.get(
            status.get("min_impact", 2), "متوسط+عالي"
        )
        
        await u.message.reply_text(
            f"📰 *حالة تتبع الأخبار*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"✅ مفعّل\n"
            f"📊 الأصول: {assets}\n"
            f"⚡ التأثير: {impact_text}\n"
            f"🧠 AI: {'✅' if status.get('ai_analysis') else '❌'}\n"
            f"📅 بدأ من: {status.get('started_at', '')[:10]}\n\n"
            f"_للإيقاف: `وقف_اخبار`_",
            parse_mode="Markdown"
        )
        return
    
    # ═══ ⚡ SCALPING — تحليل سريع (1m + 5m) ═══
    # الصيغة: سكالب [الأصل]
    # أمثلة: سكالب ذهب / سكالب فضة / سكالب eurusd / سكالب بترول
    if text.startswith(("سكالب", "scalp", "سكالبينج", "scalping")):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await u.message.reply_text(
                "⚡ *Scalping Analysis*\n\n"
                "الصيغة: `سكالب [الأصل]`\n\n"
                "*أمثلة:*\n"
                "• `سكالب ذهب`\n"
                "• `سكالب فضة`\n"
                "• `سكالب eurusd`\n"
                "• `سكالب gbpusd`\n"
                "• `سكالب usdjpy`\n"
                "• `سكالب بترول`\n\n"
                "📊 *البوت يحلل 7 مؤشرات على فريم 1m + 5m:*\n"
                "1. RSI(7) 1m\n"
                "2. EMA Cross (5/13)\n"
                "3. Bollinger Bands 5m\n"
                "4. Volume Spike\n"
                "5. Stochastic\n"
                "6. ATR Momentum\n"
                "7. Candle Pattern\n\n"
                "⚡ يعطي قرار LONG/SHORT/WAIT + SL/TP ضيق",
                parse_mode="Markdown"
            )
            return
        
        asset_raw = parts[1].lower().strip()
        # ─── خريطة الأصول ───
        scalp_asset_map = {
            # الذهب
            "ذهب": ("Gold", "GC=F"), "gold": ("Gold", "GC=F"),
            "xauusd": ("Gold", "GC=F"), "xau": ("Gold", "GC=F"),
            # الفضة
            "فضة": ("Silver", "SI=F"), "silver": ("Silver", "SI=F"),
            "xagusd": ("Silver", "SI=F"), "xag": ("Silver", "SI=F"),
            # Forex
            "eurusd": ("EUR/USD", "EURUSD=X"), "eur": ("EUR/USD", "EURUSD=X"), "يورو": ("EUR/USD", "EURUSD=X"),
            "gbpusd": ("GBP/USD", "GBPUSD=X"), "gbp": ("GBP/USD", "GBPUSD=X"), "باوند": ("GBP/USD", "GBPUSD=X"),
            "usdjpy": ("USD/JPY", "JPY=X"), "jpy": ("USD/JPY", "JPY=X"), "ين": ("USD/JPY", "JPY=X"),
            "usdchf": ("USD/CHF", "CHF=X"), "chf": ("USD/CHF", "CHF=X"),
            "audusd": ("AUD/USD", "AUDUSD=X"), "aud": ("AUD/USD", "AUDUSD=X"),
            # البترول
            "بترول": ("Oil", "CL=F"), "نفط": ("Oil", "CL=F"), "oil": ("Oil", "CL=F"), "wti": ("Oil", "CL=F"),
        }
        
        asset_info = scalp_asset_map.get(asset_raw)
        if not asset_info:
            await u.message.reply_text(
                "⚠️ الأصل غير مدعوم في Scalping.\n\n"
                "*الأصول المتاحة:*\n"
                "🥇 ذهب / gold | 🥈 فضة / silver\n"
                "💱 eurusd / gbpusd / usdjpy / usdchf / audusd\n"
                "🛢️ بترول / oil / wti",
                parse_mode="Markdown"
            )
            return
        
        asset, ticker = asset_info
        
        await u.message.reply_text(
            f"⚡ *Scalping Analysis — {asset}*\n_جاري تحليل 7 مؤشرات..._",
            parse_mode="Markdown"
        )
        
        try:
            scalp_result = analyze_scalp(asset, ticker)
            if not scalp_result:
                await u.message.reply_text(
                    "⚠️ تعذّر تحليل Scalping — تأكد من توفر بيانات 1m/5m"
                )
                return
            
            text_out = format_scalp(scalp_result)
            await send_long(u, text_out)
        except Exception as e:
            log.warning(f"Scalp error: {e}")
            await u.message.reply_text(f"⚠️ خطأ: {str(e)[:100]}")
        return
    
    # ═══ التوصيات ═══
    if text in ("توصية", "توصيه", "recommend", "ذهب", "توصية ذهب", "توصيه ذهب", "gold"):
        await u.message.reply_text(
            "⏳ *جاري بناء توصية الذهب...*\n_(60 ثانية)_",
            parse_mode="Markdown")
        rec = build_recommendation(asset="Gold", chat_id=chat_id)
        for m in format_recommendation(rec):
            await send_long(u, m)
            await asyncio.sleep(0.3)
        return
    
    if text in ("توصية دولار", "توصية الدولار", "دولار", "dollar", "dxy"):
        await u.message.reply_text("⏳ *توصية الدولار...*", parse_mode="Markdown")
        rec = build_recommendation(asset="USD/DXY", chat_id=chat_id)
        for m in format_recommendation(rec):
            await send_long(u, m)
            await asyncio.sleep(0.3)
        return
    
    if text in ("أداء", "اداء", "performance"):
        await send_long(u, performance_report(chat_id))
        return
    
    # ═══ التحليل ═══
    if text in ("تحليل", "analysis"):
        await u.message.reply_text("⏳ *تحليل بـ3 AIs...*", parse_mode="Markdown")
        prices = fetch_prices()
        news = fetch_news(max_per_source=3, hours_back=24)[:8]
        prompt = (
            "بيانات السوق:\n" +
            "\n".join(f"- {k}: {v['price']:.4f} ({v['change_pct']:+.2f}%)"
                     for k, v in prices.items()) +
            "\n\nأخبار:\n" +
            "\n".join(f"- {n['title']}" for n in news) +
            "\n\nأعطِ تحليلاً شاملاً للسوق الآن."
        )
        analyses = multi_ai(prompt)
        for name, txt in analyses.items():
            if txt.startswith(("⚪","⚠️")): continue
            ic = {"Claude":"🧠","Gemini":"💎","OpenAI":"🤖"}.get(name, "🔵")
            await send_long(u, f"{ic} *{name}*\n━━━━━━━━━━━━━━━━━━━\n\n{txt}")
        return
    
    if text in ("فني", "technical", "ta"):
        await u.message.reply_text("⏳ *تحليل فني...*", parse_mode="Markdown")
        ta = technical_analysis("GC=F")
        await send_long(u, format_technical(ta))
        return
    
    # ═══ Smart Money ═══
    if text in ("حيتان", "smart money", "cot"):
        await u.message.reply_text("⏳ *جاري جلب COT...*", parse_mode="Markdown")
        cot = fetch_cot_data()
        await send_long(u, format_cot(cot))
        return
    
    if text in ("سعر_ذهب", "سعر ذهب", "gold_price", "ذهب_الآن", "gold_now"):
        await u.message.reply_text("⏳ *جاري فحص كل مصادر سعر الذهب...*", parse_mode="Markdown")
        
        msg = "🥇 *تشخيص سعر الذهب — كل المصادر*\n"
        msg += "━━━━━━━━━━━━━━━━━━━\n\n"
        
        # ═══ Polygon Forex Snapshot (C:XAUUSD) ═══
        msg += "*1️⃣ Polygon — Forex Snapshot (C:XAUUSD):*\n"
        if not POLYGON_API_KEY:
            msg += "   ❌ POLYGON_API_KEY غير موجود\n\n"
        else:
            data = polygon_get(
                "/v2/snapshot/locale/global/markets/forex/tickers/C:XAUUSD",
                return_error=True,
            )
            if isinstance(data, dict) and data.get("_error"):
                msg += f"   ❌ {data.get('_message', 'فشل')}\n"
                if data.get("_error") == "plan":
                    msg += "   _XAU/USD غير متاح في خطتك الحالية_\n"
                msg += "\n"
            elif data and data.get("status") == "OK" and data.get("ticker"):
                td = data["ticker"]
                lq = td.get("lastQuote", {}) or {}
                bid, ask = lq.get("b", 0), lq.get("a", 0)
                mid = (bid + ask) / 2 if (bid and ask) else 0
                if mid:
                    msg += f"   ✅ السعر: `${mid:,.2f}`\n"
                    msg += f"   Bid/Ask: `${bid:,.2f}` / `${ask:,.2f}`\n\n"
                else:
                    msg += "   ⚠️ بيانات فارغة (السوق مغلق؟)\n\n"
            else:
                msg += "   ⚠️ لا يوجد رد صحيح\n\n"
        
        # ═══ Polygon Currency Conversion (XAU → USD) ═══
        msg += "*2️⃣ Polygon — Conversion (XAU/USD):*\n"
        if not POLYGON_API_KEY:
            msg += "   ❌ غير متاح\n\n"
        else:
            data = polygon_get(
                "/v1/conversion/XAU/USD",
                {"amount": 1, "precision": 2},
                return_error=True,
            )
            if isinstance(data, dict) and data.get("_error"):
                msg += f"   ❌ {data.get('_message', 'فشل')}\n\n"
            elif data and data.get("converted"):
                msg += f"   ✅ السعر: `${data['converted']:,.2f}`\n\n"
            else:
                msg += "   ⚠️ لا يوجد converted في الرد\n\n"
        
        # ═══ Polygon GLD ETF (يحتاج Stocks plan) ═══
        msg += "*3️⃣ Polygon — GLD ETF Snapshot:*\n"
        if not POLYGON_API_KEY:
            msg += "   ❌ غير متاح\n\n"
        else:
            data = polygon_get(
                "/v2/snapshot/locale/us/markets/stocks/tickers/GLD",
                return_error=True,
            )
            if isinstance(data, dict) and data.get("_error"):
                msg += f"   ❌ {data.get('_message', 'فشل')}\n\n"
            elif data and data.get("status") == "OK" and data.get("ticker"):
                td = data["ticker"]
                last_trade = td.get("lastTrade", {}) or {}
                gld_p = last_trade.get("p", 0)
                if gld_p:
                    estimated = gld_p * 10
                    msg += f"   ✅ GLD: `${gld_p:.2f}` → الذهب ≈ `${estimated:,.2f}`\n\n"
                else:
                    msg += "   ⚠️ بيانات GLD فارغة\n\n"
            else:
                msg += "   ⚠️ لا يوجد رد\n\n"
        
        # ═══ yfinance GC=F ═══
        msg += "*4️⃣ yfinance (GC=F):*\n"
        try:
            t = yf.Ticker("GC=F")
            hist = t.history(period="1d", interval="1m")
            if not hist.empty:
                yf_p = float(hist["Close"].iloc[-1])
                msg += f"   📊 السعر: `${yf_p:,.2f}`\n"
                if yf_p < 3000:
                    msg += f"   ⚠️ يبدو contract منتهي (السعر الحقيقي >$4000)\n"
                msg += "\n"
            else:
                msg += "   ❌ بيانات فارغة\n\n"
        except Exception as e:
            msg += f"   ❌ خطأ: {str(e)[:50]}\n\n"
        
        # ═══ القرار النهائي ═══
        poly = polygon_get_gold_price()
        msg += "━━━━━━━━━━━━━━━━━━━\n"
        msg += "*🎯 السعر اللي يستخدمه البوت:*\n"
        if poly:
            msg += f"`${poly['price']:,.2f}`\n"
            msg += f"_المصدر: {poly.get('source', 'unknown')}_\n"
        else:
            msg += "⚠️ كل مصادر Polygon فشلت → fallback لـyfinance\n"
            msg += "_قد يكون الرقم غير دقيق_\n"
        
        await send_long(u, msg)
        return
    
        if not ENABLE_OPTIONS:
            await u.message.reply_text(
                "💎 *Options Sentiment معطّلة*\n"
                "━━━━━━━━━━━━━━━━━━━\n\n"
                "ℹ️ هذه الميزة معطّلة افتراضياً لأنها تحتاج اشتراك *Options Starter* "
                "($29/شهر إضافي على Polygon)\n\n"
                "✅ *البديل الأقوى عندك جاهز:*\n"
                "أمر `حيتان` يعرض *CFTC COT Reports* — وهي **أقوى من Options Sentiment** "
                "للذهب لأنها تكشف مراكز Hedge Funds الفعلية في *CME Gold Futures* "
                "(ليس مجرد proxy على GLD ETF).\n\n"
                "🔧 *لتفعيل الميزة لاحقاً:*\n"
                "1. اشترك في Options Starter ($29) من polygon.io\n"
                "2. أضف في Railway Variables: `ENABLE_OPTIONS = true`\n"
                "3. أعد تشغيل البوت\n\n"
                "💡 جرّب الآن: `حيتان`",
                parse_mode="Markdown"
            )
            return
        await u.message.reply_text("⏳ *Options Sentiment...*", parse_mode="Markdown")
        opts = polygon_options_aggregate("GLD", return_error=True)
        await send_long(u, format_options_sentiment(opts))
        return
    
    if text in ("فوركس_مباشر", "فوركس مباشر", "forex_live", "fx", "فوركس"):
        await u.message.reply_text("⏳ *جاري جلب أسعار Forex مباشرة من Polygon...*", parse_mode="Markdown")
        
        if not POLYGON_API_KEY:
            await u.message.reply_text(
                "❌ *Polygon API غير مفعّل*\n\nأضف `POLYGON_API_KEY` في Variables",
                parse_mode="Markdown"
            )
            return
        
        # أهم 6 أزواج
        pairs = [
            ("C:EURUSD", "EUR/USD"),
            ("C:GBPUSD", "GBP/USD"),
            ("C:USDJPY", "USD/JPY"),
            ("C:USDCHF", "USD/CHF"),
            ("C:AUDUSD", "AUD/USD"),
            ("C:USDCAD", "USD/CAD"),
        ]
        
        msg = "💱 *Forex Live — Polygon Real-time*\n"
        msg += "━━━━━━━━━━━━━━━━━━━\n\n"
        
        any_data = False
        for ticker, name in pairs:
            data = polygon_forex_realtime(ticker)
            if not data or not data.get("mid"):
                msg += f"*{name}:* غير متاح\n"
                continue
            any_data = True
            arrow = "🟢" if data["change_pct"] > 0 else "🔴" if data["change_pct"] < 0 else "⚪"
            decimals = 2 if "JPY" in name else 5
            msg += f"{arrow} *{name}:* `{data['mid']:.{decimals}f}`\n"
            msg += f"   التغير: `{data['change_pct']:+.2f}%`\n"
            msg += f"   Bid/Ask: `{data['bid']:.{decimals}f}` / `{data['ask']:.{decimals}f}`\n"
            if data.get("day_high") and data.get("day_low"):
                msg += f"   Range اليوم: `{data['day_low']:.{decimals}f}` - `{data['day_high']:.{decimals}f}`\n"
            msg += "\n"
        
        if not any_data:
            msg += "❌ *لم يتم استلام بيانات*\n\n"
            msg += "💡 جرّب أمر `فحص_polygon` للتشخيص"
        else:
            msg += "━━━━━━━━━━━━━━━━━━━\n"
            msg += "💎 _Powered by Polygon Currencies Starter_\n"
            msg += "_البيانات Real-time + Cache 30s_"
        
        await send_long(u, msg)
        return
    
    if text in ("فحص_polygon", "polygon_test", "polygon", "فحص بوليجون"):
        await u.message.reply_text("🔍 *جاري فحص Polygon API...*", parse_mode="Markdown")
        msg = "🔍 *تشخيص Polygon API*\n"
        msg += "━━━━━━━━━━━━━━━━━━━\n\n"
        
        # 1) فحص وجود الـkey
        if not POLYGON_API_KEY:
            msg += "❌ *POLYGON_API_KEY غير موجود*\n\n"
            msg += "🔧 *الحل:*\n"
            msg += "1. روح Railway → Project → Variables\n"
            msg += "2. أضف: `POLYGON_API_KEY = your_key_here`\n"
            msg += "3. أعد تشغيل الـBot\n"
            await send_long(u, msg)
            return
        
        # نخفي معظم الـkey
        masked = POLYGON_API_KEY[:6] + "..." + POLYGON_API_KEY[-4:] if len(POLYGON_API_KEY) > 10 else "***"
        msg += f"✅ API Key موجود: `{masked}`\n"
        msg += f"   الطول: {len(POLYGON_API_KEY)} حرف\n\n"
        
        # 2) اختبار endpoint مجاني (أساسي - متاح في كل الخطط)
        msg += "*1️⃣ اختبار endpoint مجاني (Tickers):*\n"
        test1 = polygon_get("/v3/reference/tickers", {"limit": 1}, return_error=True)
        if isinstance(test1, dict) and test1.get("_error"):
            msg += f"   ❌ فشل: {test1.get('_message')}\n"
            msg += f"   Status: {test1.get('_status', 'N/A')}\n\n"
            msg += "🔧 *المشكلة في الـAPI Key نفسه — راجعه*\n"
            await send_long(u, msg)
            return
        elif test1 and "results" in test1:
            msg += f"   ✅ نجح — الـAPI Key شغّال\n\n"
        else:
            msg += f"   ⚠️ رد غريب من السيرفر\n\n"
        
        # 3) اختبار Stocks (يحتاج Stocks plan)
        msg += "*2️⃣ اختبار Stocks Snapshot:*\n"
        test2 = polygon_get("/v2/snapshot/locale/us/markets/stocks/tickers/AAPL", return_error=True)
        if isinstance(test2, dict) and test2.get("_error"):
            err_type = test2.get('_error')
            if err_type == "plan":
                msg += f"   ❌ خطتك ما فيهاش Stocks\n"
            else:
                msg += f"   ❌ {test2.get('_message')}\n"
        elif test2 and test2.get("status") == "OK":
            msg += f"   ✅ Stocks متاح\n"
        else:
            msg += f"   ⚠️ رد غير متوقع\n"
        msg += "\n"
        
        # 4) اختبار Options (الأهم!)
        msg += "*3️⃣ اختبار Options Snapshot (الأهم):*\n"
        test3 = polygon_options_aggregate("GLD", return_error=True)
        if test3.get("_error"):
            err_type = test3.get('_error')
            err_msg = test3.get('_message')
            msg += f"   ❌ {err_msg}\n"
            if err_type == "plan":
                msg += "\n💡 *النتيجة:*\n"
                msg += "خطتك الحالية على Polygon **لا تشمل Options**\n\n"
                msg += "🔧 *للحل:*\n"
                msg += "1. اشترك في *Options Starter* ($29/شهر)\n"
                msg += "   من polygon.io/dashboard\n"
                msg += "2. أو استمر بدون Options — البوت شغّال 95%\n"
            elif err_type == "rate_limit":
                msg += "\n💡 الخطة المجانية محدودة بـ5 طلبات/دقيقة\n"
        elif test3 and test3.get("underlying"):
            msg += f"   ✅ Options متاح وشغّال!\n"
            msg += f"   Calls Vol: {test3.get('calls_volume', 0):,}\n"
            msg += f"   Puts Vol: {test3.get('puts_volume', 0):,}\n"
        else:
            msg += f"   ⚠️ السوق مغلق أو لا توجد بيانات\n"
        
        msg += "\n━━━━━━━━━━━━━━━━━━━\n"
        msg += "💡 *ملاحظة:* البوت شغّال كامل بدون Polygon\n"
        msg += "Options Sentiment ميزة إضافية فقط"
        
        await send_long(u, msg)
        return
    
    if text in ("بنوك", "central banks", "فيد"):
        await u.message.reply_text("⏳ *تحليل البنوك...*", parse_mode="Markdown")
        prices = fetch_prices()
        fed = derive_fed_expectations(prices)
        yc = analyze_yield_curve(prices)
        cb = fetch_te_central_banks()
        await send_long(u, format_central_banks(fed, yc, cb))
        return
    
    if text in ("ماكرو", "macro", "fred"):
        await u.message.reply_text("⏳ *Macro Snapshot...*", parse_mode="Markdown")
        macro = fred_get_macro_snapshot()
        if not macro:
            await u.message.reply_text("⚠️ FRED API غير مكوّن")
            return
        msg = "🌍 *Macro Snapshot — FRED*\n━━━━━━━━━━━━━━━━━━━\n\n"
        for k, v in macro.items():
            arrow = "📈" if v["change"] > 0 else "📉" if v["change"] < 0 else "➡️"
            msg += f"{arrow} *{k}*\n"
            msg += f"   القيمة: `{v['value']:.2f}`\n"
            msg += f"   السابقة: `{v['previous']:.2f}` (تغيّر `{v['change']:+.2f}`)\n"
            msg += f"   📅 `{v['date']}`\n\n"
        await send_long(u, msg)
        return
    
    # ═══ الأخبار ═══
    if text in ("أخبار", "اخبار", "news"):
        await u.message.reply_text("⏳ *جاري الجلب...*", parse_mode="Markdown")
        news = fetch_news(max_per_source=4, hours_back=24)[:10]
        await send_long(u, format_news_list(news, "آخر الأخبار"))
        return
    
    if text in ("أخبار ذهب", "اخبار ذهب"):
        news = filter_news_by_topic(
            fetch_news(max_per_source=8, hours_back=48),
            ["gold", "xauusd", "ذهب", "fed", "inflation", "cpi"]
        )[:10]
        await send_long(u, format_news_list(news, "أخبار الذهب"))
        return
    
    if text in ("أخبار فوركس", "اخبار فوركس"):
        news = filter_news_by_topic(
            fetch_news(max_per_source=8, hours_back=48),
            ["eurusd", "gbpusd", "dollar", "ecb", "boe", "boj", "dxy"]
        )[:10]
        await send_long(u, format_news_list(news, "أخبار الفوركس"))
        return
    
    if text in ("عاجل", "urgent"):
        news = fetch_news(max_per_source=5, hours_back=24)
        hi = [n for n in news if is_high_impact(n)[0]][:8]
        await send_long(u, format_news_list(hi, "🚨 High-Impact"))
        return
    
    # ═══ الأسعار + تقويم ═══
    if text in ("أسعار", "اسعار", "prices"):
        prices = fetch_prices()
        await send_long(u, format_prices(prices))
        return
    
    if text in ("تقويم", "calendar"):
        events = fetch_te_calendar(days_ahead=7)[:12]
        if not events:
            await u.message.reply_text("⚠️ لا توجد بيانات")
            return
        msg = "📅 *التقويم الاقتصادي — الأسبوع*\n━━━━━━━━━━━━━━━━━━━\n\n"
        for e in events:
            imp = e.get("Importance", 1)
            ic = {3:"🔴", 2:"🟡"}.get(imp, "⚪")
            msg += f"{ic} *{e.get('Event','—')[:60]}*\n"
            msg += f"   💱 `{e.get('Country','—')}`\n"
            if e.get("Forecast") is not None:
                msg += f"   التوقع: `{e['Forecast']}` · "
            if e.get("Previous") is not None:
                msg += f"السابق: `{e['Previous']}`\n"
            if e.get("Date"):
                msg += f"   ⏰ `{str(e['Date'])[:16]}`\n"
            msg += "\n"
        await send_long(u, msg)
        return
    
    # ═══ سؤال مفتوح ═══
    if text.startswith(("سؤال ", "اسأل ", "ask ")):
        question = text.split(" ", 1)[1] if " " in text else ""
        if not question:
            await u.message.reply_text("الصيغة: `سؤال متى يهبط الذهب؟`",
                                        parse_mode="Markdown")
            return
        await u.message.reply_text("⏳ *الاستشارة...*", parse_mode="Markdown")
        prices = fetch_prices()
        ctx_text = "\n".join(
            f"- {k}: {v['price']:.4f} ({v['change_pct']:+.2f}%)"
            for k in ["Gold (XAUUSD)", "DXY (Dollar)", "10Y Yield"]
            for v in [prices.get(k)] if v
        )
        prompt = f"السوق الآن:\n{ctx_text}\n\nسؤال: {question}"
        analyses = multi_ai(prompt)
        for name, txt in analyses.items():
            if txt.startswith(("⚪","⚠️")): continue
            ic = {"Claude":"🧠","Gemini":"💎","OpenAI":"🤖"}.get(name, "🔵")
            await send_long(u, f"{ic} *{name}*\n\n{txt}")
        return
    
    # ═══ Smart Risk Analysis - تحليل مخاطر يدوي ═══
    # الصيغة: مخاطر [ذهب/دولار] [buy/sell] [السعر] [رأس المال اختياري]
    # أمثلة: مخاطر ذهب buy 2650
    #        مخاطر ذهب sell 2680 5000
    if text.startswith(("مخاطر", "risk", "إدارة")):
        parts = text.split()
        if len(parts) < 4:
            await u.message.reply_text(
                "📋 *Smart Risk Analysis*\n\n"
                "الصيغة:\n"
                "`مخاطر [ذهب/دولار] [buy/sell] [السعر] [رأس_المال]`\n\n"
                "أمثلة:\n"
                "• `مخاطر ذهب buy 2650`\n"
                "• `مخاطر ذهب sell 2680 5000`\n"
                "• `مخاطر دولار buy 105.20`\n\n"
                "البوت يحلل:\n"
                "✓ 3 مستويات SL ذكية\n"
                "✓ 3 أهداف TP + احتمالات\n"
                "✓ Danger Zones & Reject Zones\n"
                "✓ Position Sizing\n"
                "✓ Partial Close Strategy",
                parse_mode="Markdown"
            )
            return
        
        try:
            asset_input = parts[1].lower()
            action_input = parts[2].upper()
            entry_input = float(parts[3].replace(",", ""))
            capital_input = float(parts[4].replace(",", "")) if len(parts) >= 5 else 4000
            
            # ═══ Map asset (دعم كل الأصول) ═══
            asset_map = {
                # الذهب
                "ذهب": "Gold", "gold": "Gold", "xauusd": "Gold", "xau": "Gold",
                # الفضة
                "فضة": "Silver", "silver": "Silver", "xagusd": "Silver", "xag": "Silver",
                # الدولار
                "دولار": "USD/DXY", "dollar": "USD/DXY", "dxy": "USD/DXY",
                # Forex
                "eurusd": "EUR/USD", "eur": "EUR/USD", "يورو": "EUR/USD",
                "gbpusd": "GBP/USD", "gbp": "GBP/USD", "باوند": "GBP/USD", "إسترليني": "GBP/USD",
                "usdjpy": "USD/JPY", "jpy": "USD/JPY", "ين": "USD/JPY",
                "usdchf": "USD/CHF", "chf": "USD/CHF", "فرنك": "USD/CHF",
                "audusd": "AUD/USD", "aud": "AUD/USD", "أسترالي": "AUD/USD",
                # البترول
                "بترول": "Oil", "نفط": "Oil", "oil": "Oil", "wti": "Oil", "crude": "Oil",
            }
            asset = asset_map.get(asset_input)
            if not asset:
                await u.message.reply_text(
                    "⚠️ الأصل غير مدعوم. الأصول المتاحة:\n\n"
                    "🥇 ذهب / gold / xauusd\n"
                    "🥈 فضة / silver / xagusd\n"
                    "💵 دولار / dxy\n"
                    "💱 eurusd / gbpusd / usdjpy / usdchf / audusd\n"
                    "🛢️ بترول / oil / wti",
                    parse_mode="Markdown"
                )
                return
            
            # Map asset → ticker yfinance + Polygon asset key
            asset_ticker_map = {
                "Gold":    {"yf": "GC=F",      "poly": "XAU/USD"},
                "Silver":  {"yf": "SI=F",      "poly": "XAG/USD"},
                "USD/DXY": {"yf": "DX-Y.NYB",  "poly": None},  # DXY مش في Polygon
                "EUR/USD": {"yf": "EURUSD=X",  "poly": "EUR/USD"},
                "GBP/USD": {"yf": "GBPUSD=X",  "poly": "GBP/USD"},
                "USD/JPY": {"yf": "JPY=X",     "poly": "USD/JPY"},
                "USD/CHF": {"yf": "CHF=X",     "poly": "USD/CHF"},
                "AUD/USD": {"yf": "AUDUSD=X",  "poly": "AUD/USD"},
                "Oil":     {"yf": "CL=F",      "poly": "WTI"},
            }
            ticker_info = asset_ticker_map.get(asset, {"yf": "GC=F", "poly": None})
            
            if action_input not in ("BUY", "SELL", "ADD"):
                await u.message.reply_text("⚠️ Action لازم يكون: BUY أو SELL أو ADD")
                return
            
            await u.message.reply_text(
                f"⏳ *Smart Risk Analysis*\n_{asset} | {action_input} @ {entry_input}_",
                parse_mode="Markdown"
            )
            
            # جلب TA + DataFrame
            ta_ticker = ticker_info["yf"]
            ta_full = technical_analysis(ta_ticker)
            
            # للأصول المدعومة في Polygon: استخدم scaled DataFrame
            poly_asset_key = ticker_info.get("poly")
            scale_info = {"applied": False}
            if poly_asset_key:
                df_daily, scale_info = get_asset_dataframe_scaled(
                    poly_asset_key, ta_ticker, period="6mo", interval="1d"
                )
                if df_daily is None or df_daily.empty:
                    t = yf.Ticker(ta_ticker)
                    df_daily = t.history(period="6mo", interval="1d")
                # تنبيه المستخدم لو entry بعيد عن السعر الحالي
                if scale_info.get("poly_price"):
                    poly_price = scale_info["poly_price"]
                    diff_from_entry = abs(entry_input - poly_price) / poly_price * 100
                    if diff_from_entry > 10:
                        await u.message.reply_text(
                            f"⚠️ *تنبيه:* السعر الحالي لـ{asset} من Polygon = "
                            f"`{poly_price:.{ASSET_POLYGON_CONFIG.get(poly_asset_key, {}).get('decimals', 5)}f}`\n"
                            f"إنت دخلت entry = `{entry_input}` "
                            f"(فرق {diff_from_entry:.1f}%)\n\n"
                            f"_ممكن تستخدم سعر قريب من السعر الحالي_",
                            parse_mode="Markdown"
                        )
            else:
                t = yf.Ticker(ta_ticker)
                df_daily = t.history(period="6mo", interval="1d")
            
            if not ta_full or df_daily is None or df_daily.empty:
                await u.message.reply_text("⚠️ تعذّر جلب البيانات الفنية")
                return
            
            risk_data = smart_risk.build_full_risk_analysis(
                entry=entry_input,
                action=action_input,
                ta=ta_full,
                df=df_daily,
                asset=asset,
                capital=capital_input,
            )
            text_out = smart_risk.format_smart_risk_advanced(risk_data)
            await send_long(u, text_out)
            
        except ValueError:
            await u.message.reply_text(
                "⚠️ خطأ في الأرقام. مثال صحيح:\n`مخاطر ذهب buy 2650`",
                parse_mode="Markdown"
            )
        except Exception as e:
            await u.message.reply_text(f"⚠️ خطأ: {e}")
        return
    
    # ═══ Help ═══
    await u.message.reply_text(
        "💡 *الأوامر الأساسية:*\n"
        "`توصية` `يومي` `تحليل` `فني`\n"
        "`حيتان` `خيارات` `بنوك` `ماكرو`\n"
        "`أخبار` `أسعار` `تقويم` `عاجل`\n"
        "`أداء` `اشترك` `سؤال [نص]`\n"
        "`مخاطر [أصل] [buy/sell] [سعر]` ← *جديد!*\n\n"
        "/start للقائمة الكاملة",
        parse_mode="Markdown")


async def error_handler(update, context):
    log.warning(f"Bot error: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text("⚠️ خطأ مؤقت")
    except: pass


# ═══════════════════════════════════════════════════════════════════════
# 20) MAIN
# ═══════════════════════════════════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود")
        return
    
    db_init()
    
    print("=" * 70)
    print("  WALL STREET PRO BOT V4.1 — UNIFIED + SMART RISK — Running ✅")
    print("=" * 70)
    print(f"  🧠 Claude:        {'✅' if CLAUDE_API_KEY else '⚪'}")
    print(f"  💎 Gemini:        {'✅' if GEMINI_API_KEY else '⚪'}")
    print(f"  🤖 OpenAI:        {'✅' if OPENAI_API_KEY else '⚪'}")
    print(f"  📊 Polygon:       {'✅' if POLYGON_API_KEY else '⚪'}")
    print(f"  💎 Options:       {'✅ مُفعّلة' if ENABLE_OPTIONS else '⚪ معطّلة (Currencies plan)'}")
    print(f"  🌍 Trading Econ:  {'✅' if TRADING_ECON_KEY else '⚪'}")
    print(f"  📈 Databento:     {'✅' if DATABENTO_API_KEY else '⚪'}")
    print(f"  🏛️  FRED:          {'✅' if FRED_API_KEY else '⚪'}")
    print(f"  🛡️  Smart Risk:    ✅ (SL + TP + Position Sizing)")
    print(f"  📰 RSS sources:   {len(RSS_FEEDS)}")
    print(f"  💹 Symbols:       {len(SYMBOLS)}")
    print(f"  💾 Database:      {DB_PATH}")
    print("=" * 70)
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_error_handler(error_handler)
    
    jq = app.job_queue
    if jq:
        jq.run_repeating(daily_briefing_callback, interval=60, first=10)
        jq.run_repeating(monitor_high_impact_news,
                         interval=NEWS_MONITOR_INTERVAL, first=120)
        # ═══ تتبع الصفقات النشطة (كل 5 دقائق) ═══
        jq.run_repeating(trade_monitor_callback, interval=300, first=180)
        # ═══ تتبع الأخبار العاجلة + AI (كل 5 دقائق) ═══
        jq.run_repeating(news_tracking_monitor, interval=300, first=240)
        print("  ⏰ Schedulers ON:")
        print("     • Daily Briefing (1m check)")
        print("     • News High-Impact Monitor")
        print("     • 📊 Trade Monitor (5m)")
        print("     • 📰 News Tracking + AI (5m)")
    
    print("=" * 70)
    
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
