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


def fetch_prices() -> Dict[str, Dict]:
    """جلب الأسعار اللحظية + cache 60 ثانية."""
    cached = cache_get("prices_all")
    if cached:
        return cached
    
    out = {}
    for name, ticker in SYMBOLS.items():
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
            }
        except Exception as e:
            log.warning(f"price [{name}]: {e}")
    
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


def polygon_fx_quote(from_curr: str = "EUR", to_curr: str = "USD") -> Optional[Dict]:
    """آخر سعر FX من Polygon."""
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
    """تحليل فني شامل."""
    cache_key = f"ta_{ticker}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        t = yf.Ticker(ticker)
        df_1d = t.history(period="6mo", interval="1d")
        df_4h = t.history(period="60d", interval="1h")  # كبديل لـ 4H
        if df_1d.empty:
            return {}
        
        closes = df_1d["Close"]
        rsi = calc_rsi(closes)
        macd, signal, hist = calc_macd(closes)
        emas = calc_emas(closes)
        bb = calc_bollinger(closes)
        atr = calc_atr(df_1d)
        bull_obs, bear_obs = find_order_blocks(df_4h if not df_4h.empty else df_1d)
        bull_fvg, bear_fvg = find_fvg(df_1d)
        structure = detect_market_structure(df_1d)
        
        last_price = float(closes.iloc[-1])
        
        # تفسير RSI
        if rsi > 70:
            rsi_signal = "🔴 ذروة شراء"
        elif rsi < 30:
            rsi_signal = "🟢 ذروة بيع"
        else:
            rsi_signal = "🟡 محايد"
        
        # تفسير MACD
        if hist > 0 and macd > signal:
            macd_signal = "🟢 Bullish"
        elif hist < 0 and macd < signal:
            macd_signal = "🔴 Bearish"
        else:
            macd_signal = "🟡 محايد"
        
        # تفسير EMAs
        if last_price > emas["ema_20"] > emas["ema_50"] > emas["ema_200"]:
            ema_trend = "🟢 صعودي قوي (كل EMAs مرتبة)"
        elif last_price < emas["ema_20"] < emas["ema_50"] < emas["ema_200"]:
            ema_trend = "🔴 هبوطي قوي (كل EMAs مرتبة)"
        else:
            ema_trend = "🟡 مختلط"
        
        # موقع السعر من BB
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

تنسيق الإجابة بدقة:

🎯 **التوصية:** [BUY / SELL / HOLD / ADD / REDUCE]
💪 **الثقة:** [قوية/متوسطة/ضعيفة] (X/10)
⏱️ **الإطار:** [قصير 1-7 أيام / متوسط 1-4 أسابيع / طويل]

📊 **التحليل (5 نقاط):**
• [نقطة فندامنتل]
• [نقطة Smart Money]
• [نقطة Yield Curve / Fed]
• [نقطة Options Sentiment]
• [نقطة فني]

🎲 **السيناريوهات:**
• Bull (X%): [الوصف + المستوى المستهدف]
• Base (X%): [الوصف + المستوى]
• Bear (X%): [الوصف + المستوى]

🛡️ **مستوى الدخول:**
• Entry: [المستوى الدقيق فقط - رقم واحد]
• المنطق: [ليه الدخول هنا]

⚠️ **العوامل الحاسمة (Catalysts المتوقعة):**
• [أحداث/أرقام قادمة قد تغيّر التوصية]

⚡ **ملاحظة مهمة:** لا تحتاج تعطي SL/TP — البوت سيحسبها تلقائياً
بمنهجية Smart Risk Management (Order Blocks + Liquidity Pools + ATR + 
Round Numbers detection). فقط ركّز على *Entry* والمنطق.

📝 **ملاحظة:** تحليل تعليمي — ليس نصيحة استثمارية.
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
📅 {datetime.now(pytz.timezone(DEFAULT_TZ)).strftime('%A %d/%m/%Y %H:%M')}

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

📅 الأحداث القادمة (7 أيام):
{cal_text}

😰 مؤشر الخوف:
  VIX: {vix:.2f} ← {fear}

📰 آخر الأخبار المؤثرة:
{news_text}
{last_rec_text}
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
                t = yf.Ticker(ta_ticker)
                df_daily = t.history(period="6mo", interval="1d")
                
                if ta_full and not df_daily.empty:
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
        "🛡️ *إدارة المخاطر الذكية* ✨ جديد:\n"
        "`مخاطر ذهب buy 2650` — تحليل مخاطر يدوي\n"
        "`مخاطر ذهب sell 2680 5000` — مع رأس مال\n"
        "  ▸ 3 مستويات SL + Danger Zones\n"
        "  ▸ 3 أهداف TP + احتمالات + Reject Zones\n"
        "  ▸ Position Sizing + Partial Close\n\n"
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
    
    # ═══ التوصيات ═══
    if text in ("توصية", "توصيه", "recommend"):
        await u.message.reply_text(
            "⏳ *جاري بناء توصية الذهب...*\n_(60 ثانية)_",
            parse_mode="Markdown")
        rec = build_recommendation(asset="Gold", chat_id=chat_id)
        for m in format_recommendation(rec):
            await send_long(u, m)
            await asyncio.sleep(0.3)
        return
    
    if text in ("توصية دولار", "توصية الدولار"):
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
    
    if text in ("خيارات", "options", "opt"):
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
            
            # Map asset
            asset_map = {
                "ذهب": "Gold", "gold": "Gold", "xauusd": "Gold",
                "دولار": "USD/DXY", "dollar": "USD/DXY", "dxy": "USD/DXY",
            }
            asset = asset_map.get(asset_input, "Gold")
            
            if action_input not in ("BUY", "SELL", "ADD"):
                await u.message.reply_text("⚠️ Action لازم يكون: BUY أو SELL أو ADD")
                return
            
            await u.message.reply_text(
                f"⏳ *Smart Risk Analysis*\n_{asset} | {action_input} @ {entry_input}_",
                parse_mode="Markdown"
            )
            
            # جلب TA + DataFrame
            ta_ticker = "GC=F" if asset == "Gold" else "DX-Y.NYB"
            ta_full = technical_analysis(ta_ticker)
            t = yf.Ticker(ta_ticker)
            df_daily = t.history(period="6mo", interval="1d")
            
            if not ta_full or df_daily.empty:
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
        print("  ⏰ Schedulers ON (briefing + monitor)")
    
    print("=" * 70)
    
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
