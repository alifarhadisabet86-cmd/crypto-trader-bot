"""
تنظیمات مرکزی و قوانین معاملاتی ربات (Single Source of Truth)
Institutional Trading Bot V2 - Core Configuration
"""

import os
from pathlib import Path
from typing import Dict, Any

# ==============================================================================
# ۱. مسیرهای پایه سیستم (سازگار با Windows و Linux در GitHub Actions)
# ==============================================================================
BASE_DIR: Path = Path(__file__).resolve().parent.parent
STATE_DIR: Path = BASE_DIR / "state"
CHARTS_DIR: Path = STATE_DIR / "charts"

# اطمینان از وجود پوشه‌های حافظه و چارت در لحظه ایمپورت
STATE_DIR.mkdir(parents=True, exist_ok=True)
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# ۲. سبد دارایی‌های هدف و گروه‌بندی همبستگی (WATCHLIST)
# ==============================================================================
WATCHLIST: Dict[str, Dict[str, Any]] = {
    "BTC": {
        "symbol": "BTC/USDT",
        "category": "CRYPTO_MAJOR",
        "correlation_group": "CRYPTO_HIGH",
        "min_tick": 0.1,
    },
    "ETH": {
        "symbol": "ETH/USDT",
        "category": "CRYPTO_MAJOR",
        "correlation_group": "CRYPTO_HIGH",
        "min_tick": 0.01,
    },
    "SOL": {
        "symbol": "SOL/USDT",
        "category": "CRYPTO_ALT",
        "correlation_group": "CRYPTO_HIGH",
        "min_tick": 0.01,
    },
    "XRP": {
        "symbol": "XRP/USDT",
        "category": "CRYPTO_ALT",
        "correlation_group": "CRYPTO_MED",
        "min_tick": 0.0001,
    },
    "XAU": {
        "symbol": "PAXG/USDT",  # معادل دقیق ۱ اونس طلای جهانی (XAUUSD) در صرافی
        "category": "COMMODITY",
        "correlation_group": "SAFE_HAVEN",
        "min_tick": 0.1,
    },
}


# ==============================================================================
# ۳. ساختار تایم‌فریم‌های مولتی‌تایم‌فریم (TIMEFRAMES)
# ==============================================================================
TIMEFRAMES: Dict[str, str] = {
    "HTF_STRUCTURE": "4h",   # تایم‌فریم ساختار کلان و بایاس اصلی
    "MTF_REGIME": "1h",      # تایم‌فریم تشخیص رژیم بازار (روند یا رنج) و فیلتر شوک خبری
    "LTF_SETUP": "15m",      # تایم‌فریم استخراج FVG، شکار نقدینگی (Sweep) و ناحیه ورود
    "MICRO_TRIGGER": "5m",   # تایم‌فریم تاییدیه کندلی و ماشه شلیک (CHoCH / Pinbar / Engulfing)
}


# ==============================================================================
# ۴. قوانین مدیریت ریسک، سرمایه و ماتریس اسلات‌ها (RISK_RULES)
# ==============================================================================
RISK_RULES: Dict[str, Any] = {
    "initial_balance_usdt": 1000.0,       # موجودی اولیه پرتفوی (دلار/تتر)
    "base_risk_per_trade_pct": 0.5,       # ریسک پایه در هر معامله (۰.۵٪ در حالت عادی)
    "winning_streak_risk_pct": 0.8,       # افزایش ریسک به ۰.۸٪ پس از ۲ برد متوالی (یا حالت تهاجمی)
    "losing_streak_risk_pct": 0.25,       # کاهش ریسک به ۰.۲۵٪ پس از ۲ باخت متوالی (یا حالت محافظه‌کارانه)
    "max_daily_drawdown_pct": 2.0,        # مدارشکن روزانه (قفل شدن معاملات جدید در صورت ۲٪ ضرر روزانه)
    "max_concurrent_positions": 5,        # حداکثر ۵ پوزیشن باز همزمان
    "max_normal_score_slots": 2,          # حداکثر ۲ اسلات برای ستاپ‌های با امتیاز عادی (۶۵ تا ۷۴.۹)
    "golden_score_threshold": 75.0,       # حد نصاب ستاپ‌های طلایی برای استفاده از ۳ اسلات رزرو شده
    "max_crypto_correlated_same_side": 3, # حداکثر ۳ پوزیشن هم‌جهت فعال در گروه کریپتو (سپر همبستگی)
    "max_leverage": 10,                   # حداکثر اهرم مجاز
    "max_margin_per_trade_pct": 25.0,     # حداکثر مارجین درگیر در یک معامله (۲۵٪ کل موجودی)
}


# ==============================================================================
# ۵. قوانین اجرایی بروکر، کارمزدها و گارد اسپرد (EXECUTION_RULES)
# ==============================================================================
EXECUTION_RULES: Dict[str, Any] = {
    "primary_crypto_exchange": "bitunix", # صرافی هدف برای اجرای سفارشات کریپتو
    "cloud_data_feed": "kucoin",          # فید دیتای کلود (بدون محدودیت IP برای سرورهای گیت‌هاب)
    "gold_broker": "opofinance",          # بروکر مرجع برای معاملات طلا
    "entry_order_type": "LIMIT",          # نوع سفارش ورود و تارگت (Maker)
    "sl_order_type": "MARKET",            # نوع سفارش حد ضرر (Taker)
    "maker_fee": 0.0002,                  # کارمزد Maker: ۰.۰۲٪
    "taker_fee": 0.0006,                  # کارمزد Taker: ۰.۰۶٪
    "max_spread_to_target_ratio": 0.05,   # گارد اسپرد: حداکثر نسبت اسپرد به کل فاصله تارگت (۵٪)
}


# ==============================================================================
# ۶. قوانین امتیازدهی فازی و ماشین زمان (SCORING_RULES)
# ==============================================================================
SCORING_RULES: Dict[str, Any] = {
    "min_score_to_trade": 65.0,           # حداقل امتیاز فازی برای تایید ستاپ
    "full_size_score_threshold": 80.0,    # حد نصاب امتیاز برای ورود با ۱۰۰٪ حجم استاندارد
    "min_timemachine_winrate": 42.0,      # حداقل وین‌ریت مورد نیاز در شبیه‌ساز مونت‌کارلو (۴۲٪)
    "min_timemachine_ev_r": 0.05,         # حداقل امید ریاضی (Expected Value) بر حسب R
    "target_sample_size_paper": 50,       # تعداد معاملات هدف برای ارزیابی آماری پرتفوی
}


# ==============================================================================
# ۷. ضرایب پایه یادگیری ماشین بیزی (ML DEFAULT WEIGHTS)
# ==============================================================================
DEFAULT_REGIME_WEIGHTS: Dict[str, float] = {
    "TRENDING_BULL": 1.0,
    "TRENDING_BEAR": 1.0,
    "RANGING": 1.0,
}

DEFAULT_COIN_MULTIPLIERS: Dict[str, float] = {
    coin: 1.0 for coin in WATCHLIST.keys()
}


# ==============================================================================
# ۸. تنظیمات ارتباطی اتاق فرمان تلگرام (TELEGRAM_CONFIG)
# ==============================================================================
TELEGRAM_CONFIG: Dict[str, str] = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
}