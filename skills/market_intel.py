"""
مهارت سوم (نسخه V2.5): اطلاعات بازار، تقویم اقتصادی فارکس، سنتیمنت، سشن‌ها و واگرایی SMT
Institutional Trading Bot V2.5 - Market Intelligence & Economic Calendar Shield
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd
import requests


class MarketIntelSkill:
    """
    کلاس تحلیل اطلاعات کلان بازار شامل:
    1. شاخص ترس و طمع (Fear & Greed) با نوار گرافیکی ۱۰ تایی
    2. تقویم اقتصادی فارکس (فیلتر پیشگیرانه اخبار قرمز USD برای طلا و کریپتو)
    3. تشخیص سشن‌های معاملاتی (London / NY Killzones & Asian Session)
    4. همبستگی پیرسون (Pearson Correlation) و واگرایی پول هوشمند (SMT Divergence)
    """

    def __init__(self, timeout_sec: int = 8) -> None:
        self.fng_url: str = "https://api.alternative.me/fng/?limit=1"
        self.calendar_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        self.timeout_sec: int = timeout_sec
        self._cached_calendar: List[Dict[str, Any]] = []
        self._calendar_fetched_date: str = ""

    # ==========================================================================
    # ۱. دریافت شاخص ترس و طمع و ساخت نوار گرافیکی ۱۰ تایی
    # ==========================================================================
    @staticmethod
    def build_sentiment_bar(value: int) -> str:
        val = max(0, min(100, int(value)))
        filled = int(round(val / 10.0))
        empty = 10 - filled

        if val <= 25:
            block = "🟥"
        elif val <= 45:
            block = "🟧"
        elif val <= 55:
            block = "🟨"
        elif val <= 75:
            block = "🟩"
        else:
            block = "🔥"

        return (block * filled) + ("⬜" * empty)

    def fetch_sentiment(self) -> Dict[str, Any]:
        default_val = 50
        default_cls = "Neutral"

        try:
            resp = requests.get(self.fng_url, timeout=self.timeout_sec)
            if resp.status_code == 200:
                payload = resp.json()
                data_list = payload.get("data", [])
                if data_list:
                    item = data_list[0]
                    val = int(item.get("value", default_val))
                    cls_name = str(item.get("value_classification", default_cls))
                    return {
                        "value": val,
                        "classification": cls_name,
                        "bar": self.build_sentiment_bar(val),
                        "is_live": True,
                    }
        except Exception:
            pass

        return {
            "value": default_val,
            "classification": default_cls,
            "bar": self.build_sentiment_bar(default_val),
            "is_live": False,
        }

    # ==========================================================================
    # ۲. فیلتر پیشگیرانه تقویم اقتصادی فارکس (High-Impact USD News Shield)
    # ==========================================================================
    def check_economic_news_shield(
        self,
        now_utc: Optional[datetime] = None,
        window_minutes: int = 30,
        simulated_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        بررسی وجود اخبار قرمز (High Impact) روی USD در بازه ۳۰ دقیقه قبل تا ۳۰ دقیقه بعد.
        اگر خبر مهمی در جریان باشد، سپر خبری فعال شده و ورود جدید مسدود می‌گردد.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        events = simulated_events if simulated_events is not None else self._get_weekly_calendar(now_utc)
        upcoming_high_impact: List[Dict[str, Any]] = []
        active_block_event: Optional[Dict[str, Any]] = None

        for ev in events:
            country = str(ev.get("country", "")).upper().strip()
            impact = str(ev.get("impact", "")).capitalize().strip()
            title = str(ev.get("title", "Economic Event")).strip()
            date_str = str(ev.get("date", "")).strip()

            if country not in ("USD", "ALL", "US") or impact != "High":
                continue

            try:
                ev_dt = datetime.fromisoformat(date_str).astimezone(timezone.utc)
            except Exception:
                continue

            diff_min = (ev_dt - now_utc).total_seconds() / 60.0

            # رویدادهای تا ۱۲ ساعت آینده برای نمایش در استاتوس
            if -60.0 <= diff_min <= 720.0:
                upcoming_high_impact.append({
                    "title": title,
                    "country": country,
                    "minutes_to_event": round(diff_min, 1),
                    "time_utc": ev_dt.strftime("%H:%M UTC"),
                })

            # بررسی پنجره ممنوعه (۳۰ دقیقه قبل تا ۳۰ دقیقه بعد از خبر قرمز)
            if abs(diff_min) <= float(window_minutes):
                active_block_event = {
                    "title": title,
                    "country": country,
                    "minutes_to_event": round(diff_min, 1),
                    "time_utc": ev_dt.strftime("%H:%M UTC"),
                }

        if active_block_event is not None:
            m_rem = active_block_event["minutes_to_event"]
            timing_str = f"{abs(m_rem):.0f} دقیقه تا انتشار" if m_rem >= 0 else f"{abs(m_rem):.0f} دقیقه پس از انتشار"
            summary_fa = f"🚨 قفل خبری فعال: {active_block_event['title']} ({timing_str})"
            return {
                "news_shield_active": True,
                "active_event": active_block_event,
                "upcoming_events": upcoming_high_impact[:3],
                "summary_fa": summary_fa,
            }

        if upcoming_high_impact:
            nxt = upcoming_high_impact[0]
            summary_fa = f"⚠️ خبر قرمز پیش‌رو: {nxt['title']} ({nxt['time_utc']})"
        else:
            summary_fa = "🟢 بدون خبر قرمز قریب‌الوقوع (ایمن برای ترید)"

        return {
            "news_shield_active": False,
            "active_event": None,
            "upcoming_events": upcoming_high_impact[:3],
            "summary_fa": summary_fa,
        }

    def _get_weekly_calendar(self, now_utc: datetime) -> List[Dict[str, Any]]:
        today_str = now_utc.strftime("%Y-%m-%d")
        if self._cached_calendar and self._calendar_fetched_date == today_str:
            return self._cached_calendar

        try:
            resp = requests.get(self.calendar_url, timeout=self.timeout_sec)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    self._cached_calendar = data
                    self._calendar_fetched_date = today_str
                    return data
        except Exception:
            pass
        return self._cached_calendar

    # ==========================================================================
    # ۳. تشخیص سشن‌های معاملاتی (London / NY Killzone & Asian Range)
    # ==========================================================================
    @staticmethod
    def check_killzone_session(utc_hour: Optional[int] = None) -> Dict[str, Any]:
        if utc_hour is None:
            utc_hour = datetime.now(timezone.utc).hour

        hour = int(utc_hour) % 24

        if 12 <= hour < 16:
            return {
                "in_killzone": True,
                "session_name": "LONDON_NY_OVERLAP",
                "session_fa": "🔥 هم‌پوشانی لندن و نیویورک (حداکثر نقدینگی)",
                "hour_utc": hour,
                "score_bonus": 10.0,
            }
        if 7 <= hour < 12:
            return {
                "in_killzone": True,
                "session_name": "LONDON_KILLZONE",
                "session_fa": "🇬🇧 سشن لندن (Killzone فعال)",
                "hour_utc": hour,
                "score_bonus": 10.0,
            }
        if 16 <= hour <= 20:
            return {
                "in_killzone": True,
                "session_name": "NEW_YORK_KILLZONE",
                "session_fa": "🇺🇸 سشن نیویورک (Killzone فعال)",
                "hour_utc": hour,
                "score_bonus": 10.0,
            }
        if 0 <= hour < 7:
            return {
                "in_killzone": False,
                "session_name": "ASIAN_ACCUMULATION",
                "session_fa": "🌏 سشن آسیا (فاز تجمیع نقدینگی)",
                "hour_utc": hour,
                "score_bonus": 3.0,
            }

        return {
            "in_killzone": False,
            "session_name": "OFF_PEAK_SESSION",
            "session_fa": "🌙 خارج از سشن اصلی (نقدینگی کم)",
            "hour_utc": hour,
            "score_bonus": 2.0,
        }

    # ==========================================================================
    # ۴. محاسبه همبستگی پیرسون و تشخیص واگرایی پول هوشمند (SMT Divergence)
    # ==========================================================================
    def analyze_correlation_and_smt(
        self,
        df_btc: pd.DataFrame,
        df_eth: pd.DataFrame,
        lookback: int = 20,
    ) -> Dict[str, Any]:
        default_res = {
            "pearson_r": 0.85,
            "smt_divergence": "NONE",
            "bullish_smt": False,
            "bearish_smt": False,
            "smt_score_bonus": 0.0,
        }

        if df_btc is None or df_eth is None:
            return default_res
        if len(df_btc) < lookback or len(df_eth) < lookback:
            return default_res

        b_df = df_btc.tail(lookback).reset_index(drop=True)
        e_df = df_eth.tail(lookback).reset_index(drop=True)

        b_close = b_df["close"].astype(float).values
        e_close = e_df["close"].astype(float).values

        b_ret = pd.Series(b_close).pct_change().dropna().values
        e_ret = pd.Series(e_close).pct_change().dropna().values

        pearson_r = 0.85
        if len(b_ret) > 3 and np.std(b_ret) > 1e-12 and np.std(e_ret) > 1e-12:
            corr_matrix = np.corrcoef(b_ret, e_ret)
            if not np.isnan(corr_matrix[0, 1]):
                pearson_r = float(np.clip(corr_matrix[0, 1], -1.0, 1.0))

        mid = lookback // 2
        btc_prev_low = float(np.min(b_df["low"].iloc[:mid]))
        btc_curr_low = float(np.min(b_df["low"].iloc[mid:]))
        eth_prev_low = float(np.min(e_df["low"].iloc[:mid]))
        eth_curr_low = float(np.min(e_df["low"].iloc[mid:]))

        btc_prev_high = float(np.max(b_df["high"].iloc[:mid]))
        btc_curr_high = float(np.max(b_df["high"].iloc[mid:]))
        eth_prev_high = float(np.max(e_df["high"].iloc[:mid]))
        eth_curr_high = float(np.max(e_df["high"].iloc[mid:]))

        bullish_smt = (btc_curr_low < btc_prev_low and eth_curr_low >= eth_prev_low) or (
            eth_curr_low < eth_prev_low and btc_curr_low >= btc_prev_low
        )
        bearish_smt = (btc_curr_high > btc_prev_high and eth_curr_high <= eth_prev_high) or (
            eth_curr_high > eth_prev_high and btc_curr_high <= btc_prev_high
        )

        smt_type = "NONE"
        bonus = 0.0
        if bullish_smt and not bearish_smt:
            smt_type = "BULLISH_SMT"
            bonus = 8.0
        elif bearish_smt and not bullish_smt:
            smt_type = "BEARISH_SMT"
            bonus = 8.0

        return {
            "pearson_r": round(pearson_r, 4),
            "smt_divergence": smt_type,
            "bullish_smt": bool(bullish_smt),
            "bearish_smt": bool(bearish_smt),
            "smt_score_bonus": bonus,
        }