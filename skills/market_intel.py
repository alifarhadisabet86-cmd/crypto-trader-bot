"""
مهارت سوم: هوش بازار، سنتیمنت (Fear & Greed)، Killzones، همبستگی و واگرایی SMT
Institutional Trading Bot V2 - Market Intelligence & Macro Context Skill
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd
import requests


class MarketIntelSkill:
    """
    کلاس تحلیل سنتیمنت بازار، تشخیص سشن‌های معاملاتی (Killzones) و
    محاسبه همبستگی پیرسون و واگرایی پول هوشمند (SMT Divergence) بین BTC و ETH.
    """

    def __init__(self) -> None:
        self.fng_url: str = "https://api.alternative.me/fng/?limit=1"
        self.correlation_window: int = 60
        self.smt_window: int = 15

    @staticmethod
    def _build_sentiment_bar(value: int) -> str:
        """
        ساخت نوار گرافیکی ۱۰ تایی بر اساس عدد شاخص ترس و طمع (۰ تا ۱۰۰):
        - زیر ۴۰ (ترس): 🟥
        - بین ۴۰ تا ۶۰ (خنثی): 🟨
        - بالای ۶۰ (طمع): 🟩
        """
        clamped = max(0, min(100, int(value)))
        filled_blocks = int(round(clamped / 10.0))
        empty_blocks = 10 - filled_blocks

        if clamped < 40:
            active_char = "🟥"
        elif clamped <= 60:
            active_char = "🟨"
        else:
            active_char = "🟩"

        return (active_char * filled_blocks) + ("⬜" * empty_blocks)

    def fetch_sentiment(self) -> Dict[str, Any]:
        """
        دریافت شاخص Fear & Greed از API رسمی و ساخت نوار گرافیکی ۱۰ تایی.
        در صورت عدم دسترسی به اینترنت یا تایم‌اوت، مقدار خنثی (۵۰) برمی‌گرداند.
        """
        try:
            resp = requests.get(self.fng_url, timeout=6)
            if resp.status_code == 200:
                payload = resp.json()
                data_list = payload.get("data", [])
                if data_list and len(data_list) > 0:
                    item = data_list[0]
                    val = int(item.get("value", 50))
                    classification = str(item.get("value_classification", "Neutral"))
                    bar = self._build_sentiment_bar(val)
                    return {
                        "value": val,
                        "classification": classification,
                        "bar": bar,
                        "valid": True,
                    }
        except Exception as e:
            print(f"⚠️ [MarketIntelSkill] Failed to fetch Fear & Greed Index: {e}")

        return {
            "value": 50,
            "classification": "Neutral",
            "bar": self._build_sentiment_bar(50),
            "valid": False,
        }

    def check_killzone_session(self, utc_hour: Optional[int] = None) -> Dict[str, Any]:
        """
        تشخیص سشن معاملاتی بر اساس ساعت UTC:
        - لندن (7 <= hour <= 11): پاداش +8
        - هم‌پوشانی نیویورک (12 <= hour <= 17): پاداش +10
        - آسیا (0 <= hour <= 6): پاداش +3
        - سایر ساعات (LATE_US_QUIET): پاداش 0
        """
        hour = utc_hour if utc_hour is not None else datetime.now(timezone.utc).hour
        hour = int(hour) % 24

        if 7 <= hour <= 11:
            return {
                "session": "LONDON_KILLZONE",
                "score_bonus": 8.0,
                "utc_hour": hour,
                "active_killzone": True,
            }
        if 12 <= hour <= 17:
            return {
                "session": "NY_OVERLAP_KILLZONE",
                "score_bonus": 10.0,
                "utc_hour": hour,
                "active_killzone": True,
            }
        if 0 <= hour <= 6:
            return {
                "session": "ASIA_SESSION",
                "score_bonus": 3.0,
                "utc_hour": hour,
                "active_killzone": False,
            }
        return {
            "session": "LATE_US_QUIET",
            "score_bonus": 0.0,
            "utc_hour": hour,
            "active_killzone": False,
        }

    def analyze_correlation_and_smt(
        self,
        df_btc_15m: pd.DataFrame,
        df_eth_15m: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        محاسبه ضریب همبستگی پیرسون بین BTC و ETH در ۶۰ کندل ۱۵ دقیقه
        و بررسی واگرایی SMT در ۱۵ کندل اخیر (BULLISH_SMT یا BEARISH_SMT).
        """
        default_res: Dict[str, Any] = {
            "pearson_corr": 0.85,
            "smt_divergence": "NONE",
            "bullish_smt": False,
            "bearish_smt": False,
            "details": "Insufficient BTC/ETH data for SMT analysis",
        }

        if (
            df_btc_15m is None
            or df_eth_15m is None
            or len(df_btc_15m) < self.smt_window
            or len(df_eth_15m) < self.smt_window
        ):
            return default_res

        # هم‌تراز کردن طول دو دیتافریم
        min_len = min(len(df_btc_15m), len(df_eth_15m))
        corr_len = min(self.correlation_window, min_len)

        btc_closes = df_btc_15m["close"].astype(float).iloc[-corr_len:].values
        eth_closes = df_eth_15m["close"].astype(float).iloc[-corr_len:].values

        # ۱. محاسبه ضریب همبستگی پیرسون روی تغییرات قیمت (یا قیمت‌های بسته شدن)
        pearson_corr = 0.85
        if corr_len >= 10:
            btc_std = float(np.std(btc_closes))
            eth_std = float(np.std(eth_closes))
            if btc_std > 1e-12 and eth_std > 1e-12:
                corr_matrix = np.corrcoef(btc_closes, eth_closes)
                val = float(corr_matrix[0, 1])
                if not np.isnan(val):
                    pearson_corr = round(val, 4)

        # ۲. بررسی واگرایی SMT در ۱۵ کندل اخیر (تقسیم به نیمه اول و نیمه دوم)
        smt_len = min(self.smt_window, min_len)
        half = max(3, smt_len // 2)

        btc_lows = df_btc_15m["low"].astype(float).iloc[-smt_len:].values
        eth_lows = df_eth_15m["low"].astype(float).iloc[-smt_len:].values
        btc_highs = df_btc_15m["high"].astype(float).iloc[-smt_len:].values
        eth_highs = df_eth_15m["high"].astype(float).iloc[-smt_len:].values

        btc_low_prev, btc_low_rec = float(np.min(btc_lows[:half])), float(np.min(btc_lows[half:]))
        eth_low_prev, eth_low_rec = float(np.min(eth_lows[:half])), float(np.min(eth_lows[half:]))

        btc_high_prev, btc_high_rec = float(np.max(btc_highs[:half])), float(np.max(btc_highs[half:]))
        eth_high_prev, eth_high_rec = float(np.max(eth_highs[:half])), float(np.max(eth_highs[half:]))

        # Bullish SMT: یکی کف پایین‌تر (LL) زده و دیگری کف بالاتر (HL) ساخته است
        bullish_smt = (
            (btc_low_rec < btc_low_prev and eth_low_rec > eth_low_prev)
            or (eth_low_rec < eth_low_prev and btc_low_rec > btc_low_prev)
        )

        # Bearish SMT: یکی سقف بالاتر (HH) زده و دیگری سقف پایین‌تر (LH) ساخته است
        bearish_smt = (
            (btc_high_rec > btc_high_prev and eth_high_rec < eth_high_prev)
            or (eth_high_rec > eth_high_prev and btc_high_rec < btc_high_prev)
        )

        smt_type = "NONE"
        details = f"BTC/ETH Corr: {pearson_corr:.2f} | No SMT divergence"

        if bullish_smt and not bearish_smt:
            smt_type = "BULLISH_SMT"
            details = f"Bullish SMT detected at swing lows (Corr: {pearson_corr:.2f})"
        elif bearish_smt and not bullish_smt:
            smt_type = "BEARISH_SMT"
            details = f"Bearish SMT detected at swing highs (Corr: {pearson_corr:.2f})"

        return {
            "pearson_corr": pearson_corr,
            "smt_divergence": smt_type,
            "bullish_smt": bool(bullish_smt),
            "bearish_smt": bool(bearish_smt),
            "details": details,
        }