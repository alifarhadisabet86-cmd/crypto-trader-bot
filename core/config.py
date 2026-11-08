"""
تنظیمات مرکزی، واچ‌لیست، مدیریت ریسک، دروازه ۵۰ معامله و فرمت‌بندی قیمت‌ها (Core Configuration V2.6 Pro)
Institutional Trading Bot V2.6 Pro - Centralized Configuration
"""

import os
from pathlib import Path
from typing import Dict, Any

# مسیرهای پایه پروژه
BASE_DIR: Path = Path(__file__).resolve().parent.parent
STATE_DIR: Path = BASE_DIR / "state"
CHARTS_DIR: Path = STATE_DIR / "charts"

STATE_DIR.mkdir(parents=True, exist_ok=True)
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# ۱. واچ‌لیست ۵ دارایی اصلی به همراه دقت اعشار استاندارد و لینک چارت زنده
WATCHLIST: Dict[str, Dict[str, Any]] = {
    "BTC": {
        "symbol": "BTC/USDT",
        "name": "Bitcoin",
        "decimals": 1,
        "correlated_group": "CRYPTO_MAJOR",
        "tv_url": "https://www.tradingview.com/chart/?symbol=KUCOIN:BTCUSDT",
    },
    "ETH": {
        "symbol": "ETH/USDT",
        "name": "Ethereum",
        "decimals": 2,
        "correlated_group": "ALT_HIGH_BETA",
        "tv_url": "https://www.tradingview.com/chart/?symbol=KUCOIN:ETHUSDT",
    },
    "SOL": {
        "symbol": "SOL/USDT",
        "name": "Solana",
        "decimals": 2,
        "correlated_group": "ALT_HIGH_BETA",
        "tv_url": "https://www.tradingview.com/chart/?symbol=KUCOIN:SOLUSDT",
    },
    "XRP": {
        "symbol": "XRP/USDT",
        "name": "Ripple",
        "decimals": 4,
        "correlated_group": "ALT_HIGH_BETA",
        "tv_url": "https://www.tradingview.com/chart/?symbol=KUCOIN:XRPUSDT",
    },
    "XAU": {
        "symbol": "PAXG/USDT",
        "name": "Gold (XAUUSD)",
        "decimals": 2,
        "correlated_group": "SAFE_HAVEN_GOLD",
        "tv_url": "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD",
    },
}

# لینک‌های مستقیم پنل کاربری صرافی و بروکر برای دکمه‌های شیشه‌ای تلگرام
BROKER_URLS: Dict[str, str] = {
    "bitunix": "https://www.bitunix.com/ftrade",
    "opofinance": "https://my.opofinance.com/",
    "kucoin": "https://www.kucoin.com/trade/BTC-USDT",
    "tradingview_gold": "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD",
}

# ۲. تایم‌فریم‌های چهارگانه تحلیلی
TIMEFRAMES: Dict[str, str] = {
    "HTF_STRUCTURE": "4h",
    "MTF_REGIME": "1h",
    "LTF_SETUP": "15m",
    "MICRO_TRIGGER": "5m",
}

# ۳. تنظیمات صرافی مرجع دیتا و قوانین اجرایی
EXCHANGE_CONFIG: Dict[str, Any] = {
    "exchange_id": "kucoin",
    "timeout_ms": 15000,
    "enable_rate_limit": True,
    "MAKER_FEE_RATE": 0.0002,
    "TAKER_FEE_RATE": 0.0006,
    "MAX_SPREAD_TO_TP_RATIO": 0.05,
    "MAKER_OFFSET_ATR_5M": 0.10,
    "SL_MIN_ATR_MULT": 0.85,
    "SL_MAX_ATR_MULT": 2.20,
    "SL_BUFFER_ATR_MULT": 0.20,
    "MIN_SL_PCT": 0.0035,
    "TP1_R_MULTIPLE": 1.15,
    "TP1_CLOSE_PCT": 0.0,
    "TP1_LOCK_OFFSET_R": 0.25,
    "MIN_RR_RANGING": 1.75,
    "MIN_RR_TRENDING": 2.30,
}
EXECUTION_RULES: Dict[str, Any] = EXCHANGE_CONFIG
EXCHANGE_RULES: Dict[str, Any] = EXCHANGE_CONFIG

# ۴. قوانین مدیریت سرمایه، ۵ اسلات، مدارشکن روزانه/هفتگی و دروازه ۵۰ معامله
RISK_CONFIG: Dict[str, Any] = {
    "INITIAL_BALANCE_USDT": 1000.0,
    "DEFAULT_LEVERAGE": 5,
    "MAX_OPEN_POSITIONS": 5,
    "MAX_CORRELATED_ALTS": 3,
    "STANDARD_SLOTS": 3,
    "GOLDEN_SLOTS_MIN_SCORE": 80.0,
    "MIN_CONFLUENCE_SCORE": 68.0,
    "TRADE_COOLDOWN_MINUTES": 60,
    "BASE_RISK_PCT": 0.50,
    "WIN_STREAK_RISK_PCT": 0.80,
    "LOSS_STREAK_RISK_PCT": 0.25,
    "MAX_DAILY_DRAWDOWN_PCT": 2.0,
    "MAX_WEEKLY_DRAWDOWN_PCT": 5.0,
    "MAX_MARGIN_USAGE_PER_TRADE_PCT": 25.0,
    "MAKER_FEE_RATE": 0.0002,
    "TAKER_FEE_RATE": 0.0006,
    "MAX_SPREAD_TO_TP_RATIO": 0.05,
    "PAPER_GATE_TARGET_TRADES": 50,
}
RISK_RULES: Dict[str, Any] = RISK_CONFIG

# ۵. تنظیمات امتیازدهی و شبیه‌ساز مونت‌کارلو (ماشین زمان)
TIMEMACHINE_CONFIG: Dict[str, Any] = {
    "NUM_PATHS": 1000,
    "HORIZON_CANDLES_15M": 16,
    "MIN_WIN_RATE_PCT": 42.0,
    "MIN_EXPECTED_VALUE_R": 0.05,
    "MONTE_CARLO_PATHS": 1000,
    "MONTE_CARLO_HORIZON_CANDLES": 16,
    "MIN_MONTE_CARLO_WINRATE": 42.0,
    "MIN_CONFLUENCE_SCORE": 68.0,
    "GOLDEN_CONFLUENCE_SCORE": 80.0,
    "SNIPER_LIMIT_MIN_SCORE": 75.0,
}
TIMEMACHINE_RULES: Dict[str, Any] = TIMEMACHINE_CONFIG
SCORING_RULES: Dict[str, Any] = TIMEMACHINE_CONFIG

# ۶. تنظیمات یادگیری ماشین (ML Feedback Defaults)
DEFAULT_COIN_MULTIPLIERS: Dict[str, float] = {coin: 1.0 for coin in WATCHLIST.keys()}
DEFAULT_REGIME_WEIGHTS: Dict[str, float] = {
    "TRENDING_BULL": 1.0,
    "TRENDING_BEAR": 1.0,
    "RANGING": 1.0,
}

# ۷. تنظیمات تلگرام
TELEGRAM_CONFIG: Dict[str, str] = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
}


def format_price(value: float | int | None, coin: str = "BTC") -> str:
    """
    فرمت‌بندی و گرد کردن هوشمند قیمت بر اساس دارایی برای جلوگیری از اعشارهای طولانی در تلگرام.
    - BTC: 1 رقم اعشار (مثلاً 79200.7)
    - ETH, SOL, XAU: 2 رقم اعشار (مثلاً 3986.98)
    - XRP: 4 رقم اعشار (مثلاً 1.2951)
    """
    if value is None:
        return "0.00"
    try:
        val = float(value)
    except (ValueError, TypeError):
        return str(value)

    clean_coin = str(coin).strip().upper().replace("/USDT", "").replace("PAXG", "XAU")
    decimals = WATCHLIST.get(clean_coin, {}).get("decimals", 2)

    if decimals == 0:
        return f"{val:.0f}"
    return f"{val:.{decimals}f}"
