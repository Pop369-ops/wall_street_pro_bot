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
        "pip_value": 0.10,         # 1 pip = $0.10 per 0.01 lot
        "round_levels": [10, 25, 50, 100],   # round numbers spacing
        "min_distance": 5.0,        # min SL distance in price
        "default_atr_mult": 1.5,
        "decimals": 2,
        "symbol": "$",
    },
    "USD/DXY": {
        "pip_value": 1.0,
        "round_levels": [0.5, 1.0, 5.0],
        "min_distance": 0.10,
        "default_atr_mult": 1.5,
        "decimals": 3,
        "symbol": "",
    },
    "EUR/USD": {
        "pip_value": 10.0,
        "round_levels": [0.0050, 0.0100],
        "min_distance": 0.0010,
        "default_atr_mult": 1.5,
        "decimals": 5,
        "symbol": "",
    },
    "default": {
        "pip_value": 1.0,
        "round_levels": [10, 50, 100],
        "min_distance": 1.0,
        "default_atr_mult": 1.5,
        "decimals": 2,
        "symbol": "",
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
    
    # ترتيب حسب القرب من السعر
    levels_above.sort(key=lambda x: x["distance_pct"])
    levels_below.sort(key=lambda x: x["distance_pct"])
    
    return {
        "above": levels_above[:10],
        "below": levels_below[:10],
        "current_price": price,
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
    
    # ═══ Conservative SL (الأكثر أماناً) ═══
    cons_sl = None
    cons_logic = []
    max_distance_cons = atr * 4  # حد أقصى أوسع للـconservative
    
    # ابحث عن أقرب OB قوي في النطاق
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
    
    # Fallback: لو ما لقيناش OB قريب
    if cons_sl is None:
        mult = 2.5
        cons_sl = entry - atr * mult if is_buy else entry + atr * mult
        cons_logic.append(f"ATR × {mult} (لا يوجد OB قريب)")
    
    # ═══ Balanced SL (متوازن) ═══
    # الأقرب: أقرب Swing Point في النطاق المعقول (مش أبعد من 3× ATR)
    bal_sl = None
    bal_logic = []
    max_distance = atr * 3  # حد أقصى للمسافة
    
    swing_candidates = [
        l for l in reference_levels
        if "Swing" in l["type"] and abs(l["price"] - entry) <= max_distance
    ]
    # ترتيب حسب القرب من entry (الأقرب أولاً)
    swing_candidates.sort(key=lambda x: abs(x["price"] - entry))
    
    for lvl in swing_candidates:
        buffer = atr * 0.3
        if is_buy:
            candidate = lvl["price"] - buffer
            # تأكد إنه أبعد من Conservative بشكل منطقي
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
    
    # ═══ TP1: Conservative (سريع) ═══
    tp1 = None
    tp1_logic = []
    
    # أقرب Swing Point أو OB في الاتجاه
    for lvl in target_levels:
        if lvl["distance_pct"] < 1.5 and lvl["strength"] in ("strong", "very_strong"):
            tp1 = lvl["price"] * 0.998 if is_buy else lvl["price"] * 1.002  # قبله شوية
            tp1_logic.append(f"قبل {lvl['type']} @ {lvl['price']:.{cfg['decimals']}f}")
            break
    
    # Fallback: 1× ATR
    if tp1 is None:
        atr = ta.get("atr", entry * 0.005)
        tp1 = entry + atr * 1.5 if is_buy else entry - atr * 1.5
        tp1_logic.append("1.5 × ATR (fallback)")
    
    # ═══ TP2: Balanced (الهدف الأساسي - liquidity cluster) ═══
    tp2 = None
    tp2_logic = []
    
    # ابحث عن Equal Highs/Lows أو Liquidity Cluster كبير
    for lvl in target_levels:
        if (
            ("Equal" in lvl["type"] or "Round" in lvl["type"])
            and lvl["strength"] == "very_strong"
            and lvl["distance_pct"] > 0.8
        ):
            tp2 = lvl["price"]
            tp2_logic.append(f"عند {lvl['type']} (تجمّع stops) @ {lvl['price']:.{cfg['decimals']}f}")
            break
    
    # Fallback: استخدم أبعد strong level
    if tp2 is None:
        strong_levels = [l for l in target_levels if l["strength"] in ("strong", "very_strong")]
        if len(strong_levels) >= 2:
            tp2 = strong_levels[1]["price"]
            tp2_logic.append(f"عند {strong_levels[1]['type']} @ {strong_levels[1]['price']:.{cfg['decimals']}f}")
        else:
            # 2× R
            tp2 = entry + risk * 2.5 if is_buy else entry - risk * 2.5
            tp2_logic.append("R:R = 1:2.5 (محسوب)")
    
    # ═══ TP3: Extended (الحلم) ═══
    tp3 = None
    tp3_logic = []
    
    # ابحث عن Round Number كبير أو أبعد Equal Highs (في نطاق 3-5× R)
    max_tp3 = entry + risk * 5 if is_buy else entry - risk * 5
    
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
    
    # Fallback: 3× R (مش 4)
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
