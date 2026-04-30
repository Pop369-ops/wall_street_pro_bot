# 🌟 WALL STREET PRO BOT V4 — Unified Edition

بوت Telegram احترافي يدمج 3 AIs (Claude + Gemini + OpenAI) مع بيانات السوق الحقيقية لتقديم تحليلات وتوصيات تداول الذهب والفوركس بمستوى مؤسسي.

---

## ✨ المميزات

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

---

## 📋 الملفات

```
wallstreet_bot/
├── WALLSTREET_PRO_BOT.py    ← الكود الرئيسي (2,064 سطر)
├── requirements.txt          ← المكتبات
├── Procfile                  ← أمر تشغيل Railway
├── runtime.txt               ← Python 3.11.9
├── .env.example              ← قالب المتغيرات
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

---

## 🚀 النشر على Railway (خطوة بخطوة)

### 1. تحضير المجلد
```cmd
cd C:\WALLSTREET_PRO_BOT
```
انسخ كل الملفات الـ4 (`.py`, `.txt`, `Procfile`) إلى هذا المجلد.

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
WALL STREET PRO BOT V4 — UNIFIED — Running ✅
🧠 Claude:        ✅
💎 Gemini:        ✅
🤖 OpenAI:        ✅
📊 Polygon:       ✅
🌍 Trading Econ:  ✅
📈 Databento:     ✅
🏛️ FRED:          ✅
⏰ Schedulers ON
```

---

## 📱 الأوامر الكاملة

### 🎯 التوصيات
| الأمر | الوصف |
|---|---|
| `توصية` | توصية الذهب الكاملة (3 AIs + إجماع + SL/TP) |
| `توصية دولار` | توصية USD/DXY |
| `أداء` | تقرير دقة التوصيات السابقة |

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

## 🎯 ما الجديد عن V3

| الميزة | V3 | V4 |
|---|---|---|
| Polygon Options API | ❌ | ✅ |
| Trading Economics | ❌ | ✅ |
| Databento CME | ❌ | ✅ |
| FRED Macro | ❌ | ✅ |
| تحليل فني (RSI/MACD/EMA/BB) | ❌ | ✅ |
| ICT Order Blocks + FVG | ❌ | ✅ |
| SQLite Memory | ❌ | ✅ |
| Performance Tracking | ❌ | ✅ |
| ذاكرة المحادثة لكل user | ❌ | ✅ |
| تتبع آخر توصية في الـprompt | ❌ | ✅ |
| Cache Layer (60s) | ❌ | ✅ |
| الأسطر | 1,198 | 2,064 |

---

## 📊 التكاليف الشهرية

### Stack الكامل:
- Polygon Stocks Starter + Options Starter: $58
- Trading Economics: $99
- Databento (~10GB): $50
- FRED: مجاني
- **المجموع: ~$207/شهر**

### Stack الأدنى (نفس البوت يعمل):
- Polygon Currencies: $29
- FRED: مجاني
- **المجموع: $29/شهر**

> البوت يكشف تلقائياً أي APIs مكوّنة ويستخدم المتاح.

---

## ⚠️ تحذيرات مهمة

1. **هذا تحليل تعليمي**، ليس نصيحة استثمارية
2. **دقة التوصيات المتوقعة:** 55-65% (مستوى مؤسسي)
3. **إدارة المخاطر:** 1-2% مخاطرة لكل صفقة كحد أقصى
4. **لا تستخدم رأس مال لا يمكنك خسارته**
5. **الأسواق فيها عشوائية حقيقية** — لا يوجد نظام 100%

---

## 🔧 استكشاف الأخطاء

### البوت لا يرد على /start
- تحقق من `BOT_TOKEN` في Variables
- شاهد Logs في Railway

### `JobQueue غير متاح`
- تأكد من `requirements.txt` يحتوي `python-telegram-bot[job-queue]==20.7`

### `Polygon HTTP 401`
- مفتاح غير صحيح أو الاشتراك انتهى

### `FRED غير مكوّن`
- ابدأ الحصول على المفتاح من https://fred.stlouisfed.org/docs/api/api_key.html (مجاني)

### قاعدة البيانات تختفي بعد restart
- Railway Free Tier: الـcontainer غير دائم
- الحل: استخدم Railway Volumes ($5/شهر) أو ترقية للـHobby Plan

---

## 📞 الدعم

للاقتراحات والتعديلات، تواصل عبر Telegram أو افتح issue.

⚠️ _تحليلات تعليمية فقط — ليس نصيحة استثمارية._
