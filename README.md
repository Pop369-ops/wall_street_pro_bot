# 🌟 WALL STREET PRO BOT V4.1 — Smart Risk Edition

بوت Telegram احترافي يدمج 3 AIs (Claude + Gemini + OpenAI) مع بيانات السوق الحقيقية + **محرك إدارة مخاطر ذكي** لتقديم تحليلات وتوصيات تداول الذهب والفوركس بمستوى مؤسسي.

---

## ✨ المميزات

### 🎯 المحرك الأساسي
- 🎯 **محرك توصيات BUY/SELL/HOLD** بـ3 AIs + إجماع نهائي
- 📊 **تحليل فني كامل** (RSI, MACD, EMA, BB, ICT Order Blocks, FVG)
- 🐋 **Smart Money** (CFTC COT/TFF Reports)
- 💎 **Options Sentiment** (Polygon API - Put/Call ratios)
- 🏦 **عقلية البنوك المركزية** (Yield Curve + Fed Watch)
- 🌍 **Macro Snapshot** (FRED - Fed Funds, CPI, GDP, PCE...)
- 📅 **التقويم الاقتصادي** (Trading Economics + ForexFactory)
- 📰 **9 مصادر RSS** (FXStreet, Investing, ForexLive, Reuters, Fed, ECB...)
- 🚨 **مراقب أخبار High-Impact** كل 30 دقيقة + تنبيهات
- 📅 **تقرير صباحي تلقائي** (وقت مخصص لكل user)
- 💾 **SQLite Memory** — يتذكر كل توصية + يحسب الأداء
- 📚 **Performance Tracking** (دقة، PnL نظري، آخر التوصيات)

### 🛡️ Smart Risk Management ✨ جديد في V4.1

**كل توصية يطلعها البوت دلوقتي بتحتوي على تحليل مخاطر متكامل:**

#### 📉 Smart Stop Loss (3 مستويات)
- 🟢 **Conservative**: ورا Order Block 4H + Buffer (ATR × 0.5)
- 🟡 **Balanced**: ورا أقرب Swing Point + Buffer (ATR × 0.3)
- 🔴 **Aggressive**: ATR × 0.9 (سريع - مع تحذير لو قريب من Liquidity)

#### ⚠️ Danger Zones — تجنّب SL هنا
- 🚨 Round Numbers (تجمّع stops متوقع)
- 🚨 Recent Swing Highs/Lows
- 🚨 Bullish/Bearish Order Blocks
- 🚨 Equal Highs/Lows (Liquidity Pools)

#### 🎯 Smart Take Profit (3 أهداف + احتمالات)
- 🟢 **TP1 Conservative** (سريع - 78-85% احتمال) — قبل Bearish OB
- 🟡 **TP2 Balanced** (الهدف الأساسي - 50-65% احتمال) — Equal Highs Cluster
- 🔴 **TP3 Extended** (الحلم - 25-40% احتمال) — Round Number/Weekly Resistance

#### ⚠️ Reject Zones — مقاومة في طريق السعر
يكشف Order Blocks و FVG معاكسة في طريق الأهداف

#### 📋 Partial Close Strategy
خطة خروج 3 مراحل (50/30/20) مع نقل SL تلقائي:
- Stage 1: TP1 → اقفل 50% + SL → Breakeven
- Stage 2: TP2 → اقفل 30% + SL → TP1
- Stage 3: TP3 → اقفل آخر 20%

#### 💰 Position Size Calculator
جدول يربط رأس المال × نسبة المخاطرة → حجم الصفقة المثالي
(مدعوم لرأس مال $1K, $4K, $10K مع 1%, 1.5%, 2% مخاطرة)

#### 📊 R:R Analysis
- شرايط visual لكل TP
- متوسط R:R المرجّح بناءً على احتمالات الوصول
- تقييم الجودة: ✅ ممتاز / 🟡 مقبول / 🔴 ضعيف

---

## 📋 الملفات

```
wallstreet_bot/
├── WALLSTREET_PRO_BOT.py    ← الكود الرئيسي (2,235 سطر)
├── smart_risk.py             ← ✨ Module إدارة المخاطر (1,147 سطر)
├── requirements.txt          ← المكتبات
├── Procfile                  ← أمر تشغيل Railway
├── runtime.txt               ← Python 3.11.9
├── env.example               ← قالب المتغيرات
└── README.md                 ← هذا الملف
```

---

## 🔑 الـAPI Keys المطلوبة

### مطلوبة (Mandatory):
| API | المصدر | الرابط |
|---|---|---|
| **BOT_TOKEN** | @BotFather | https://t.me/botfather |
| **CLAUDE_API_KEY** | Anthropic | https://console.anthropic.com |
| **GEMINI_API_KEY** | Google AI | https://aistudio.google.com |
| **OPENAI_API_KEY** | OpenAI | https://platform.openai.com |

### مطلوبة للـStack الكامل:
| API | السعر | الرابط |
|---|---|---|
| **POLYGON_API_KEY** | $58/شهر (Stocks+Options Starter) | https://polygon.io/dashboard |
| **TRADING_ECON_KEY** | $99/شهر | https://tradingeconomics.com/api/ |
| **DATABENTO_API_KEY** | ~$50/شهر pay-as-you-go | https://databento.com |
| **FRED_API_KEY** | مجاني | https://fred.stlouisfed.org/docs/api/api_key.html |

> 💡 **البوت يعمل حتى لو APIs المدفوعة غير مكوّنة** — سيستخدم البيانات المجانية فقط (RSS + yfinance + CFTC + ForexFactory) ويتجاهل الباقي.
>
> 🛡️ **Smart Risk Management يعمل بدون أي API مدفوعة** — يعتمد على yfinance فقط.

---

## 🚀 النشر على Railway (خطوة بخطوة)

### 1. تحضير المجلد
```cmd
cd C:\WALLSTREET_PRO_BOT
```
انسخ كل الملفات الـ6 (بما فيها `smart_risk.py` الجديد) إلى هذا المجلد.

### 2. إنشاء البوت على Telegram
1. افتح [@BotFather](https://t.me/botfather)
2. أرسل `/newbot`
3. اختر اسم وusername
4. انسخ التوكن (مثل: `7234567890:AAH...`)

### 3. الحصول على API Keys
- **Claude:** https://console.anthropic.com → API Keys → Create Key
- **Gemini:** https://aistudio.google.com → Get API Key (مجاني)
- **OpenAI:** https://platform.openai.com → API Keys → Create new
- **Polygon:** https://polygon.io/dashboard/signup → Subscribe → Stocks Starter $29 + Options Starter $29
- **Trading Economics:** https://tradingeconomics.com/api → Subscribe → Standard $99 → احصل على `user:password`
- **Databento:** https://databento.com → Sign up → API Keys → اختياري
- **FRED:** https://fred.stlouisfed.org/docs/api/api_key.html → Request API Key (مجاني فوراً)

### 4. النشر على Railway
```cmd
railway init
# Project name: wallstreet-pro-bot

railway up
```

### 5. إضافة المتغيرات في Railway Dashboard
اذهب لـ **Variables** وأضف:
```
BOT_TOKEN              = توكن البوت
CLAUDE_API_KEY         = مفتاح Claude
GEMINI_API_KEY         = مفتاح Gemini
OPENAI_API_KEY         = مفتاح OpenAI
POLYGON_API_KEY        = مفتاح Polygon
TRADING_ECON_KEY       = user:password
DATABENTO_API_KEY      = مفتاح Databento (اختياري)
FRED_API_KEY           = مفتاح FRED
```

### 6. تأكد من Region
في Settings → Region → اختر **EU West Amsterdam** (أفضل اتصال للـAPIs).

### 7. تحقق من الـLogs
يجب أن ترى:
```
WALL STREET PRO BOT V4.1 — UNIFIED + SMART RISK — Running ✅
🧠 Claude:        ✅
💎 Gemini:        ✅
🤖 OpenAI:        ✅
📊 Polygon:       ✅
🌍 Trading Econ:  ✅
📈 Databento:     ✅
🏛️ FRED:          ✅
🛡️ Smart Risk:    ✅ (SL + TP + Position Sizing)
⏰ Schedulers ON
```

---

## 📱 الأوامر الكاملة

### 🎯 التوصيات
| الأمر | الوصف |
|---|---|
| `توصية` | توصية الذهب الكاملة (3 AIs + إجماع + **Smart Risk تلقائي**) |
| `توصية دولار` | توصية USD/DXY + Smart Risk |
| `أداء` | تقرير دقة التوصيات (يدعم TP3 الجديد) |

### 🛡️ Smart Risk Management ✨ جديد
| الأمر | الوصف |
|---|---|
| `مخاطر ذهب buy 2650` | تحليل مخاطر يدوي للذهب @ 2650 |
| `مخاطر ذهب sell 2680 5000` | مع رأس مال محدد ($5000) |
| `مخاطر دولار buy 105.20` | للـDXY |

**يعرض:**
- 3 مستويات SL مع تفسير كل واحد
- 3 أهداف TP مع احتمالات الوصول
- خريطة Danger Zones (تجنّب SL هنا)
- خريطة Reject Zones (مقاومة في الطريق)
- خطة Partial Close كاملة
- جدول Position Sizing
- ASCII charts للـR:R

### 📊 التحليل
| الأمر | الوصف |
|---|---|
| `تحليل` | تحليل سوق شامل |
| `فني` | RSI/MACD/EMA/BB/ICT |
| `سؤال [نصك]` | اسأل أي سؤال |

### 🐋 Smart Money
| الأمر | الوصف |
|---|---|
| `حيتان` | CFTC COT (Long/Short positions) |
| `خيارات` | Options Put/Call sentiment |
| `بنوك` | Fed bias + Yield Curve |
| `ماكرو` | FRED data (CPI/GDP/Fed Rate) |

### 📰 الأخبار
| الأمر | الوصف |
|---|---|
| `أخبار` | كل الأخبار |
| `أخبار ذهب` / `أخبار فوركس` | فلترة |
| `عاجل` | High-Impact فقط |

### 💹 البيانات
| الأمر | الوصف |
|---|---|
| `أسعار` | الأسعار اللحظية |
| `تقويم` | التقويم الاقتصادي |

### 📅 الاشتراكات
| الأمر | الوصف |
|---|---|
| `اشترك` | تقرير 7:00 ص (الرياض) |
| `اشترك 8 30` | مخصص (8:30 ص) |
| `يومي` | تشغيل التقرير الآن |
| `الغاء` | إلغاء |

---

## 🎯 ما الجديد في V4.1

| الميزة | V4 | V4.1 |
|---|---|---|
| Smart SL Suggester (3 مستويات) | ❌ | ✅ |
| Smart TP Suggester (3 أهداف) | ❌ | ✅ |
| Danger Zones Detection | ❌ | ✅ |
| Reject Zones Detection | ❌ | ✅ |
| Partial Close Strategy | ❌ | ✅ |
| Position Size Calculator | ❌ | ✅ |
| TP3 (Extended Target) | ❌ | ✅ |
| ASCII Charts للـR:R | ❌ | ✅ |
| Liquidity Map (شامل) | ❌ | ✅ |
| Round Numbers Detection | ❌ | ✅ |
| Equal Highs/Lows Detection | ❌ | ✅ |
| Risk Probability Scoring | ❌ | ✅ |
| أمر `مخاطر` للتحليل اليدوي | ❌ | ✅ |
| الأسطر | 2,064 | 3,382 (+1,318) |

---

## 🛡️ كيف يعمل Smart Risk Management

### المنهجية:
1. **تحليل خريطة السيولة** حول السعر:
   - Order Blocks (Bullish + Bearish)
   - Fair Value Gaps
   - Swing Highs/Lows (آخر 5 شموع pivot)
   - Equal Highs/Lows (تجمّعات stops)
   - Round Numbers (10/25/50/100 للذهب)
   - Bollinger Band Upper/Lower

2. **حساب SL ذكي** (3 مستويات):
   - Conservative = ورا Order Block + Buffer (ATR × 0.5)
   - Balanced = ورا Swing Point + Buffer (ATR × 0.3)
   - Aggressive = ATR × 0.9 (مع تحذير من Round Numbers)

3. **حساب TP بناءً على Liquidity Pools**:
   - TP1 = قبل أقرب Bearish/Bullish OB
   - TP2 = عند Equal Highs Cluster (تجمّع stops)
   - TP3 = عند Round Number كبير أو Weekly R/S

4. **حساب احتمالات الوصول** (heuristic):
   - مسافة بالـATR (أقرب = أعلى)
   - قوة الـTrend (EMA alignment)
   - RSI position
   - MACD direction

5. **خطة الخروج التدريجي**:
   - 50% عند TP1 + نقل SL لـBreakeven
   - 30% عند TP2 + نقل SL لـTP1
   - 20% عند TP3

---

## 📊 التكاليف الشهرية

### Stack الكامل:
- Polygon Stocks Starter + Options Starter: $58
- Trading Economics: $99
- Databento (~10GB): $50
- FRED: مجاني
- **المجموع: ~$207/شهر**

### Stack الأدنى (نفس البوت + Smart Risk يعمل):
- Polygon Currencies: $29
- FRED: مجاني
- **المجموع: $29/شهر**

> 🛡️ **Smart Risk Management يعمل حتى بدون أي API مدفوعة** — يستخدم yfinance فقط.

---

## ⚠️ تحذيرات مهمة

1. **هذا تحليل تعليمي**، ليس نصيحة استثمارية
2. **دقة التوصيات المتوقعة:** 55-65% (مستوى مؤسسي)
3. **إدارة المخاطر:** 1-2% مخاطرة لكل صفقة كحد أقصى
4. **لا تستخدم رأس مال لا يمكنك خسارته**
5. **الأسواق فيها عشوائية حقيقية** — لا يوجد نظام 100%
6. **Smart Risk يساعد لكن لا يضمن** — السوق قد يكسر أي مستوى

---

## 🔧 استكشاف الأخطاء

### البوت لا يرد على /start
- تحقق من `BOT_TOKEN` في Variables
- شاهد Logs في Railway

### `JobQueue غير متاح`
- تأكد من `requirements.txt` يحتوي `python-telegram-bot[job-queue]==20.7`

### `ImportError: smart_risk`
- تأكد إن ملف `smart_risk.py` مرفوع جنب `WALLSTREET_PRO_BOT.py` في نفس المجلد

### `Smart Risk failed: ...`
- غالباً مشكلة yfinance (مؤقتة)
- البوت لسه هيدّيك التوصية الأساسية بدون Smart Risk
- جرّب الأمر تاني بعد دقيقة

### `Polygon HTTP 401`
- مفتاح غير صحيح أو الاشتراك انتهى

### قاعدة البيانات تختفي بعد restart
- Railway Free Tier: الـcontainer غير دائم
- الحل: استخدم Railway Volumes ($5/شهر) أو ترقية للـHobby Plan

---

## 📞 الدعم

للاقتراحات والتعديلات، تواصل عبر Telegram أو افتح issue.

⚠️ _تحليلات تعليمية فقط — ليس نصيحة استثمارية._
