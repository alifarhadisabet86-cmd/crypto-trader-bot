"""
مهارت پنجم (نسخه V2.6 Pro): ماشه ورود میکرو ۵ دقیقه + فیلتر حجم پول هوشمند (5m RVOL)
Institutional Trading Bot V2.6 Pro - 5m Micro Entry Trigger, Volume Confirmation & Maker Price Optimizer
"""

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

from core.config import EXCHANGE_CONFIG, TIMEMACHINE_CONFIG


class EntryTriggerSkill:
    """
    کلاس بررسی کندل‌های تایم‌فریم 5m برای صدور دستور شلیک نهایی،
    فیلتر جلوگیری از ورود وسط کندل‌های شارپ/ریزشی (Anti-Falling-Knife)،
    فیلتر تایید حجم پول هوشمند (5m RVOL) برای حذف فیک‌اوت‌های کم‌حجم،
    و تعیین قیمت ورود بهینه Limit Maker (0.10 * ATR_5m بهتر از قیمت مارکت).
    """

    def __init__(self) -> None:
        self.wick_rejection_ratio: float = 0.45
        self.engulf_body_ratio: float = 0.55
        self.sniper_score_threshold: float = float(TIMEMACHINE_CONFIG.get("SNIPER_LIMIT_MIN_SCORE", 75.0))
        self.maker_offset_atr_mult: float = float(EXCHANGE_CONFIG.get("MAKER_OFFSET_ATR_5M", 0.10))
        self.min_standard_rvol_5m: float = 1.12
        self.min_sniper_rvol_5m: float = 0.95

    def evaluate_entry_trigger(
        self,
        df_5m: pd.DataFrame,
        candidate_side: str,
        confluence_score: float,
        active_fvg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        بررسی شروط کندلی ۵ دقیقه (5M_MICRO_CHOCH, 5M_PINBAR, 5M_ENGULFING)، شرط LIMIT_SNIPER_FVG
        و فیلتر حجم نسبی ۵ دقیقه (RVOL). محاسبه قیمت دقیق سفارش Limit (Maker).
        """
        side = str(candidate_side).strip().upper()

        if df_5m is None or len(df_5m) < 5 or side not in ("LONG", "SHORT"):
            return {
                "triggered": False,
                "trigger_type": "NONE",
                "order_type": "LIMIT",
                "side": side,
                "market_price": 0.0,
                "limit_entry_price": 0.0,
                "atr_5m": 0.0,
                "rvol_5m": 0.0,
                "details": "Insufficient 5m data or invalid candidate side",
            }

        opens = df_5m["open"].astype(float).values
        highs = df_5m["high"].astype(float).values
        lows = df_5m["low"].astype(float).values
        closes = df_5m["close"].astype(float).values
        vols = (
            df_5m["volume"].astype(float).values
            if "volume" in df_5m.columns
            else np.ones(len(df_5m), dtype=float)
        )

        if "atr" in df_5m.columns and not df_5m["atr"].isna().all():
            atr_5m = float(df_5m["atr"].iloc[-1])
        else:
            atr_5m = float((df_5m["high"] - df_5m["low"]).tail(14).mean())

        atr_5m = max(atr_5m, 1e-8)
        market_price = float(closes[-1])

        # محاسبه حجم نسبی ۵ دقیقه (RVOL) نسبت به میانگین ۲۰ کندل اخیر
        avg_vol_20 = max(float(np.mean(vols[-min(20, len(vols)):])), 1e-8)
        recent_peak_vol = float(max(vols[-1], vols[-2]))
        rvol_5m = recent_peak_vol / avg_vol_20

        req_rvol = (
            self.min_sniper_rvol_5m
            if float(confluence_score) >= self.sniper_score_threshold
            else self.min_standard_rvol_5m
        )
        volume_confirmed = rvol_5m >= req_rvol

        # مشخصات کندل فعلی (-1)، کندل قبلی (-2) و دو کندل قبل (-3)
        c_open, c_high, c_low, c_close = opens[-1], highs[-1], lows[-1], closes[-1]
        p_open, p_high, p_low, p_close = opens[-2], highs[-2], lows[-2], closes[-2]
        pp_close = closes[-3]

        candle_range = max(c_high - c_low, 1e-12)
        body_size = abs(c_close - c_open)
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low
        close_pos_in_candle = (c_close - c_low) / candle_range

        # فیلتر ایمنی جلوگیری از ورود وسط کندل‌های ریزشی/شارپ مخالف (Anti-Climax / Falling Knife Guard)
        is_adverse_climax = False
        if side == "LONG" and c_close < c_open and body_size > 1.25 * atr_5m and close_pos_in_candle < 0.20:
            is_adverse_climax = True
        elif side == "SHORT" and c_close > c_open and body_size > 1.25 * atr_5m and close_pos_in_candle > 0.80:
            is_adverse_climax = True

        triggered = False
        trigger_type = "NONE"
        details = (
            f"Waiting for 5m confirmation (RVOL={rvol_5m:.2f}x < {req_rvol:.2f}x)"
            if not volume_confirmed
            else "Waiting for 5m micro confirmation"
        )

        if not is_adverse_climax and volume_confirmed:
            # ======================================================================
            # ۱. بررسی 5M_MICRO_CHOCH (بسته شدن کندل فعلی فراتر از سقف/کف کندل قبلی)
            # ======================================================================
            if side == "LONG" and c_close > p_high and c_close > c_open:
                triggered = True
                trigger_type = "5M_MICRO_CHOCH"
                details = f"Bullish 5m CHoCH: Close ({c_close:.4f}) > prior High ({p_high:.4f}) | RVOL {rvol_5m:.2f}x"
            elif side == "SHORT" and c_close < p_low and c_close < c_open:
                triggered = True
                trigger_type = "5M_MICRO_CHOCH"
                details = f"Bearish 5m CHoCH: Close ({c_close:.4f}) < prior Low ({p_low:.4f}) | RVOL {rvol_5m:.2f}x"

            # ======================================================================
            # ۲. بررسی 5M_PINBAR (پین‌بار بازگشتی با شدوی حداقل ۴۵٪ و بسته شدن در نیمه موافق)
            # ======================================================================
            if not triggered:
                if (
                    side == "LONG"
                    and (lower_wick / candle_range) >= self.wick_rejection_ratio
                    and close_pos_in_candle >= 0.45
                ):
                    triggered = True
                    trigger_type = "5M_PINBAR"
                    details = f"Bullish 5m Pinbar rejection (Wick {(lower_wick / candle_range)*100:.1f}%, RVOL {rvol_5m:.2f}x)"
                elif (
                    side == "SHORT"
                    and (upper_wick / candle_range) >= self.wick_rejection_ratio
                    and close_pos_in_candle <= 0.55
                ):
                    triggered = True
                    trigger_type = "5M_PINBAR"
                    details = f"Bearish 5m Pinbar rejection (Wick {(upper_wick / candle_range)*100:.1f}%, RVOL {rvol_5m:.2f}x)"

            # ======================================================================
            # ۳. بررسی 5M_ENGULFING (کندل پوشا / مومنتوم قوی با بدنه حداقل ۵۵٪)
            # ======================================================================
            if not triggered:
                body_ratio = body_size / candle_range
                bull_engulf = c_close > c_open and (
                    (body_ratio >= self.engulf_body_ratio and c_close > pp_close)
                    or (p_close < p_open and c_close >= p_open and c_open <= p_close)
                )
                bear_engulf = c_close < c_open and (
                    (body_ratio >= self.engulf_body_ratio and c_close < pp_close)
                    or (p_close > p_open and c_close <= p_open and c_open >= p_close)
                )
                if side == "LONG" and bull_engulf:
                    triggered = True
                    trigger_type = "5M_ENGULFING"
                    details = f"Bullish 5m Engulfing (Body {body_ratio*100:.1f}%, RVOL {rvol_5m:.2f}x)"
                elif side == "SHORT" and bear_engulf:
                    triggered = True
                    trigger_type = "5M_ENGULFING"
                    details = f"Bearish 5m Engulfing (Body {body_ratio*100:.1f}%, RVOL {rvol_5m:.2f}x)"

            # ======================================================================
            # ۴. بررسی LIMIT_SNIPER_FVG (امتیاز فازی >= 75 و وجود active_fvg)
            # ======================================================================
            if not triggered:
                if float(confluence_score) >= self.sniper_score_threshold and active_fvg is not None:
                    triggered = True
                    trigger_type = "LIMIT_SNIPER_FVG"
                    details = (
                        f"Golden Setup Sniper Trigger (Score {confluence_score:.1f} >= "
                        f"{self.sniper_score_threshold:.1f} with active 15m FVG | RVOL {rvol_5m:.2f}x)"
                    )

        # ======================================================================
        # ۵. محاسبه قیمت ورود Limit به اندازه 0.10 * ATR_5m بهتر از قیمت مارکت
        # ======================================================================
        offset = self.maker_offset_atr_mult * atr_5m
        if side == "LONG":
            limit_entry_price = round(market_price - offset, 6)
        else:
            limit_entry_price = round(market_price + offset, 6)

        return {
            "triggered": triggered,
            "trigger_type": trigger_type,
            "order_type": "LIMIT",
            "side": side,
            "market_price": round(market_price, 6),
            "limit_entry_price": limit_entry_price,
            "atr_5m": round(atr_5m, 6),
            "rvol_5m": round(rvol_5m, 2),
            "details": details,
        }
