"""
═══════════════════════════════════════════════════════════════════════
  SMART RISK MANAGEMENT MODULE — V1.0
═══════════════════════════════════════════════════════════════════════
  ميزات إدارة المخاطر الذكية لـ WALLSTREET_PRO_BOT
  
  يوفّر:
    🛡️  Smart SL Suggester (3 مستويات + Danger Zones)
    🎯 Smart TP Suggester (3 أهداف + Reject Zones + احتمالات)
    📋 Partial Close Strategy (خطة خروج تدريجي)
    💰 Position Size Calculator (Risk-based sizing)
    📊 R:R Analysis & ASCII Charts
  
  المبدأ:
    تجنّب الأماكن الواضحة (Round Numbers, Recent Swings)
    استهدف Liquidity Pools (Equal Highs/Lows, Order Blocks)
    حافظ على R:R منطقي (≥ 1:2)
═══════════════════════════════════════════════════════════════════════
"""

from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np


# ═══════════════════════════════════════════════════════════════════════
# 1) ASSET CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════
ASSET_CONFIG = {
    "Gold": {
        "pip_value": 0.10,
        "round_levels": [10, 25, 50, 100],
        "min_distance": 5.0,
        "default_atr_mult": 1.5,
        "decimals": 2,
        "symbol": "$",
        "lot_value_per_point": 100,  # Gold: 1 lot = 100 oz
        "min_lot": 0.01,
    },
    "Silver": {
        "pip_value": 0.05,
        "round_levels": [0.50, 1.0, 2.5, 5.0],
        "min_distance": 0.30,
        "default_atr_mult": 1.5,
        "decimals": 3,
        "symbol": "$",
        "lot_value_per_point": 5000,  # Silver: 1 lot = 5000 oz
        "min_lot": 0.01,
    },
    "USD/DXY": {
        "pip_value": 1.0,
        "round_levels": [0.5, 1.0, 5.0],
        "min_distance": 0.10,
        "default_atr_mult": 1.5,
        "decimals": 3,
        "symbol": "",
        "lot_value_per_point": 1000,
        "min_lot": 0.01,
    },
    "EUR/USD": {
        "pip_value": 10.0,
        "round_levels": [0.0050, 0.0100],
        "min_distance": 0.0010,
        "default_atr_mult": 1.5,
        "decimals": 5,
        "symbol": "",
        "lot_value_per_point": 100000,  # 1 standard lot = 100k units
        "min_lot": 0.01,
    },
    "GBP/USD": {
        "pip_value": 10.0,
        "round_levels": [0.0050, 0.0100],
        "min_distance": 0.0010,
        "default_atr_mult": 1.5,
        "decimals": 5,
        "symbol": "",
        "lot_value_per_point": 100000,
        "min_lot": 0.01,
    },
    "USD/JPY": {
        "pip_value": 9.0,    # تقريبي - يعتمد على الصرف
        "round_levels": [0.50, 1.00, 5.00],
        "min_distance": 0.10,
        "default_atr_mult": 1.5,
        "decimals": 3,
        "symbol": "¥",
        "lot_value_per_point": 1000,
        "min_lot": 0.01,
    },
    "USD/CHF": {
        "pip_value": 10.0,
        "round_levels": [0.0050, 0.0100],
        "min_distance": 0.0010,
        "default_atr_mult": 1.5,
        "decimals": 5,
        "symbol": "",
        "lot_value_per_point": 100000,
        "min_lot": 0.01,
    },
    "AUD/USD": {
        "pip_value": 10.0,
        "round_levels": [0.0050, 0.0100],
        "min_distance": 0.0010,
        "default_atr_mult": 1.5,
        "decimals": 5,
        "symbol": "",
        "lot_value_per_point": 100000,
        "min_lot": 0.01,
    },
    "Oil": {
        "pip_value": 10.0,
        "round_levels": [0.50, 1.0, 5.0, 10.0],
        "min_distance": 0.30,
        "default_atr_mult": 1.5,
        "decimals": 2,
        "symbol": "$",
        "lot_value_per_point": 1000,  # WTI: 1 contract = 1000 barrels
        "min_lot": 0.01,
    },
    "default": {
        "pip_value": 1.0,
        "round_levels": [10, 50, 100],
        "min_distance": 1.0,
        "default_atr_mult": 1.5,
        "decimals": 2,
        "symbol": "",
        "lot_value_per_point": 100,
        "min_lot": 0.01,
    },
}


def _get_config(asset: str) -> Dict:
    return ASSET_CONFIG.get(asset, ASSET_CONFIG["default"])


# ═══════════════════════════════════════════════════════════════════════
# 2) STRUCTURE DETECTION (Swings, Round Numbers, Equal H/L)
# ═══════════════════════════════════════════════════════════════════════
def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> Dict[str, List[Dict]]:
    """يحدد Swing Highs و Swing Lows باستخدام Pivot Points.
    
    Returns:
        {"highs": [{"price": x, "index": i, "strength": n}, ...],
         "lows":  [{"price": x, "index": i, "strength": n}, ...]}
    """
    if df.empty or len(df) < lookback * 2 + 1:
        return {"highs": [], "lows": []}
    
    highs, lows = [], []
    n = len(df)
    
    for i in range(lookback, n - lookback):
        # Swing High: أعلى من lookback شموع قبله وبعده
        is_swing_high = all(
            df["High"].iloc[i] >= df["High"].iloc[i - j]
            and df["High"].iloc[i] >= df["High"].iloc[i + j]
            for j in range(1, lookback + 1)
        )
        if is_swing_high:
            # قوة الـSwing = كم شمعة أقل منه بشكل متتالي
            strength = lookback
            highs.append({
                "price": float(df["High"].iloc[i]),
                "index": i,
                "strength": strength,
                "bars_ago": n - 1 - i,
            })
        
        # Swing Low: أقل من lookback شموع قبله وبعده
        is_swing_low = all(
            df["Low"].iloc[i] <= df["Low"].iloc[i - j]
            and df["Low"].iloc[i] <= df["Low"].iloc[i + j]
            for j in range(1, lookback + 1)
        )
        if is_swing_low:
            strength = lookback
            lows.append({
                "price": float(df["Low"].iloc[i]),
                "index": i,
                "strength": strength,
                "bars_ago": n - 1 - i,
            })
    
    # ترتيب حسب الأحدث وأخذ آخر 5
    highs = sorted(highs, key=lambda x: x["index"], reverse=True)[:5]
    lows = sorted(lows, key=lambda x: x["index"], reverse=True)[:5]
    
    return {"highs": highs, "lows": lows}


def find_round_numbers(price: float, range_pct: float, asset: str) -> List[Dict]:
    """يحدد الأرقام المستديرة القريبة من السعر.
    
    Args:
        price: السعر الحالي
        range_pct: نطاق البحث كنسبة (مثلاً 0.03 = ±3%)
        asset: اسم الأصل
    """
    cfg = _get_config(asset)
    levels = cfg["round_levels"]
    
    range_amount = price * range_pct
    low_bound = price - range_amount
    high_bound = price + range_amount
    
    result = []
    for level_size in levels:
        # أوجد كل الأرقام المستديرة في النطاق
        start = int(low_bound / level_size) * level_size
        cur = start
        while cur <= high_bound:
            if low_bound <= cur <= high_bound and abs(cur - price) > 0.01:
                strength = (
                    "very_strong" if level_size == max(levels)
                    else "strong" if level_size == levels[-2]
                    else "medium" if len(levels) > 2 and level_size == levels[-3]
                    else "weak"
                )
                result.append({
                    "price": round(cur, cfg["decimals"]),
                    "spacing": level_size,
                    "strength": strength,
                    "side": "above" if cur > price else "below",
                })
            cur += level_size
    
    # إزالة المكررات وترتيب حسب القرب
    seen = set()
    unique = []
    for r in result:
        key = round(r["price"], cfg["decimals"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    unique.sort(key=lambda x: abs(x["price"] - price))
    return unique[:8]


def find_equal_highs_lows(
    df: pd.DataFrame,
    tolerance_pct: float = 0.0015,
    min_touches: int = 2,
) -> Dict[str, List[Dict]]:
    """يبحث عن مستويات تكررت 2+ مرات (تجمّعات Stops محتملة).
    
    Args:
        tolerance_pct: نسبة التساهل (0.0015 = 0.15% فرق مقبول)
        min_touches: الحد الأدنى للمسات
    """
    if df.empty or len(df) < 20:
        return {"equal_highs": [], "equal_lows": []}
    
    swings = find_swing_points(df, lookback=3)
    highs = swings["highs"]
    lows = swings["lows"]
    
    def cluster(points: List[Dict]) -> List[Dict]:
        if not points:
            return []
        
        # ترتيب حسب السعر
        sorted_pts = sorted(points, key=lambda x: x["price"])
        clusters = []
        current_cluster = [sorted_pts[0]]
        
        for pt in sorted_pts[1:]:
            avg_price = sum(p["price"] for p in current_cluster) / len(current_cluster)
            if abs(pt["price"] - avg_price) / avg_price <= tolerance_pct:
                current_cluster.append(pt)
            else:
                if len(current_cluster) >= min_touches:
                    clusters.append({
                        "price": sum(p["price"] for p in current_cluster) / len(current_cluster),
                        "touches": len(current_cluster),
                        "strength": min(len(current_cluster), 5),
                    })
                current_cluster = [pt]
        
        # آخر cluster
        if len(current_cluster) >= min_touches:
            clusters.append({
                "price": sum(p["price"] for p in current_cluster) / len(current_cluster),
                "touches": len(current_cluster),
                "strength": min(len(current_cluster), 5),
            })
        
        return clusters
    
    return {
        "equal_highs": cluster(highs),
        "equal_lows": cluster(lows),
    }


# ═══════════════════════════════════════════════════════════════════════
# 2.5) LIQUIDITY POOLS DETECTION — منطق الحيتان (Smart Money Logic)
# ═══════════════════════════════════════════════════════════════════════
def find_liquidity_pools(
    df: pd.DataFrame,
    asset: str = "Gold",
    lookback_swings: int = 5,
) -> Dict[str, List[Dict]]:
    """يحدد Liquidity Pools — الأماكن اللي الحيتان بتستهدفها.
    
    الفلسفة:
    ==========
    Smart Money (المؤسسات/الحيتان) بتشتغل على الـSell-side & Buy-side Liquidity:
    
    🐋 Buy-side Liquidity (BSL): فوق Swing Highs / Equal Highs
       - هنا الـShort traders بيحطوا Stop Loss (Buy Stops)
       - الحيتان بتدفع السعر لفوق علشان تـsweep هذي الـstops
       - بعد الـsweep، السعر يرجع تحت = "Stop Hunt"
    
    🐋 Sell-side Liquidity (SSL): تحت Swing Lows / Equal Lows
       - هنا الـLong traders بيحطوا Stop Loss (Sell Stops)
       - الحيتان بتـsweep هذي الـstops قبل ما تعكس
    
    استراتيجية البوت:
    ================
    1. SL: لازم يكون **بعد** الـliquidity pool (مش قبله)
       لأن الحيتان بتمسح الـliquidity وترجع
    2. TP: في اتجاه الـopposite liquidity pool
       (الحيتان بتدفع السعر لهناك)
    
    Returns:
        {
          "buy_side": [   # فوق السعر - target للـlongs
              {"price": x, "type": "Equal Highs", "strength": "very_strong",
               "touches": 3, "distance_pct": 1.2, "is_swept": False},
              ...
          ],
          "sell_side": [  # تحت السعر - target للـshorts
              ...
          ]
        }
    """
    if df.empty or len(df) < 30:
        return {"buy_side": [], "sell_side": []}
    
    cfg = _get_config(asset)
    current_price = float(df["Close"].iloc[-1])
    
    buy_side = []
    sell_side = []
    
    # ═══ المصدر 1: Equal Highs/Lows (الأقوى) ═══
    eq_data = find_equal_highs_lows(df, tolerance_pct=0.0015, min_touches=2)
    
    for eq in eq_data["equal_highs"]:
        if eq["price"] > current_price:
            distance_pct = (eq["price"] - current_price) / current_price * 100
            strength_label = (
                "very_strong" if eq["touches"] >= 3
                else "strong" if eq["touches"] == 2
                else "medium"
            )
            buy_side.append({
                "price": eq["price"],
                "type": f"Equal Highs ({eq['touches']}× touches)",
                "icon": "🎯",
                "strength": strength_label,
                "touches": eq["touches"],
                "distance_pct": round(distance_pct, 3),
                "source": "equal_highs",
                "is_swept": False,  # سيتم تحديده لاحقاً
            })
    
    for eq in eq_data["equal_lows"]:
        if eq["price"] < current_price:
            distance_pct = (current_price - eq["price"]) / current_price * 100
            strength_label = (
                "very_strong" if eq["touches"] >= 3
                else "strong" if eq["touches"] == 2
                else "medium"
            )
            sell_side.append({
                "price": eq["price"],
                "type": f"Equal Lows ({eq['touches']}× touches)",
                "icon": "🎯",
                "strength": strength_label,
                "touches": eq["touches"],
                "distance_pct": round(distance_pct, 3),
                "source": "equal_lows",
                "is_swept": False,
            })
    
    # ═══ المصدر 2: Recent Swing Highs/Lows (المهمة) ═══
    swings = find_swing_points(df, lookback=lookback_swings)
    
    # نأخذ آخر 5 swings فقط (الأقرب زمنياً = الأكثر تأثيراً)
    recent_highs = sorted(swings["highs"], key=lambda x: -x["index"])[:5]
    recent_lows = sorted(swings["lows"], key=lambda x: -x["index"])[:5]
    
    for sh in recent_highs:
        if sh["price"] > current_price:
            distance_pct = (sh["price"] - current_price) / current_price * 100
            # Strength بناءً على bars_ago — كل ما كانت أحدث، أقوى
            strength_label = (
                "very_strong" if sh["bars_ago"] < 20
                else "strong" if sh["bars_ago"] < 60
                else "medium"
            )
            buy_side.append({
                "price": round(sh["price"], cfg["decimals"]),
                "type": f"Swing High ({sh['bars_ago']} bars ago)",
                "icon": "🔝",
                "strength": strength_label,
                "bars_ago": sh["bars_ago"],
                "distance_pct": round(distance_pct, 3),
                "source": "swing_high",
                "is_swept": False,
            })
    
    for sl in recent_lows:
        if sl["price"] < current_price:
            distance_pct = (current_price - sl["price"]) / current_price * 100
            strength_label = (
                "very_strong" if sl["bars_ago"] < 20
                else "strong" if sl["bars_ago"] < 60
                else "medium"
            )
            sell_side.append({
                "price": round(sl["price"], cfg["decimals"]),
                "type": f"Swing Low ({sl['bars_ago']} bars ago)",
                "icon": "🔻",
                "strength": strength_label,
                "bars_ago": sl["bars_ago"],
                "distance_pct": round(distance_pct, 3),
                "source": "swing_low",
                "is_swept": False,
            })
    
    # ═══ المصدر 3: All-Time/Period High & Low ═══
    period_high = float(df["High"].max())
    period_low = float(df["Low"].min())
    
    if period_high > current_price:
        distance_pct = (period_high - current_price) / current_price * 100
        if distance_pct < 25:  # عقلانياً
            buy_side.append({
                "price": round(period_high, cfg["decimals"]),
                "type": "Period High (6mo)",
                "icon": "👑",
                "strength": "very_strong",
                "distance_pct": round(distance_pct, 3),
                "source": "period_high",
                "is_swept": False,
            })
    
    if period_low < current_price:
        distance_pct = (current_price - period_low) / current_price * 100
        if distance_pct < 25:
            sell_side.append({
                "price": round(period_low, cfg["decimals"]),
                "type": "Period Low (6mo)",
                "icon": "👑",
                "strength": "very_strong",
                "distance_pct": round(distance_pct, 3),
                "source": "period_low",
                "is_swept": False,
            })
    
    # ═══ تحديد الـSwept Pools (الـliquidity اللي اتمسحت) ═══
    # لو السعر اخترق pool ثم رجع = "Liquidity Sweep" حصل
    # هذا مهم لأن الـpool الـswept = ضعيف (الحيتان مسحته بالفعل)
    last_20_high = float(df["High"].iloc[-20:].max())
    last_20_low = float(df["Low"].iloc[-20:].min())
    
    for p in buy_side:
        # لو الـpool أقل من last_20_high والسعر دلوقتي تحته = اتمسح
        if p["price"] < last_20_high and current_price < p["price"]:
            # تأكد من إن السعر فعلاً اخترقه ورجع
            for i in range(max(0, len(df) - 20), len(df)):
                if df["High"].iloc[i] >= p["price"]:
                    if df["Close"].iloc[-1] < p["price"]:
                        p["is_swept"] = True
                    break
    
    for p in sell_side:
        if p["price"] > last_20_low and current_price > p["price"]:
            for i in range(max(0, len(df) - 20), len(df)):
                if df["Low"].iloc[i] <= p["price"]:
                    if df["Close"].iloc[-1] > p["price"]:
                        p["is_swept"] = True
                    break
    
    # ═══ ترتيب وإزالة المكررات ═══
    def dedupe_and_sort(pools: List[Dict]) -> List[Dict]:
        # إزالة المكررات (نفس السعر تقريباً)
        unique = []
        seen_prices = []
        for p in sorted(pools, key=lambda x: -_strength_score(x["strength"])):
            is_dup = any(
                abs(p["price"] - sp) / sp < 0.002 for sp in seen_prices
            )
            if not is_dup:
                unique.append(p)
                seen_prices.append(p["price"])
        # ترتيب حسب القرب
        unique.sort(key=lambda x: x["distance_pct"])
        return unique[:8]  # أفضل 8 fقط
    
    return {
        "buy_side": dedupe_and_sort(buy_side),
        "sell_side": dedupe_and_sort(sell_side),
    }


def _strength_score(strength: str) -> int:
    return {"very_strong": 4, "strong": 3, "medium": 2, "weak": 1}.get(strength, 0)


def find_smart_money_zones(
    df: pd.DataFrame,
    asset: str = "Gold",
) -> Dict[str, List[Dict]]:
    """يحدد Smart Money Zones — مناطق دخول/خروج المؤسسات.
    
    1. **Order Blocks (OB)**: آخر شمعة مخالفة قبل حركة قوية
       - Bullish OB: شمعة هابطة قبل ارتفاع كبير = الحيتان دخلت Long
       - Bearish OB: شمعة صاعدة قبل هبوط كبير = الحيتان دخلت Short
    
    2. **Break of Structure (BOS)**: اختراق Swing High/Low كبير
       - يدل على change of trend أو continuation
    
    3. **Mitigation Zones**: مناطق Order Blocks اللي تم إعادة اختبارها
    
    Returns:
        {
          "bullish_obs": [{"price": x, "type": "Bullish OB", ...}],
          "bearish_obs": [...],
          "recent_bos": [{"price": x, "type": "Bullish BOS", ...}],
        }
    """
    if df.empty or len(df) < 30:
        return {"bullish_obs": [], "bearish_obs": [], "recent_bos": []}
    
    cfg = _get_config(asset)
    bullish_obs = []
    bearish_obs = []
    recent_bos = []
    
    n = len(df)
    
    # ═══ Order Blocks Detection ═══
    # نبحث في آخر 60 شمعة عن OBs
    for i in range(max(0, n - 60), n - 3):
        candle_open = df["Open"].iloc[i]
        candle_close = df["Close"].iloc[i]
        candle_high = df["High"].iloc[i]
        candle_low = df["Low"].iloc[i]
        candle_range = candle_high - candle_low
        
        if candle_range == 0:
            continue
        
        # شمعة هابطة (close < open)
        is_bearish = candle_close < candle_open
        # شمعة صاعدة
        is_bullish = candle_close > candle_open
        
        # Bullish OB: شمعة هابطة، تليها 2-3 شموع صاعدة قوية
        if is_bearish and i + 3 < n:
            next_3_high = max(df["High"].iloc[i+1:i+4])
            move_up = (next_3_high - candle_high) / candle_range
            if move_up > 2.0:  # ارتفاع 2x range الشمعة
                bullish_obs.append({
                    "price": round((candle_high + candle_low) / 2, cfg["decimals"]),
                    "high": round(candle_high, cfg["decimals"]),
                    "low": round(candle_low, cfg["decimals"]),
                    "type": "Bullish OB",
                    "icon": "🟢",
                    "bars_ago": n - 1 - i,
                    "move_strength": round(move_up, 2),
                    "strength": "very_strong" if move_up > 3 else "strong",
                })
        
        # Bearish OB: شمعة صاعدة، تليها 2-3 شموع هابطة قوية
        if is_bullish and i + 3 < n:
            next_3_low = min(df["Low"].iloc[i+1:i+4])
            move_down = (candle_low - next_3_low) / candle_range
            if move_down > 2.0:
                bearish_obs.append({
                    "price": round((candle_high + candle_low) / 2, cfg["decimals"]),
                    "high": round(candle_high, cfg["decimals"]),
                    "low": round(candle_low, cfg["decimals"]),
                    "type": "Bearish OB",
                    "icon": "🔴",
                    "bars_ago": n - 1 - i,
                    "move_strength": round(move_down, 2),
                    "strength": "very_strong" if move_down > 3 else "strong",
                })
    
    # ترتيب: الأقرب والأقوى أولاً
    bullish_obs.sort(key=lambda x: (x["bars_ago"], -_strength_score(x["strength"])))
    bearish_obs.sort(key=lambda x: (x["bars_ago"], -_strength_score(x["strength"])))
    
    # ═══ Break of Structure Detection ═══
    # نشوف هل آخر 10 شموع كسرت آخر Swing High/Low
    swings = find_swing_points(df, lookback=5)
    if swings["highs"] and swings["lows"]:
        last_swing_high = max(swings["highs"], key=lambda x: x["index"]) if swings["highs"] else None
        last_swing_low = max(swings["lows"], key=lambda x: x["index"]) if swings["lows"] else None
        
        recent_close = float(df["Close"].iloc[-1])
        
        if last_swing_high and recent_close > last_swing_high["price"]:
            # Bullish BOS — اختراق صعودي
            recent_bos.append({
                "price": round(last_swing_high["price"], cfg["decimals"]),
                "type": "Bullish BOS",
                "icon": "⚡",
                "direction": "up",
                "bars_ago": last_swing_high["bars_ago"],
                "strength": "strong",
            })
        
        if last_swing_low and recent_close < last_swing_low["price"]:
            recent_bos.append({
                "price": round(last_swing_low["price"], cfg["decimals"]),
                "type": "Bearish BOS",
                "icon": "⚡",
                "direction": "down",
                "bars_ago": last_swing_low["bars_ago"],
                "strength": "strong",
            })
    
    return {
        "bullish_obs": bullish_obs[:5],
        "bearish_obs": bearish_obs[:5],
        "recent_bos": recent_bos,
    }


# ═══════════════════════════════════════════════════════════════════════
# 2.7) MULTI-TIMEFRAME CONFLUENCE — تحليل 3 إطارات زمنية
# ═══════════════════════════════════════════════════════════════════════
def analyze_timeframe_bias(df: pd.DataFrame, lookback: int = 50) -> Dict:
    """يحلل اتجاه إطار زمني واحد ويرجّع bias.
    
    Returns: {
        "bias": "BULLISH" / "BEARISH" / "NEUTRAL",
        "strength": 1-10,
        "ema_trend": str,
        "structure": str,
        "rsi": float,
        "score": int,           # bull_score - bear_score
    }
    """
    if df is None or df.empty or len(df) < 30:
        return {"bias": "UNKNOWN", "strength": 0, "score": 0,
                "ema_trend": "—", "structure": "—", "rsi": 50}
    
    closes = df["Close"]
    
    # EMA trend
    ema_20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_50 = closes.ewm(span=50, adjust=False).mean().iloc[-1]
    if len(closes) >= 200:
        ema_200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]
    else:
        ema_200 = ema_50
    
    last = float(closes.iloc[-1])
    
    bull_score = 0
    bear_score = 0
    
    # ─── 1. EMA Stack ───
    if last > ema_20 > ema_50 > ema_200:
        bull_score += 3
        ema_trend = "🟢 صعودي قوي"
    elif last > ema_20 > ema_50:
        bull_score += 2
        ema_trend = "🟢 صعودي"
    elif last < ema_20 < ema_50 < ema_200:
        bear_score += 3
        ema_trend = "🔴 هبوطي قوي"
    elif last < ema_20 < ema_50:
        bear_score += 2
        ema_trend = "🔴 هبوطي"
    elif last > ema_20:
        bull_score += 1
        ema_trend = "🟡 صعودي ضعيف"
    elif last < ema_20:
        bear_score += 1
        ema_trend = "🟡 هبوطي ضعيف"
    else:
        ema_trend = "⚪ متذبذب"
    
    # ─── 2. Market Structure (Higher Highs/Lower Lows) ───
    recent = df.iloc[-min(20, len(df)):]
    swings_high = []
    swings_low = []
    for i in range(2, len(recent) - 2):
        if (recent["High"].iloc[i] > recent["High"].iloc[i-1] 
            and recent["High"].iloc[i] > recent["High"].iloc[i+1]
            and recent["High"].iloc[i] > recent["High"].iloc[i-2]
            and recent["High"].iloc[i] > recent["High"].iloc[i+2]):
            swings_high.append(float(recent["High"].iloc[i]))
        if (recent["Low"].iloc[i] < recent["Low"].iloc[i-1]
            and recent["Low"].iloc[i] < recent["Low"].iloc[i+1]
            and recent["Low"].iloc[i] < recent["Low"].iloc[i-2]
            and recent["Low"].iloc[i] < recent["Low"].iloc[i+2]):
            swings_low.append(float(recent["Low"].iloc[i]))
    
    structure = "متذبذب"
    if len(swings_high) >= 2 and swings_high[-1] > swings_high[-2]:
        if len(swings_low) >= 2 and swings_low[-1] > swings_low[-2]:
            structure = "🟢 HH+HL (صعودي)"
            bull_score += 2
    elif len(swings_low) >= 2 and swings_low[-1] < swings_low[-2]:
        if len(swings_high) >= 2 and swings_high[-1] < swings_high[-2]:
            structure = "🔴 LH+LL (هبوطي)"
            bear_score += 2
    
    # ─── 3. RSI ───
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float('nan'))
    rsi = 100 - 100 / (1 + rs)
    rsi_now = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    
    if 50 < rsi_now < 70:
        bull_score += 1
    elif rsi_now >= 70:
        bear_score += 1  # ذروة شراء = إشارة عكس محتملة
    elif 30 < rsi_now < 50:
        bear_score += 1
    elif rsi_now <= 30:
        bull_score += 1  # ذروة بيع = إشارة عكس
    
    # ─── 4. Recent momentum (آخر 10 شموع) ───
    if len(closes) >= 10:
        change_10 = (closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100
        if change_10 > 2:
            bull_score += 1
        elif change_10 < -2:
            bear_score += 1
    
    # ─── القرار النهائي ───
    score_diff = bull_score - bear_score
    if score_diff >= 3:
        bias = "BULLISH"
        strength = min(10, 5 + score_diff)
    elif score_diff >= 1:
        bias = "WEAK_BULL"
        strength = min(8, 4 + score_diff)
    elif score_diff <= -3:
        bias = "BEARISH"
        strength = min(10, 5 + abs(score_diff))
    elif score_diff <= -1:
        bias = "WEAK_BEAR"
        strength = min(8, 4 + abs(score_diff))
    else:
        bias = "NEUTRAL"
        strength = 5
    
    return {
        "bias": bias,
        "strength": strength,
        "ema_trend": ema_trend,
        "structure": structure,
        "rsi": round(rsi_now, 1),
        "bull_score": bull_score,
        "bear_score": bear_score,
        "score": score_diff,
    }


def calculate_multi_tf_confluence(
    df_daily: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    asset: str = "Gold",
) -> Dict:
    """يحلل التوافق بين 3 إطارات زمنية.
    
    المنطق:
    - Daily: Long-term trend (الاتجاه الكبير)
    - 4H: Mid-term momentum (الزخم المتوسط)
    - 1H: Short-term timing (التوقيت الدقيق)
    
    Confluence = توافق الإطارات الثلاثة في نفس الاتجاه
    
    Returns: {
        "daily": {bias, strength, ...},
        "4h": {...},
        "1h": {...},
        "confluence_score": 0-10,
        "confluence_direction": "BULLISH"/"BEARISH"/"MIXED",
        "recommendation": str,
        "agreement_count": int,
    }
    """
    daily_analysis = analyze_timeframe_bias(df_daily)
    h4_analysis = analyze_timeframe_bias(df_4h)
    h1_analysis = analyze_timeframe_bias(df_1h)
    
    biases = [daily_analysis["bias"], h4_analysis["bias"], h1_analysis["bias"]]
    
    # تصنيف bullish/bearish
    bullish_tfs = sum(1 for b in biases if "BULL" in b)
    bearish_tfs = sum(1 for b in biases if "BEAR" in b)
    
    # توافق
    if bullish_tfs == 3:
        direction = "STRONG_BULLISH"
        confluence = 10
        agreement = 3
        rec = (
            "✅ *كل الإطارات صعودية — Strong Confluence!*\n"
            "هذي الفرصة المثالية للـlong:\n"
            "• Daily صعودي (الاتجاه الكبير)\n"
            "• 4H صعودي (الزخم)\n"
            "• 1H صعودي (التوقيت)\n\n"
            "💡 BUY عند أي pullback لـSmart Money zones"
        )
    elif bearish_tfs == 3:
        direction = "STRONG_BEARISH"
        confluence = 10
        agreement = 3
        rec = (
            "✅ *كل الإطارات هبوطية — Strong Confluence!*\n"
            "هذي الفرصة المثالية للـshort:\n"
            "• Daily هبوطي\n"
            "• 4H هبوطي\n"
            "• 1H هبوطي\n\n"
            "💡 SELL عند أي rally لـResistance/OB"
        )
    elif bullish_tfs == 2:
        direction = "BULLISH"
        confluence = 7
        agreement = 2
        rec = (
            "🟢 *إطاران صعوديان — Confluence جيد*\n"
            "فرصة شراء لكن بحذر:\n"
            "• تأكد إن الإطار اللي عكس مش هو Daily\n"
            "• Position size أصغر (0.5x من الطبيعي)"
        )
    elif bearish_tfs == 2:
        direction = "BEARISH"
        confluence = 7
        agreement = 2
        rec = (
            "🔴 *إطاران هبوطيان — Confluence جيد*\n"
            "فرصة بيع لكن بحذر:\n"
            "• تأكد إن الإطار اللي عكس مش هو Daily\n"
            "• Position size أصغر"
        )
    elif bullish_tfs == 1 and bearish_tfs == 1:
        direction = "MIXED"
        confluence = 3
        agreement = 0
        rec = (
            "⚠️ *إشارات متضاربة — تجنّب الدخول!*\n"
            "Multi-TF غير متفقة:\n"
            "• إطار صعودي + إطار هبوطي + إطار محايد\n"
            "• *الانتظار أفضل* حتى يحصل توافق\n\n"
            "💡 لو لازم تتداول، قلّل الـrisk لـ0.5%"
        )
    else:  # كلها neutral
        direction = "NEUTRAL"
        confluence = 5
        agreement = 0
        rec = (
            "⚪ *كل الإطارات محايدة*\n"
            "السوق في consolidation:\n"
            "• انتظر اختراق واضح\n"
            "• راقب الـliquidity pools\n"
            "• استعد للحركة بعد الـbreakout"
        )
    
    # تحقق من Daily override
    # Daily هو الأهم - لو معاكس للاتنين الباقيين، Confluence ضعيف
    daily_bias = daily_analysis["bias"]
    if "BULL" in daily_bias and bearish_tfs == 2:
        confluence = min(confluence, 4)
        direction = "DAILY_BULL_CORRECTION"
        rec = (
            "⚠️ *Daily صعودي لكن 4H+1H هبوطيان*\n"
            "هذا تصحيح في اتجاه صعودي:\n"
            "• تجنّب الـSHORT (ضد الاتجاه الأكبر)\n"
            "• انتظر pullback لـsmart money zones\n"
            "• استعد للـLONG عند نهاية التصحيح"
        )
    elif "BEAR" in daily_bias and bullish_tfs == 2:
        confluence = min(confluence, 4)
        direction = "DAILY_BEAR_CORRECTION"
        rec = (
            "⚠️ *Daily هبوطي لكن 4H+1H صعوديان*\n"
            "هذا rally في هبوط:\n"
            "• تجنّب الـLONG (ضد الاتجاه الأكبر)\n"
            "• انتظر تأكيد الانعكاس\n"
            "• استعد للـSHORT عند نهاية الـrally"
        )
    
    return {
        "daily": daily_analysis,
        "h4": h4_analysis,
        "h1": h1_analysis,
        "confluence_score": confluence,
        "confluence_direction": direction,
        "recommendation": rec,
        "agreement_count": agreement,
        "bullish_tfs": bullish_tfs,
        "bearish_tfs": bearish_tfs,
    }


def format_multi_tf_analysis(mtf: Dict, asset: str = "Gold") -> str:
    """تنسيق نتائج Multi-TF للعرض."""
    if not mtf:
        return "⚠️ تعذّر تحليل Multi-TF"
    
    daily = mtf["daily"]
    h4 = mtf["h4"]
    h1 = mtf["h1"]
    confluence = mtf["confluence_score"]
    
    # Bias icon
    bias_icon = {
        "BULLISH": "🟢", "STRONG_BULLISH": "🟢⚡",
        "WEAK_BULL": "🟢",
        "BEARISH": "🔴", "STRONG_BEARISH": "🔴⚡",
        "WEAK_BEAR": "🔴",
        "NEUTRAL": "⚪",
        "UNKNOWN": "❓",
    }
    
    out = []
    out.append("🎯 *MULTI-TIMEFRAME CONFLUENCE*")
    out.append("═" * 33)
    out.append(f"📊 *{asset}*")
    out.append("")
    
    # ─── Daily ───
    out.append(f"📅 *Daily (الاتجاه الكبير):*")
    out.append(f"   {bias_icon.get(daily['bias'], '❓')} {daily['bias']} (قوة: {daily['strength']}/10)")
    out.append(f"   📈 EMA: {daily['ema_trend']}")
    out.append(f"   🏗 Structure: {daily['structure']}")
    out.append(f"   📊 RSI: {daily['rsi']}")
    out.append("")
    
    # ─── 4H ───
    out.append(f"🕓 *4H (الزخم):*")
    out.append(f"   {bias_icon.get(h4['bias'], '❓')} {h4['bias']} (قوة: {h4['strength']}/10)")
    out.append(f"   📈 EMA: {h4['ema_trend']}")
    out.append(f"   📊 RSI: {h4['rsi']}")
    out.append("")
    
    # ─── 1H ───
    out.append(f"🕐 *1H (التوقيت):*")
    out.append(f"   {bias_icon.get(h1['bias'], '❓')} {h1['bias']} (قوة: {h1['strength']}/10)")
    out.append(f"   📈 EMA: {h1['ema_trend']}")
    out.append(f"   📊 RSI: {h1['rsi']}")
    out.append("")
    
    # ─── Confluence Score ───
    out.append("─" * 33)
    score_bar = "█" * confluence + "░" * (10 - confluence)
    out.append(f"🎯 *Confluence Score: {confluence}/10*")
    out.append(f"   `{score_bar}`")
    
    # تقييم
    if confluence >= 9:
        rating = "🌟🌟🌟🌟🌟 توافق ممتاز"
    elif confluence >= 7:
        rating = "🌟🌟🌟🌟 توافق جيد"
    elif confluence >= 5:
        rating = "🌟🌟🌟 توافق متوسط"
    elif confluence >= 3:
        rating = "🌟🌟 توافق ضعيف"
    else:
        rating = "🌟 لا توافق"
    out.append(f"   {rating}")
    out.append("")
    
    # ─── التوصية ───
    out.append("─" * 33)
    out.append("💡 *التوصية:*")
    out.append(mtf["recommendation"])
    out.append("")
    
    out.append("⚠️ _تحليل تعليمي — ليس نصيحة استثمارية_")
    
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════════
# 3) LIQUIDITY MAP — كل المستويات في مكان واحد
# ═══════════════════════════════════════════════════════════════════════
def build_liquidity_map(
    price: float,
    df: pd.DataFrame,
    ta: Dict,
    asset: str,
    range_pct: float = 0.05,
) -> Dict:
    """يبني خريطة شاملة لكل مستويات السيولة حول السعر.
    
    Returns:
        {
          "above": [{level, type, strength, distance_pct}, ...],
          "below": [{...}, ...],
        }
    """
    levels_above = []
    levels_below = []
    
    # 1. Order Blocks
    for ob in ta.get("order_blocks", {}).get("bullish", []):
        lvl = ob["level"]
        if lvl < price:
            levels_below.append({
                "price": lvl,
                "type": "Bullish OB",
                "icon": "🟢",
                "strength": "strong",
                "distance_pct": (price - lvl) / price * 100,
            })
        else:
            levels_above.append({
                "price": lvl,
                "type": "Bullish OB",
                "icon": "🟢",
                "strength": "strong",
                "distance_pct": (lvl - price) / price * 100,
            })
    
    for ob in ta.get("order_blocks", {}).get("bearish", []):
        lvl = ob["level"]
        if lvl > price:
            levels_above.append({
                "price": lvl,
                "type": "Bearish OB",
                "icon": "🔴",
                "strength": "strong",
                "distance_pct": (lvl - price) / price * 100,
            })
        else:
            levels_below.append({
                "price": lvl,
                "type": "Bearish OB",
                "icon": "🔴",
                "strength": "strong",
                "distance_pct": (price - lvl) / price * 100,
            })
    
    # 2. FVG (Fair Value Gaps)
    for fvg in ta.get("fvg", {}).get("bullish", []):
        mid = (fvg["gap_top"] + fvg["gap_bottom"]) / 2
        if mid > price:
            levels_above.append({
                "price": mid,
                "type": "Bullish FVG",
                "icon": "🟦",
                "strength": "medium",
                "distance_pct": (mid - price) / price * 100,
            })
    
    for fvg in ta.get("fvg", {}).get("bearish", []):
        mid = (fvg["gap_top"] + fvg["gap_bottom"]) / 2
        if mid < price:
            levels_below.append({
                "price": mid,
                "type": "Bearish FVG",
                "icon": "🟧",
                "strength": "medium",
                "distance_pct": (price - mid) / price * 100,
            })
    
    # 3. Swing Points
    if df is not None and not df.empty:
        swings = find_swing_points(df, lookback=5)
        for s in swings["highs"][:3]:
            if s["price"] > price:
                levels_above.append({
                    "price": s["price"],
                    "type": "Swing High",
                    "icon": "🔺",
                    "strength": "strong",
                    "distance_pct": (s["price"] - price) / price * 100,
                })
        for s in swings["lows"][:3]:
            if s["price"] < price:
                levels_below.append({
                    "price": s["price"],
                    "type": "Swing Low",
                    "icon": "🔻",
                    "strength": "strong",
                    "distance_pct": (price - s["price"]) / price * 100,
                })
        
        # 4. Equal Highs/Lows (Liquidity Clusters)
        eq = find_equal_highs_lows(df)
        for h in eq["equal_highs"]:
            if h["price"] > price:
                levels_above.append({
                    "price": h["price"],
                    "type": f"Equal Highs ×{h['touches']}",
                    "icon": "🐋",
                    "strength": "very_strong",
                    "distance_pct": (h["price"] - price) / price * 100,
                })
        for l in eq["equal_lows"]:
            if l["price"] < price:
                levels_below.append({
                    "price": l["price"],
                    "type": f"Equal Lows ×{l['touches']}",
                    "icon": "🐋",
                    "strength": "very_strong",
                    "distance_pct": (price - l["price"]) / price * 100,
                })
    
    # 5. Round Numbers
    rounds = find_round_numbers(price, range_pct, asset)
    for r in rounds:
        item = {
            "price": r["price"],
            "type": f"Round (${r['spacing']})",
            "icon": "⭕",
            "strength": r["strength"],
            "distance_pct": abs(r["price"] - price) / price * 100,
        }
        if r["side"] == "above":
            levels_above.append(item)
        else:
            levels_below.append(item)
    
    # 6. Bollinger Bands
    if ta.get("bb_upper") and ta["bb_upper"] > price:
        levels_above.append({
            "price": ta["bb_upper"],
            "type": "BB Upper",
            "icon": "📊",
            "strength": "medium",
            "distance_pct": (ta["bb_upper"] - price) / price * 100,
        })
    if ta.get("bb_lower") and ta["bb_lower"] < price:
        levels_below.append({
            "price": ta["bb_lower"],
            "type": "BB Lower",
            "icon": "📊",
            "strength": "medium",
            "distance_pct": (price - ta["bb_lower"]) / price * 100,
        })
    
    # 7. ⭐ Liquidity Pools (الحيتان) - الأقوى
    liq_pools = find_liquidity_pools(df, asset)
    
    # Buy-side liquidity (فوق السعر) = هدف للـlongs
    for pool in liq_pools["buy_side"]:
        if pool.get("is_swept"):
            continue  # نتخطى الـpools اللي اتمسحت
        levels_above.append({
            "price": pool["price"],
            "type": f"💰 BSL: {pool['type']}",
            "icon": pool["icon"],
            "strength": pool["strength"],
            "distance_pct": pool["distance_pct"],
            "is_liquidity_pool": True,
            "pool_source": pool.get("source"),
        })
    
    # Sell-side liquidity (تحت السعر) = هدف للـshorts
    for pool in liq_pools["sell_side"]:
        if pool.get("is_swept"):
            continue
        levels_below.append({
            "price": pool["price"],
            "type": f"💰 SSL: {pool['type']}",
            "icon": pool["icon"],
            "strength": pool["strength"],
            "distance_pct": pool["distance_pct"],
            "is_liquidity_pool": True,
            "pool_source": pool.get("source"),
        })
    
    # 8. ⭐ Smart Money Zones (Order Blocks المحسّنة + BOS)
    sm_zones = find_smart_money_zones(df, asset)
    
    for ob in sm_zones["bullish_obs"][:3]:
        if ob["price"] < price:
            levels_below.append({
                "price": ob["price"],
                "type": f"🐋 {ob['type']} ({ob['bars_ago']}b ago)",
                "icon": ob["icon"],
                "strength": ob["strength"],
                "distance_pct": (price - ob["price"]) / price * 100,
                "is_smart_money_zone": True,
                "ob_high": ob["high"],
                "ob_low": ob["low"],
            })
        else:
            levels_above.append({
                "price": ob["price"],
                "type": f"🐋 {ob['type']} ({ob['bars_ago']}b ago)",
                "icon": ob["icon"],
                "strength": ob["strength"],
                "distance_pct": (ob["price"] - price) / price * 100,
                "is_smart_money_zone": True,
            })
    
    for ob in sm_zones["bearish_obs"][:3]:
        if ob["price"] > price:
            levels_above.append({
                "price": ob["price"],
                "type": f"🐋 {ob['type']} ({ob['bars_ago']}b ago)",
                "icon": ob["icon"],
                "strength": ob["strength"],
                "distance_pct": (ob["price"] - price) / price * 100,
                "is_smart_money_zone": True,
                "ob_high": ob["high"],
                "ob_low": ob["low"],
            })
        else:
            levels_below.append({
                "price": ob["price"],
                "type": f"🐋 {ob['type']} ({ob['bars_ago']}b ago)",
                "icon": ob["icon"],
                "strength": ob["strength"],
                "distance_pct": (price - ob["price"]) / price * 100,
                "is_smart_money_zone": True,
            })
    
    # ترتيب حسب القرب من السعر
    levels_above.sort(key=lambda x: x["distance_pct"])
    levels_below.sort(key=lambda x: x["distance_pct"])
    
    return {
        "above": levels_above[:12],
        "below": levels_below[:12],
        "current_price": price,
        "liquidity_pools": liq_pools,
        "smart_money_zones": sm_zones,
    }


# ═══════════════════════════════════════════════════════════════════════
# 4) SMART STOP LOSS CALCULATOR
# ═══════════════════════════════════════════════════════════════════════
def calculate_smart_sl(
    entry: float,
    action: str,
    ta: Dict,
    df: pd.DataFrame,
    liq_map: Dict,
    asset: str,
) -> Dict:
    """يحسب 3 مستويات SL ذكية + Danger Zones.
    
    Returns:
        {
          "conservative": {"price": x, "distance": y, "distance_pct": z, "logic": [...]},
          "balanced":     {...},
          "aggressive":   {...},
          "danger_zones": [{"price", "type", "reason"}, ...],
          "recommended":  "balanced",
        }
    """
    cfg = _get_config(asset)
    atr = ta.get("atr", entry * 0.005)  # fallback 0.5%
    is_buy = action.upper() in ("BUY", "ADD")
    
    # ─── المرجع: المستويات في الاتجاه المعاكس للصفقة ───
    reference_levels = liq_map["below"] if is_buy else liq_map["above"]
    
    # ⭐ Liquidity Pools (الحيتان) في الاتجاه المعاكس
    liq_pools = liq_map.get("liquidity_pools", {})
    if is_buy:
        opposite_pools = liq_pools.get("sell_side", [])  # SSL تحت السعر
    else:
        opposite_pools = liq_pools.get("buy_side", [])   # BSL فوق السعر
    
    # نأخذ الـpools اللي مش متمسحة (الحيتان لسه ممكن تستهدفها)
    active_pools = [p for p in opposite_pools if not p.get("is_swept", False)]
    
    # ═══ Conservative SL (الأكثر أماناً) ═══
    # المنطق: SL **خلف** أقوى Liquidity Pool
    # عشان لو الحيتان مسحت الـpool، ما يضربش الـSL بتاعنا
    cons_sl = None
    cons_logic = []
    max_distance_cons = atr * 5  # حد أقصى أوسع للـconservative
    
    # نبحث في active_pools عن الأقوى والأقرب
    strong_pools = [
        p for p in active_pools
        if p["strength"] in ("very_strong", "strong")
        and abs(p["price"] - entry) <= max_distance_cons
    ]
    strong_pools.sort(key=lambda x: abs(x["price"] - entry))
    
    if strong_pools:
        target_pool = strong_pools[0]
        # buffer أكبر للـConservative (atr × 0.7) عشان يكون **بعد** الـpool
        buffer = atr * 0.7
        if is_buy:
            cons_sl = target_pool["price"] - buffer
            cons_logic.append(f"🐋 خلف {target_pool['type']} @ {target_pool['price']:.{cfg['decimals']}f}")
            cons_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.7)")
            cons_logic.append("✓ مكان حماية من Stop Hunting")
        else:
            cons_sl = target_pool["price"] + buffer
            cons_logic.append(f"🐋 خلف {target_pool['type']} @ {target_pool['price']:.{cfg['decimals']}f}")
            cons_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.7)")
            cons_logic.append("✓ مكان حماية من Stop Hunting")
    
    # Fallback 1: Order Block قوي
    if cons_sl is None:
        ob_candidates = [
            l for l in reference_levels
            if l["strength"] in ("strong", "very_strong")
            and "OB" in l["type"]
            and abs(l["price"] - entry) <= max_distance_cons
        ]
        ob_candidates.sort(key=lambda x: abs(x["price"] - entry))
        
        for lvl in ob_candidates:
            buffer = atr * 0.5
            if is_buy:
                candidate = lvl["price"] - buffer
                if candidate < entry:
                    cons_sl = candidate
                    cons_logic.append(f"ورا {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
                    cons_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.5)")
                    break
            else:
                candidate = lvl["price"] + buffer
                if candidate > entry:
                    cons_sl = candidate
                    cons_logic.append(f"ورا {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
                    cons_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.5)")
                    break
    
    # Fallback 2: ATR × 2.5
    if cons_sl is None:
        mult = 2.5
        cons_sl = entry - atr * mult if is_buy else entry + atr * mult
        cons_logic.append(f"ATR × {mult} (لا يوجد Liquidity Pool قريب)")
    
    # ═══ Balanced SL (متوازن) - بعد أقرب Swing/Pool ═══
    # المنطق: SL خلف أقرب Liquidity Pool متوسط القوة
    bal_sl = None
    bal_logic = []
    max_distance = atr * 3
    
    # نأخذ medium-strength pools كأولوية
    medium_pools = [
        p for p in active_pools
        if p["strength"] in ("strong", "medium")
        and abs(p["price"] - entry) <= max_distance
    ]
    medium_pools.sort(key=lambda x: abs(x["price"] - entry))
    
    if medium_pools:
        target = medium_pools[0]
        buffer = atr * 0.4
        if is_buy:
            candidate = target["price"] - buffer
            if candidate < entry and (cons_sl is None or candidate > cons_sl - atr * 0.3):
                bal_sl = candidate
                bal_logic.append(f"💰 خلف {target['type']} @ {target['price']:.{cfg['decimals']}f}")
                bal_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.4)")
        else:
            candidate = target["price"] + buffer
            if candidate > entry and (cons_sl is None or candidate < cons_sl + atr * 0.3):
                bal_sl = candidate
                bal_logic.append(f"💰 خلف {target['type']} @ {target['price']:.{cfg['decimals']}f}")
                bal_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.4)")
    
    # Fallback: Swing point
    if bal_sl is None:
        swing_candidates = [
            l for l in reference_levels
            if "Swing" in l["type"] and abs(l["price"] - entry) <= max_distance
        ]
        swing_candidates.sort(key=lambda x: abs(x["price"] - entry))
        
        for lvl in swing_candidates:
            buffer = atr * 0.3
            if is_buy:
                candidate = lvl["price"] - buffer
                if candidate < entry and (cons_sl is None or candidate > cons_sl - atr * 0.5):
                    bal_sl = candidate
                    bal_logic.append(f"ورا {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
                    bal_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.3)")
                    break
            else:
                candidate = lvl["price"] + buffer
                if candidate > entry and (cons_sl is None or candidate < cons_sl + atr * 0.5):
                    bal_sl = candidate
                    bal_logic.append(f"ورا {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
                    bal_logic.append(f"Buffer: {buffer:.{cfg['decimals']}f} (ATR × 0.3)")
                    break
    
    # Fallback: ATR × 1.5
    if bal_sl is None:
        mult = 1.5
        bal_sl = entry - atr * mult if is_buy else entry + atr * mult
        bal_logic.append(f"ATR × {mult} (لا يوجد Swing قريب)")
    
    # ═══ Aggressive SL (ضيّق) ═══
    agg_mult = cfg["default_atr_mult"] * 0.6  # ~0.9
    agg_sl = entry - atr * agg_mult if is_buy else entry + atr * agg_mult
    agg_logic = [f"ATR × {agg_mult:.1f} (سريع وضيّق)", "⚠️ خطر الخروج المبكر"]
    
    # ─── تحقّق من Danger Zones للـAggressive ───
    danger_warning = []
    for lvl in reference_levels[:5]:
        if abs(lvl["price"] - agg_sl) / agg_sl < 0.003:  # ≤0.3% فرق
            danger_warning.append(f"⚠️ قريب من {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
    
    # ═══ Danger Zones (مناطق ممنوع SL فيها) ═══
    danger_zones = []
    for lvl in reference_levels[:6]:
        if lvl["strength"] in ("very_strong", "strong"):
            reason = "تجمّع stops متوقع" if "Equal" in lvl["type"] or "Round" in lvl["type"] else "Liquidity Pool"
            danger_zones.append({
                "price": lvl["price"],
                "type": lvl["type"],
                "icon": lvl["icon"],
                "reason": reason,
            })
    
    # ─── حساب المسافات والنسب ───
    def make_sl_dict(sl: float, logic: List[str]) -> Dict:
        distance = abs(entry - sl)
        return {
            "price": round(sl, cfg["decimals"]),
            "distance": round(distance, cfg["decimals"]),
            "distance_pct": round(distance / entry * 100, 3),
            "logic": logic,
        }
    
    cons_dict = make_sl_dict(cons_sl, cons_logic)
    bal_dict = make_sl_dict(bal_sl, bal_logic)
    agg_dict = make_sl_dict(agg_sl, agg_logic + danger_warning)
    
    # ─── Recommended ───
    # عادةً Balanced هو الأفضل، إلا لو ATR عالي جداً (تقلب) → Conservative
    vix_high = ta.get("atr", 0) > entry * 0.02  # ATR > 2%
    recommended = "conservative" if vix_high else "balanced"
    
    return {
        "conservative": cons_dict,
        "balanced": bal_dict,
        "aggressive": agg_dict,
        "danger_zones": danger_zones[:5],
        "recommended": recommended,
        "atr": atr,
    }


# ═══════════════════════════════════════════════════════════════════════
# 5) SMART TAKE PROFIT CALCULATOR
# ═══════════════════════════════════════════════════════════════════════
def calculate_smart_tp(
    entry: float,
    sl: float,
    action: str,
    ta: Dict,
    df: pd.DataFrame,
    liq_map: Dict,
    asset: str,
) -> Dict:
    """يحسب 3 مستويات TP + احتمالات الوصول + Reject Zones."""
    cfg = _get_config(asset)
    is_buy = action.upper() in ("BUY", "ADD")
    risk = abs(entry - sl)
    
    # المستويات في اتجاه الصفقة
    target_levels = liq_map["above"] if is_buy else liq_map["below"]
    
    # ⭐ Liquidity Pools في اتجاه الصفقة (الحيتان بتدفع السعر هناك)
    liq_pools = liq_map.get("liquidity_pools", {})
    if is_buy:
        target_pools = liq_pools.get("buy_side", [])  # BSL فوق
    else:
        target_pools = liq_pools.get("sell_side", [])  # SSL تحت
    
    # نأخذ الـpools الـactive (مش متمسحة) — الحيتان لسه ممكن تستهدفها
    active_target_pools = [p for p in target_pools if not p.get("is_swept", False)]
    
    # ═══ TP1: Conservative (سريع - أقرب liquidity pool) ═══
    tp1 = None
    tp1_logic = []
    
    # أولاً: نشوف هل في liquidity pool قريب (1-3% بعيد)
    nearby_pools = [
        p for p in active_target_pools
        if 0.5 < p["distance_pct"] < 3.0
        and p["strength"] in ("strong", "very_strong")
    ]
    
    if nearby_pools:
        target = nearby_pools[0]
        # TP **قبل** الـpool عشان يخش قبل الـsweep
        # نتحقق إن الـTP في الاتجاه الصحيح من الـentry
        tp1_candidate = target["price"] * 0.998 if is_buy else target["price"] * 1.002
        if (is_buy and tp1_candidate > entry) or (not is_buy and tp1_candidate < entry):
            tp1 = tp1_candidate
            tp1_logic.append(f"💰 قبل {target['type']} @ {target['price']:.{cfg['decimals']}f}")
            tp1_logic.append("✓ هدف Smart Money — اقفل قبل الـsweep")
    
    # Fallback 1: أقرب Swing/OB في الاتجاه الصحيح
    if tp1 is None:
        for lvl in target_levels:
            if lvl["distance_pct"] < 1.5 and lvl["strength"] in ("strong", "very_strong"):
                tp1_candidate = lvl["price"] * 0.998 if is_buy else lvl["price"] * 1.002
                # تحقق إن الـTP فوق الـentry للـbuy وتحت للـsell
                if (is_buy and tp1_candidate > entry) or (not is_buy and tp1_candidate < entry):
                    tp1 = tp1_candidate
                    tp1_logic.append(f"قبل {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
                    break
    
    # Fallback 2: 1.5× ATR (دائماً في الاتجاه الصحيح)
    if tp1 is None:
        atr = ta.get("atr", entry * 0.005)
        tp1 = entry + atr * 1.5 if is_buy else entry - atr * 1.5
        tp1_logic.append("1.5 × ATR (fallback)")
    
    # ═══ TP2: Balanced (Liquidity Pool أبعد - الهدف الرئيسي) ═══
    # المنطق: الحيتان بتدفع السعر لـliquidity pool أكبر
    # ده هدف الصفقة الفعلي
    tp2 = None
    tp2_logic = []
    
    # نأخذ very_strong pools في نطاق 3-8%
    target_pools_mid = [
        p for p in active_target_pools
        if 2.0 < p["distance_pct"] < 8.0
        and p["strength"] == "very_strong"
    ]
    
    if target_pools_mid:
        target = target_pools_mid[0]
        tp2_candidate = target["price"] * 0.998 if is_buy else target["price"] * 1.002
        if (is_buy and tp2_candidate > entry) or (not is_buy and tp2_candidate < entry):
            tp2 = tp2_candidate
            tp2_logic.append(f"🎯 عند {target['type']}")
            tp2_logic.append(f"💰 BSL/SSL Cluster @ {target['price']:.{cfg['decimals']}f}")
            tp2_logic.append("✓ المكان اللي الحيتان بتدفع السعر له")
    
    # Fallback 1: Equal Highs/Lows أو Round Number قوي (في الاتجاه الصحيح)
    if tp2 is None:
        for lvl in target_levels:
            if (
                ("Equal" in lvl["type"] or "Round" in lvl["type"] or "Period" in lvl["type"])
                and lvl["strength"] == "very_strong"
                and lvl["distance_pct"] > 0.8
            ):
                # تحقق من الاتجاه
                if (is_buy and lvl["price"] > entry) or (not is_buy and lvl["price"] < entry):
                    tp2 = lvl["price"]
                    tp2_logic.append(f"عند {lvl['type']} (تجمّع stops) @ {lvl['price']:.{cfg['decimals']}f}")
                    break
    
    # Fallback 2: أبعد strong level
    if tp2 is None:
        strong_levels = [
            l for l in target_levels
            if l["strength"] in ("strong", "very_strong")
            and ((is_buy and l["price"] > entry) or (not is_buy and l["price"] < entry))
        ]
        if len(strong_levels) >= 2:
            tp2 = strong_levels[1]["price"]
            tp2_logic.append(f"عند {strong_levels[1]['type']} @ {strong_levels[1]['price']:.{cfg['decimals']}f}")
        else:
            tp2 = entry + risk * 2.5 if is_buy else entry - risk * 2.5
            tp2_logic.append("R:R = 1:2.5 (محسوب)")
    
    # ═══ TP3: Extended (Period High/Low أو Major BSL/SSL) ═══
    tp3 = None
    tp3_logic = []
    
    # نطاق TP3: لا يتعدى 5× R
    max_tp3 = entry + risk * 5 if is_buy else entry - risk * 5
    
    # نبحث عن أبعد liquidity pool ضخم في النطاق
    far_pools = [
        p for p in active_target_pools
        if p["strength"] == "very_strong"
        and ((is_buy and entry < p["price"] <= max_tp3 and p["price"] > tp2)
             or (not is_buy and max_tp3 <= p["price"] < entry and p["price"] < tp2))
    ]
    
    if far_pools:
        # Period High/Low أولاً (الأكثر liquidity)
        period_pools = [p for p in far_pools if "Period" in p.get("type", "")]
        target = period_pools[0] if period_pools else far_pools[-1]
        tp3 = target["price"]
        tp3_logic.append(f"🐋 {target['type']} @ {target['price']:.{cfg['decimals']}f}")
        tp3_logic.append("✓ هدف ممتد - liquidity pool ضخم")
    
    # Fallback: أي very_strong level في النطاق
    if tp3 is None:
        for lvl in target_levels:
            if lvl["strength"] == "very_strong":
                in_range = (
                    (is_buy and entry < lvl["price"] <= max_tp3 and lvl["price"] > tp2)
                    or (not is_buy and max_tp3 <= lvl["price"] < entry and lvl["price"] < tp2)
                )
                if in_range:
                    tp3 = lvl["price"]
                    tp3_logic.append(f"عند {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
                    break
    
    # Fallback: 3× R
    if tp3 is None:
        tp3 = entry + risk * 3 if is_buy else entry - risk * 3
        tp3_logic.append("R:R = 1:3 (هدف ممتد محسوب)")
    
    # ═══ تأكد من ترتيب TPs منطقياً ═══
    if is_buy:
        tps = sorted([tp1, tp2, tp3])
    else:
        tps = sorted([tp1, tp2, tp3], reverse=True)
    tp1, tp2, tp3 = tps[0], tps[1], tps[2]
    
    # ─── حساب احتمالات الوصول (heuristic) ───
    def calc_probability(tp_price: float, tp_idx: int) -> int:
        """
        احتمال الوصول بناءً على:
        - المسافة بالـATR (أقرب = احتمال أعلى)
        - قوة الـTrend (Bullish/Bearish)
        - وجود Reject Zones في الطريق
        """
        atr = ta.get("atr", entry * 0.005)
        distance_atr = abs(tp_price - entry) / atr
        
        # احتمال أساسي
        base_prob = max(20, 85 - distance_atr * 8)
        
        # تعديل حسب Trend
        ema_trend = ta.get("ema_trend", "")
        if (is_buy and "صعودي" in ema_trend) or (not is_buy and "هبوطي" in ema_trend):
            base_prob += 8
        
        # تعديل حسب RSI
        rsi = ta.get("rsi", 50)
        if is_buy and rsi < 40:
            base_prob += 5
        elif not is_buy and rsi > 60:
            base_prob += 5
        
        # تعديل حسب MACD
        macd_sig = ta.get("macd_signal", "")
        if (is_buy and "Bullish" in macd_sig) or (not is_buy and "Bearish" in macd_sig):
            base_prob += 5
        
        return int(min(85, max(15, base_prob)))
    
    tp1_prob = calc_probability(tp1, 1)
    tp2_prob = calc_probability(tp2, 2)
    tp3_prob = calc_probability(tp3, 3)
    
    # ─── Reject Zones (مناطق مقاومة في الطريق) ───
    reject_zones = []
    for lvl in target_levels:
        # المستويات اللي في طريقنا للأهداف
        in_path = False
        if is_buy:
            in_path = entry < lvl["price"] < tp3
        else:
            in_path = tp3 < lvl["price"] < entry
        
        # مستويات معاكسة قوية فقط
        if in_path and lvl["type"] in ("Bearish OB", "Bullish OB", "Bearish FVG", "Bullish FVG"):
            opposite = (is_buy and "Bearish" in lvl["type"]) or (not is_buy and "Bullish" in lvl["type"])
            if opposite:
                reject_zones.append({
                    "price": lvl["price"],
                    "type": lvl["type"],
                    "icon": lvl["icon"],
                    "warning": "قد يرفض السعر هنا",
                })
    
    # ─── حساب R:R لكل TP ───
    def rr(tp: float) -> float:
        if risk == 0:
            return 0
        reward = abs(tp - entry)
        return round(reward / risk, 2)
    
    def make_tp_dict(tp: float, prob: int, logic: List[str], close_pct: int) -> Dict:
        distance = abs(tp - entry)
        return {
            "price": round(tp, cfg["decimals"]),
            "distance": round(distance, cfg["decimals"]),
            "distance_pct": round(distance / entry * 100, 3),
            "probability": prob,
            "rr": rr(tp),
            "close_pct": close_pct,
            "logic": logic,
        }
    
    return {
        "tp1": make_tp_dict(tp1, tp1_prob, tp1_logic, 50),
        "tp2": make_tp_dict(tp2, tp2_prob, tp2_logic, 30),
        "tp3": make_tp_dict(tp3, tp3_prob, tp3_logic, 20),
        "reject_zones": reject_zones[:4],
        "weighted_rr": round(
            (rr(tp1) * tp1_prob + rr(tp2) * tp2_prob + rr(tp3) * tp3_prob)
            / (tp1_prob + tp2_prob + tp3_prob),
            2,
        ),
    }


# ═══════════════════════════════════════════════════════════════════════
# 6) POSITION SIZE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════
def calculate_position_size(
    entry: float,
    sl: float,
    asset: str,
    capitals: List[float] = None,
    risk_pcts: List[float] = None,
) -> Dict:
    """يحسب حجم الصفقة بناءً على:
       - رأس المال
       - نسبة المخاطرة
       - مسافة SL
       
    Returns جدول كامل (capital × risk%).
    """
    cfg = _get_config(asset)
    capitals = capitals or [1000, 4000, 10000, 25000]
    risk_pcts = risk_pcts or [1.0, 1.5, 2.0]
    
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return {"table": [], "warning": "SL = Entry — invalid"}
    
    # Pip value calculation depends on asset
    # Gold: 1 pip = $0.10 لكل 0.01 lot
    # نحسب: lot_size = (capital × risk%) / (sl_distance × pip_value × 100)
    pip_value_per_001_lot = cfg["pip_value"]  # $0.10 for gold
    
    table = []
    for cap in capitals:
        row = {"capital": cap, "sizes": []}
        for risk_pct in risk_pcts:
            risk_amount = cap * (risk_pct / 100)
            
            # Gold (XAUUSD): 1 standard lot = 100 oz, 1$ move = $100 P&L
            # mini lot (0.1) = $10/pt, micro lot (0.01) = $1/pt
            # lot_size = risk_$ / (sl_distance × $100_per_pt_per_full_lot)
            if asset == "Gold":
                value_per_pt_per_lot = 100  # $100 per $1 move per 1 lot
                lot_size = risk_amount / (sl_distance * value_per_pt_per_lot)
            elif asset in ("USD/DXY", "DXY"):
                # DXY futures: 1 pt = $1000 per contract
                value_per_pt_per_lot = 1000
                lot_size = risk_amount / (sl_distance * value_per_pt_per_lot)
            else:
                # Forex generic: 1 standard lot = 100k units
                # 1 pip = $10 (for USD pairs)
                value_per_pip = 100000  # for std lot
                lot_size = risk_amount / (sl_distance * value_per_pip / 10)
            
            # تنسيق الـlot
            if lot_size >= 1:
                lot_str = f"{lot_size:.2f}"
            elif lot_size >= 0.01:
                lot_str = f"{lot_size:.3f}"
            else:
                lot_str = f"{lot_size:.4f}"
            
            row["sizes"].append({
                "risk_pct": risk_pct,
                "lot": round(lot_size, 4),
                "lot_str": lot_str,
                "risk_amount": round(risk_amount, 2),
            })
        table.append(row)
    
    return {
        "table": table,
        "sl_distance": round(sl_distance, cfg["decimals"]),
        "asset": asset,
    }


# ═══════════════════════════════════════════════════════════════════════
# 7) PARTIAL CLOSE STRATEGY
# ═══════════════════════════════════════════════════════════════════════
def build_partial_close_strategy(
    entry: float,
    sl: float,
    tp1: Dict,
    tp2: Dict,
    tp3: Dict,
    action: str,
    asset: str,
) -> List[Dict]:
    """يبني خطة خروج تدريجي ذكية.
    
    Returns:
        [{stage, price, action, sl_move_to, close_pct, note}, ...]
    """
    cfg = _get_config(asset)
    is_buy = action.upper() in ("BUY", "ADD")
    
    return [
        {
            "stage": 1,
            "trigger_price": tp1["price"],
            "trigger_label": f"TP1 @ {tp1['price']:.{cfg['decimals']}f}",
            "action": f"اقفل {tp1['close_pct']}% من الصفقة",
            "sl_move_to": round(entry, cfg["decimals"]),
            "sl_move_label": "Breakeven (Entry)",
            "close_pct": tp1["close_pct"],
            "remaining_pct": 100 - tp1["close_pct"],
            "note": "أمّن رأس المال — الصفقة risk-free من هنا",
        },
        {
            "stage": 2,
            "trigger_price": tp2["price"],
            "trigger_label": f"TP2 @ {tp2['price']:.{cfg['decimals']}f}",
            "action": f"اقفل {tp2['close_pct']}% إضافية",
            "sl_move_to": round(tp1["price"], cfg["decimals"]),
            "sl_move_label": f"TP1 ({tp1['price']:.{cfg['decimals']}f})",
            "close_pct": tp2["close_pct"],
            "remaining_pct": 100 - tp1["close_pct"] - tp2["close_pct"],
            "note": "أمّن ربح TP1 + اترك runner",
        },
        {
            "stage": 3,
            "trigger_price": tp3["price"],
            "trigger_label": f"TP3 @ {tp3['price']:.{cfg['decimals']}f}",
            "action": f"اقفل آخر {tp3['close_pct']}% (Runner)",
            "sl_move_to": round(tp2["price"], cfg["decimals"]),
            "sl_move_label": f"TP2 ({tp2['price']:.{cfg['decimals']}f})",
            "close_pct": tp3["close_pct"],
            "remaining_pct": 0,
            "note": "🏆 الصفقة مكتملة!",
        },
    ]


# ═══════════════════════════════════════════════════════════════════════
# 8) MAIN ENTRY POINT — Full Risk Analysis
# ═══════════════════════════════════════════════════════════════════════
def build_full_risk_analysis(
    entry: float,
    action: str,
    ta: Dict,
    df: pd.DataFrame,
    asset: str = "Gold",
    capital: float = None,
) -> Dict:
    """البوابة الرئيسية — تحلل مخاطر صفقة كاملة.
    
    Args:
        entry: سعر الدخول
        action: BUY / SELL / ADD / REDUCE
        ta: dict من technical_analysis()
        df: DataFrame من yfinance
        asset: اسم الأصل
        capital: رأس المال (اختياري)
    
    Returns:
        dict كامل بكل البيانات للعرض
    """
    if not entry or not action:
        return {"error": "entry/action مطلوبان"}
    
    if action.upper() in ("HOLD", "REDUCE"):
        return {"action": action, "skip_reason": "HOLD/REDUCE — لا يحتاج SL/TP جديد"}
    
    # 1. خريطة السيولة
    liq_map = build_liquidity_map(entry, df, ta, asset)
    
    # 2. Smart SL
    sl_data = calculate_smart_sl(entry, action, ta, df, liq_map, asset)
    
    # استخدم الـrecommended SL لحساب TP
    recommended_sl = sl_data[sl_data["recommended"]]["price"]
    
    # 3. Smart TP
    tp_data = calculate_smart_tp(entry, recommended_sl, action, ta, df, liq_map, asset)
    
    # 4. Partial Close Strategy
    strategy = build_partial_close_strategy(
        entry, recommended_sl,
        tp_data["tp1"], tp_data["tp2"], tp_data["tp3"],
        action, asset,
    )
    
    # 5. Position Sizing
    capitals = [capital] if capital else [1000, 4000, 10000]
    sizing = calculate_position_size(entry, recommended_sl, asset, capitals=capitals)
    
    return {
        "asset": asset,
        "action": action,
        "entry": entry,
        "atr": ta.get("atr", 0),
        "sl": sl_data,
        "tp": tp_data,
        "strategy": strategy,
        "sizing": sizing,
        "liquidity_map": liq_map,
    }


# ═══════════════════════════════════════════════════════════════════════
# 9) ADVANCED FORMATTING (نص + ASCII charts + visual indicators)
# ═══════════════════════════════════════════════════════════════════════
def _bar(value: float, max_value: float = 100, width: int = 10) -> str:
    """يصنع شريط visual: ▓▓▓▓▓░░░░░"""
    if max_value == 0:
        return "░" * width
    filled = int(round((value / max_value) * width))
    filled = max(0, min(width, filled))
    return "▓" * filled + "░" * (width - filled)


def _strength_bar(strength: str) -> str:
    """شريط حسب الـstrength."""
    mapping = {
        "very_strong": ("▓▓▓▓▓▓▓▓▓░", "قوي جداً"),
        "strong": ("▓▓▓▓▓▓▓░░░", "قوي"),
        "medium": ("▓▓▓▓▓░░░░░", "متوسط"),
        "weak": ("▓▓▓░░░░░░░", "ضعيف"),
    }
    return mapping.get(strength, ("▓▓▓░░░░░░░", "—"))[0]


def format_smart_risk_advanced(risk_data: Dict, lang: str = "ar") -> str:
    """تنسيق متقدّم: نص + ASCII charts + visual indicators."""
    if "error" in risk_data:
        return f"⚠️ {risk_data['error']}"
    
    if "skip_reason" in risk_data:
        return f"ℹ️ {risk_data['skip_reason']}"
    
    asset = risk_data["asset"]
    action = risk_data["action"]
    entry = risk_data["entry"]
    atr = risk_data["atr"]
    cfg = _get_config(asset)
    dp = cfg["decimals"]
    sym = cfg["symbol"]
    
    is_buy = action.upper() in ("BUY", "ADD")
    arrow = "🟢 BUY" if is_buy else "🔴 SELL"
    
    out = []
    
    # ═══ HEADER ═══
    out.append("🛡️ *SMART RISK MANAGEMENT*")
    out.append("═" * 33)
    out.append(f"📊 *{asset}*  |  {arrow}")
    out.append(f"💰 Entry: `{sym}{entry:,.{dp}f}`  |  ATR: `{atr:.{dp}f}`")
    out.append("")
    
    # ═══ SMART MONEY / LIQUIDITY POOLS SECTION ═══
    liq_map = risk_data.get("liquidity_map", {})
    liq_pools = liq_map.get("liquidity_pools", {})
    sm_zones = liq_map.get("smart_money_zones", {})
    
    if liq_pools or sm_zones:
        out.append("🐋 *SMART MONEY ANALYSIS*")
        out.append("─" * 33)
        
        # Buy-side Liquidity (BSL) - أهداف الـlongs
        bsl = [p for p in liq_pools.get("buy_side", []) if not p.get("is_swept")][:3]
        if bsl:
            out.append("📈 *Buy-side Liquidity (BSL):*")
            out.append("_(فوق السعر - أماكن الـStops للـShorts)_")
            for p in bsl:
                bars = f" | {p.get('bars_ago')}b" if p.get('bars_ago') else ""
                strength_icon = {"very_strong": "🔥", "strong": "💪", "medium": "✓"}.get(
                    p["strength"], "·"
                )
                out.append(
                    f"   {strength_icon} {p['icon']} `{sym}{p['price']:,.{dp}f}` "
                    f"({p['type']}{bars})"
                )
            out.append("")
        
        # Sell-side Liquidity (SSL) - أهداف الـshorts
        ssl = [p for p in liq_pools.get("sell_side", []) if not p.get("is_swept")][:3]
        if ssl:
            out.append("📉 *Sell-side Liquidity (SSL):*")
            out.append("_(تحت السعر - أماكن الـStops للـLongs)_")
            for p in ssl:
                bars = f" | {p.get('bars_ago')}b" if p.get('bars_ago') else ""
                strength_icon = {"very_strong": "🔥", "strong": "💪", "medium": "✓"}.get(
                    p["strength"], "·"
                )
                out.append(
                    f"   {strength_icon} {p['icon']} `{sym}{p['price']:,.{dp}f}` "
                    f"({p['type']}{bars})"
                )
            out.append("")
        
        # Order Blocks (مناطق دخول الحيتان)
        bull_obs = sm_zones.get("bullish_obs", [])[:2]
        bear_obs = sm_zones.get("bearish_obs", [])[:2]
        if bull_obs or bear_obs:
            out.append("🐋 *Order Blocks (دخول الحيتان):*")
            for ob in bull_obs:
                out.append(
                    f"   🟢 Bullish OB: `{sym}{ob['low']:,.{dp}f}` - "
                    f"`{sym}{ob['high']:,.{dp}f}` ({ob['bars_ago']}b ago)"
                )
            for ob in bear_obs:
                out.append(
                    f"   🔴 Bearish OB: `{sym}{ob['low']:,.{dp}f}` - "
                    f"`{sym}{ob['high']:,.{dp}f}` ({ob['bars_ago']}b ago)"
                )
            out.append("")
        
        # Break of Structure
        bos = sm_zones.get("recent_bos", [])
        if bos:
            for b in bos:
                direction_text = "صعود" if b["direction"] == "up" else "هبوط"
                out.append(
                    f"⚡ *{b['type']}*: اختراق {direction_text} لـ"
                    f"`{sym}{b['price']:,.{dp}f}`"
                )
            out.append("")
    
    # ═══ SL SECTION ═══
    sl = risk_data["sl"]
    rec = sl["recommended"]
    
    out.append("📉 *STOP LOSS LEVELS*")
    out.append("─" * 33)
    
    for level_name, label, icon in [
        ("conservative", "Conservative", "🟢"),
        ("balanced", "Balanced", "🟡"),
        ("aggressive", "Aggressive", "🔴"),
    ]:
        s = sl[level_name]
        star = " ⭐" if level_name == rec else ""
        bar_strength = {"conservative": 9, "balanced": 6, "aggressive": 3}[level_name]
        bar = _bar(bar_strength, 10, 10)
        bar_label = {"conservative": "آمن جداً", "balanced": "متوازن", "aggressive": "ضيّق"}[level_name]
        
        out.append(f"{icon} *{label}*: `{sym}{s['price']:,.{dp}f}` "
                   f"({s['distance']:+.{dp}f} | {s['distance_pct']:.2f}%){star}")
        out.append(f"   `{bar}` {bar_label}")
        for line in s["logic"][:3]:
            out.append(f"   ✓ {line}")
        out.append("")
    
    # ═══ DANGER ZONES ═══
    if sl["danger_zones"]:
        out.append("⚠️ *DANGER ZONES* — تجنّب SL هنا:")
        out.append("─" * 33)
        for dz in sl["danger_zones"]:
            out.append(f"🚨 `{sym}{dz['price']:,.{dp}f}` ← {dz['icon']} {dz['type']}")
            out.append(f"     _({dz['reason']})_")
        out.append("")
    
    # ═══ TP SECTION ═══
    tp = risk_data["tp"]
    
    out.append("🎯 *TAKE PROFIT TARGETS*")
    out.append("─" * 33)
    
    for tp_key, label, icon, star_label in [
        ("tp1", "TP1 - Conservative", "🟢", ""),
        ("tp2", "TP2 - Balanced", "🟡", " ⭐ الهدف الأساسي"),
        ("tp3", "TP3 - Extended", "🔴", ""),
    ]:
        t = tp[tp_key]
        prob_bar = _bar(t["probability"], 100, 10)
        
        out.append(f"{icon} *{label}*: `{sym}{t['price']:,.{dp}f}`{star_label}")
        out.append(f"   📏 ({t['distance']:+.{dp}f} | {t['distance_pct']:+.2f}%)")
        out.append(f"   📊 احتمال: `{prob_bar}` *{t['probability']}%*")
        out.append(f"   📐 R:R = `1:{t['rr']}`  |  📋 اقفل *{t['close_pct']}%*")
        for line in t["logic"][:2]:
            out.append(f"   ✓ {line}")
        out.append("")
    
    # ═══ REJECT ZONES ═══
    if tp["reject_zones"]:
        out.append("⚠️ *REJECT ZONES* — مقاومة في الطريق:")
        out.append("─" * 33)
        for rz in tp["reject_zones"]:
            out.append(f"{rz['icon']} `{sym}{rz['price']:,.{dp}f}` ← {rz['type']}")
            out.append(f"     _({rz['warning']})_")
        out.append("")
    
    # ═══ PARTIAL CLOSE STRATEGY ═══
    out.append("📋 *PARTIAL CLOSE STRATEGY*")
    out.append("─" * 33)
    for s in risk_data["strategy"]:
        out.append(f"*Stage {s['stage']}*: عند {s['trigger_label']}")
        out.append(f"   ▸ {s['action']}")
        out.append(f"   ▸ حرّك SL → {s['sl_move_label']}")
        out.append(f"   ▸ متبقّي: {s['remaining_pct']}%")
        out.append(f"   💡 _{s['note']}_")
        out.append("")
    
    # ═══ POSITION SIZING TABLE ═══
    sizing = risk_data["sizing"]
    if sizing.get("table"):
        out.append("💰 *POSITION SIZING* (مع SL = Recommended)")
        out.append("─" * 33)
        out.append("```")
        out.append("Capital   | Risk 1%  | Risk 1.5% | Risk 2%")
        out.append("──────────┼──────────┼───────────┼─────────")
        for row in sizing["table"]:
            cap_str = f"${row['capital']:,}".ljust(9)
            sizes = row["sizes"]
            r1 = f"{sizes[0]['lot_str']} lot".ljust(8)
            r2 = f"{sizes[1]['lot_str']} lot".ljust(9)
            r3 = f"{sizes[2]['lot_str']} lot".ljust(7)
            out.append(f"{cap_str} | {r1} | {r2} | {r3}")
        out.append("```")
        out.append(f"_SL distance: {sizing['sl_distance']:.{dp}f} {sym}_")
        out.append("")
    
    # ═══ R:R BREAKDOWN ═══
    out.append("📊 *R:R BREAKDOWN*")
    out.append("─" * 33)
    max_rr = max(tp["tp1"]["rr"], tp["tp2"]["rr"], tp["tp3"]["rr"])
    for tp_key, label in [("tp1", "TP1"), ("tp2", "TP2"), ("tp3", "TP3")]:
        rr_val = tp[tp_key]["rr"]
        bar = _bar(rr_val, max(max_rr, 4), 10)
        star = " ⭐" if tp_key == "tp2" else ""
        out.append(f"{label} → `1:{rr_val}` `{bar}`{star}")
    out.append(f"")
    out.append(f"⚖️  *متوسط R:R المرجّح: `1:{tp['weighted_rr']}`*")
    
    weighted_quality = (
        "✅ ممتاز" if tp["weighted_rr"] >= 2.5
        else "🟡 مقبول" if tp["weighted_rr"] >= 1.5
        else "🔴 ضعيف"
    )
    out.append(f"   التقييم: {weighted_quality}")
    out.append("")
    
    # ═══ FOOTER ═══
    rec_sl_price = sl[rec]["price"]
    out.append("═" * 33)
    out.append("💡 *الذكاء النهائي:*")
    out.append(f"  ▸ SL: `{sym}{rec_sl_price:,.{dp}f}` ({rec.title()})")
    out.append(f"  ▸ خطة الخروج: 50/30/20")
    out.append(f"  ▸ Risk Management: 1-1.5% per trade")
    out.append("")
    out.append("⚠️ _تحليل تعليمي — ليس نصيحة استثمارية_")
    
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════════
# 10) PARSE AI ENTRY (للتكامل مع build_recommendation)
# ═══════════════════════════════════════════════════════════════════════
import re

def parse_entry_from_ai(text: str) -> Optional[float]:
    """يستخرج Entry من نص توصية AI."""
    patterns = [
        r"Entry[:\s]+\$?([\d,]+\.?\d*)",
        r"الدخول[:\s]+\$?([\d,]+\.?\d*)",
        r"دخول[:\s]+\$?([\d,]+\.?\d*)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except:
                pass
    return None


def parse_action_from_ai(text: str) -> Optional[str]:
    """يستخرج Action من نص."""
    text_upper = text.upper()
    for kw in ["BUY", "SELL", "HOLD", "ADD", "REDUCE"]:
        if kw in text_upper:
            return kw
    # العربية
    if "شراء" in text or "اشتري" in text:
        return "BUY"
    if "بيع" in text or "بيع" in text:
        return "SELL"
    return None


# ═══════════════════════════════════════════════════════════════════════
# 14) BACKTESTING ENGINE — اختبار الاستراتيجيات على البيانات التاريخية
# ═══════════════════════════════════════════════════════════════════════
def backtest_smart_risk_strategy(
    df: pd.DataFrame,
    asset: str = "Gold",
    initial_capital: float = 4000,
    risk_per_trade_pct: float = 1.5,
    min_confluence: int = 6,
) -> Dict:
    """يختبر استراتيجية Smart Risk على بيانات تاريخية.
    
    الاستراتيجية:
    1. كل 5 أيام (لتجنب overtrading) نتحقق من Multi-TF Confluence
    2. لو في توافق ≥ min_confluence، نفتح صفقة
    3. نستخدم Liquidity Pools لـSL/TP
    4. Position size بناء على risk_per_trade_pct
    5. نتابع كل شمعة - لو ضرب TP1/TP2/TP3/SL، نحسب النتيجة
    
    Returns: نتائج شاملة + قائمة بكل الصفقات
    """
    if df is None or df.empty or len(df) < 100:
        return {"error": "Not enough data for backtest"}
    
    capital = initial_capital
    trades = []
    equity_curve = [(df.index[0], capital)]
    open_trade = None
    last_trade_close_idx = -10  # تجنب trading متتالي
    
    for i in range(50, len(df) - 1):
        current_bar = df.iloc[i]
        next_bar = df.iloc[i + 1] if i + 1 < len(df) else current_bar
        
        # ─── إدارة الصفقة المفتوحة ───
        if open_trade:
            high = float(next_bar["High"])
            low = float(next_bar["Low"])
            
            is_buy = open_trade["action"] == "BUY"
            sl = open_trade["sl"]
            tp1 = open_trade["tp1"]
            tp2 = open_trade["tp2"]
            tp3 = open_trade["tp3"]
            entry = open_trade["entry"]
            risk = abs(entry - sl)
            
            exit_price = None
            exit_reason = None
            
            if is_buy:
                # check SL first (worst case)
                if low <= sl:
                    exit_price = sl
                    exit_reason = "SL"
                elif high >= tp3:
                    exit_price = tp3
                    exit_reason = "TP3"
                elif high >= tp2:
                    exit_price = tp2
                    exit_reason = "TP2"
                elif high >= tp1 and not open_trade.get("tp1_hit"):
                    open_trade["tp1_hit"] = True
                    open_trade["sl"] = entry  # move to BE
            else:  # SELL
                if high >= sl:
                    exit_price = sl
                    exit_reason = "SL"
                elif low <= tp3:
                    exit_price = tp3
                    exit_reason = "TP3"
                elif low <= tp2:
                    exit_price = tp2
                    exit_reason = "TP2"
                elif low <= tp1 and not open_trade.get("tp1_hit"):
                    open_trade["tp1_hit"] = True
                    open_trade["sl"] = entry
            
            if exit_price:
                # حساب PnL
                if is_buy:
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100
                
                # Position size = risk_amount / (risk_per_unit)
                risk_amount = capital * (risk_per_trade_pct / 100)
                # حماية من قسمة على صفر
                sl_pct = abs((sl - entry) / entry * 100) if entry > 0 else 0
                if sl_pct == 0:
                    # SL = Entry (مستحيل عملياً) - نتخطى
                    open_trade = None
                    continue
                pnl_dollars = risk_amount * (pnl_pct / sl_pct)
                if exit_reason == "SL":
                    pnl_dollars = -risk_amount
                
                capital += pnl_dollars
                
                trades.append({
                    "open_idx": open_trade["open_idx"],
                    "close_idx": i + 1,
                    "open_date": str(df.index[open_trade["open_idx"]])[:10],
                    "close_date": str(df.index[i + 1])[:10],
                    "asset": asset,
                    "action": open_trade["action"],
                    "entry": round(entry, 4),
                    "exit": round(exit_price, 4),
                    "sl": round(open_trade["sl_initial"], 4),
                    "tp1": round(tp1, 4),
                    "tp2": round(tp2, 4),
                    "tp3": round(tp3, 4),
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_dollars": round(pnl_dollars, 2),
                    "capital_after": round(capital, 2),
                    "tp1_was_hit": open_trade.get("tp1_hit", False),
                })
                
                equity_curve.append((df.index[i + 1], capital))
                last_trade_close_idx = i
                open_trade = None
                
                # Stop if blown up
                if capital < initial_capital * 0.5:
                    break
        
        # ─── البحث عن صفقة جديدة ───
        if not open_trade and (i - last_trade_close_idx) >= 5:
            # نأخذ subset للـMulti-TF analysis
            df_so_far = df.iloc[:i + 1]
            
            if len(df_so_far) < 100:
                continue
            
            # Approximate 4H من Daily (تقريبي للـbacktest)
            daily_subset = df_so_far.iloc[-min(60, len(df_so_far)):]
            
            # تحليل bias
            try:
                analysis = analyze_timeframe_bias(daily_subset)
            except Exception:
                continue
            
            bias = analysis["bias"]
            strength = analysis["strength"]
            
            if bias == "STRONG_BULLISH" or (bias == "BULLISH" and strength >= 7):
                # فرصة BUY
                action = "BUY"
            elif bias == "STRONG_BEARISH" or (bias == "BEARISH" and strength >= 7):
                action = "SELL"
            else:
                continue
            
            # تحقق من Liquidity Pools
            try:
                liq_pools = find_liquidity_pools(df_so_far, asset)
                sm_zones = find_smart_money_zones(df_so_far, asset)
            except Exception:
                continue
            
            entry = float(current_bar["Close"])
            
            # ATR لـSL
            high_low = df_so_far["High"] - df_so_far["Low"]
            high_close = (df_so_far["High"] - df_so_far["Close"].shift()).abs()
            low_close = (df_so_far["Low"] - df_so_far["Close"].shift()).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1] or entry * 0.005)
            
            # ─── حساب SL/TP من liquidity pools ───
            if action == "BUY":
                # SL = خلف أقرب SSL pool
                ssl_pools = [p for p in liq_pools.get("sell_side", [])
                            if not p.get("is_swept") and p["distance_pct"] < 5]
                if ssl_pools:
                    nearest = min(ssl_pools, key=lambda x: x["distance_pct"])
                    sl = nearest["price"] - atr * 0.5
                else:
                    sl = entry - atr * 1.5
                
                # TPs = نحو BSL pools
                bsl_pools = [p for p in liq_pools.get("buy_side", [])
                            if not p.get("is_swept") and p["distance_pct"] > 0.5]
                bsl_pools.sort(key=lambda x: x["distance_pct"])
                
                if len(bsl_pools) >= 3:
                    tp1 = bsl_pools[0]["price"]
                    tp2 = bsl_pools[1]["price"]
                    tp3 = bsl_pools[2]["price"]
                else:
                    risk = abs(entry - sl)
                    tp1 = entry + risk * 1
                    tp2 = entry + risk * 2
                    tp3 = entry + risk * 3
            
            else:  # SELL
                bsl_pools = [p for p in liq_pools.get("buy_side", [])
                            if not p.get("is_swept") and p["distance_pct"] < 5]
                if bsl_pools:
                    nearest = min(bsl_pools, key=lambda x: x["distance_pct"])
                    sl = nearest["price"] + atr * 0.5
                else:
                    sl = entry + atr * 1.5
                
                ssl_pools = [p for p in liq_pools.get("sell_side", [])
                            if not p.get("is_swept") and p["distance_pct"] > 0.5]
                ssl_pools.sort(key=lambda x: x["distance_pct"])
                
                if len(ssl_pools) >= 3:
                    tp1 = ssl_pools[0]["price"]
                    tp2 = ssl_pools[1]["price"]
                    tp3 = ssl_pools[2]["price"]
                else:
                    risk = abs(entry - sl)
                    tp1 = entry - risk * 1
                    tp2 = entry - risk * 2
                    tp3 = entry - risk * 3
            
            # تأكد إن TP في الاتجاه الصحيح
            if action == "BUY":
                if not (tp1 > entry and tp2 > entry and tp3 > entry):
                    continue
            else:
                if not (tp1 < entry and tp2 < entry and tp3 < entry):
                    continue
            
            # تأكد من R:R معقول
            risk = abs(entry - sl)
            if risk == 0:
                continue
            rr_to_tp1 = abs(tp1 - entry) / risk
            if rr_to_tp1 < 0.5:  # too tight
                continue
            
            open_trade = {
                "open_idx": i,
                "action": action,
                "entry": entry,
                "sl_initial": sl,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "tp1_hit": False,
            }
    
    # ─── حساب الإحصاءات ───
    if not trades:
        return {
            "asset": asset,
            "period_days": (df.index[-1] - df.index[0]).days,
            "total_trades": 0,
            "error": "No trades generated by strategy",
        }
    
    wins = [t for t in trades if t["pnl_dollars"] > 0]
    losses = [t for t in trades if t["pnl_dollars"] < 0]
    
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    # Profit Factor
    gross_wins = sum(t["pnl_dollars"] for t in wins)
    gross_losses = abs(sum(t["pnl_dollars"] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0
    
    # Max Drawdown
    peak = initial_capital
    max_dd = 0
    for ts, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    # Total Return
    total_return = (capital - initial_capital) / initial_capital * 100
    
    # Average R:R
    avg_rr = sum(abs(t["pnl_pct"]) for t in trades) / len(trades) if trades else 0
    
    # Sharpe (مبسط)
    if len(trades) > 1:
        returns = [t["pnl_pct"] for t in trades]
        mean_r = sum(returns) / len(returns)
        std_r = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5
        sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0
    else:
        sharpe = 0
    
    return {
        "asset": asset,
        "period_days": (df.index[-1] - df.index[0]).days,
        "start_date": str(df.index[0])[:10],
        "end_date": str(df.index[-1])[:10],
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_rr": round(avg_rr, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "total_return_pct": round(total_return, 2),
        "sharpe_ratio": round(sharpe, 2),
        "best_trade": max(trades, key=lambda t: t["pnl_dollars"]) if trades else None,
        "worst_trade": min(trades, key=lambda t: t["pnl_dollars"]) if trades else None,
        "trades": trades,
    }


def format_backtest_results(result: Dict) -> str:
    """تنسيق نتائج الـbacktest للـTelegram."""
    if result.get("error") and result.get("total_trades", 0) == 0:
        return f"⚠️ *Backtest Failed*\n\n{result.get('error', '')}"
    
    out = []
    out.append("📊 *BACKTEST RESULTS*")
    out.append("═" * 33)
    out.append(f"📈 الأصل: *{result['asset']}*")
    out.append(f"📅 الفترة: {result['start_date']} → {result['end_date']}")
    out.append(f"⏱ الأيام: {result['period_days']}")
    out.append("")
    
    # ─── Capital ───
    out.append("💰 *رأس المال:*")
    out.append(f"   Initial: `${result['initial_capital']:,.0f}`")
    final = result['final_capital']
    icon = "🟢" if final >= result['initial_capital'] else "🔴"
    out.append(f"   Final:   `${final:,.2f}` {icon}")
    
    total_ret = result['total_return_pct']
    ret_icon = "🟢" if total_ret > 0 else "🔴"
    out.append(f"   {ret_icon} العائد: *{total_ret:+.2f}%*")
    out.append("")
    
    # ─── Performance ───
    out.append("─" * 33)
    out.append("📊 *الأداء:*")
    out.append(f"   📋 إجمالي الصفقات: *{result['total_trades']}*")
    out.append(f"   🟢 رابحة: {result['winning_trades']}")
    out.append(f"   🔴 خاسرة: {result['losing_trades']}")
    
    wr = result['win_rate']
    wr_icon = "🌟" if wr >= 60 else "✅" if wr >= 50 else "⚠️"
    out.append(f"   {wr_icon} Win Rate: *{wr}%*")
    out.append("")
    
    # ─── Risk Metrics ───
    out.append("─" * 33)
    out.append("⚖️ *مؤشرات المخاطر:*")
    
    pf = result['profit_factor']
    pf_icon = "🌟" if pf >= 2 else "✅" if pf >= 1.5 else "⚠️" if pf >= 1 else "🔴"
    out.append(f"   {pf_icon} Profit Factor: *{pf}*")
    
    dd = result['max_drawdown_pct']
    dd_icon = "🟢" if dd < 5 else "🟡" if dd < 10 else "🔴"
    out.append(f"   {dd_icon} Max Drawdown: *{dd}%*")
    
    sharpe = result['sharpe_ratio']
    sh_icon = "🌟" if sharpe >= 2 else "✅" if sharpe >= 1 else "⚠️"
    out.append(f"   {sh_icon} Sharpe Ratio: *{sharpe}*")
    
    out.append(f"   📐 Avg R:R: {result['avg_rr']}")
    out.append("")
    
    # ─── Best/Worst ───
    if result.get("best_trade") and result.get("worst_trade"):
        best = result["best_trade"]
        worst = result["worst_trade"]
        out.append("─" * 33)
        out.append("🏆 *أفضل صفقة:*")
        out.append(f"   {best['open_date']} | {best['action']}")
        out.append(f"   Entry: `{best['entry']}` → Exit: `{best['exit']}` ({best['exit_reason']})")
        out.append(f"   💰 ربح: *{best['pnl_pct']:+.2f}%* (`${best['pnl_dollars']:+.2f}`)")
        out.append("")
        out.append("💔 *أسوأ صفقة:*")
        out.append(f"   {worst['open_date']} | {worst['action']}")
        out.append(f"   Entry: `{worst['entry']}` → Exit: `{worst['exit']}` ({worst['exit_reason']})")
        out.append(f"   💸 خسارة: *{worst['pnl_pct']:+.2f}%* (`${worst['pnl_dollars']:+.2f}`)")
        out.append("")
    
    # ─── التقييم النهائي ───
    out.append("─" * 33)
    out.append("🎯 *التقييم العام:*")
    
    score = 0
    if wr >= 60: score += 3
    elif wr >= 50: score += 2
    elif wr >= 40: score += 1
    
    if pf >= 2: score += 3
    elif pf >= 1.5: score += 2
    elif pf >= 1: score += 1
    
    if dd < 5: score += 2
    elif dd < 10: score += 1
    
    if sharpe >= 1.5: score += 2
    elif sharpe >= 1: score += 1
    
    if score >= 8:
        rating = "🌟🌟🌟🌟🌟 استراتيجية ممتازة"
        verdict = "هذي استراتيجية احترافية - جاهزة للتطبيق"
    elif score >= 6:
        rating = "🌟🌟🌟🌟 استراتيجية جيدة جداً"
        verdict = "أداء قوي - فعّلها بحذر"
    elif score >= 4:
        rating = "🌟🌟🌟 استراتيجية متوسطة"
        verdict = "تحتاج تحسين - راجع الإعدادات"
    else:
        rating = "🌟 استراتيجية ضعيفة"
        verdict = "❌ لا تستخدمها - أعد تصميم الاستراتيجية"
    
    out.append(rating)
    out.append(f"_{verdict}_")
    out.append("")
    
    out.append("⚠️ _Past performance ≠ future results_")
    out.append("⚠️ _اختبار تعليمي — ليس ضمان للأرباح_")
    
    return "\n".join(out)
