"""
مهارت پنجم: ماشه شلیک ۵ دقیقه (CHoCH, Pinbar, Engulfing, Limit Sniper) و محاسبه قیمت ورود Limit
Institutional Trading Bot V2 - 5m Micro Entry Trigger & Maker Price Optimizer
"""

from typing import Dict, Any, Optional
import pandas as pd


class EntryTriggerSkill:
    """
    کلاس بررسی کندل‌های تایم‌فریم 5m برای صدور دستور شلیک نهایی و
    تعیین قیمت ورود بهینه (limit_entry_price) به اندازه 0.10 * ATR_5m بهتر از قیمت مارکت.
    """

    def __init__(self) -> None:
        self.wick_rejection_ratio: float = 0.45
        self.engulf_body_ratio: float = 0.55
        self.sniper_score_threshold: float = 75.0
        self.maker_offset_atr_mult: float = 0.10

    def evaluate_entry_trigger(
        self,
        df_5m: pd.DataFrame,
        candidate_side: str,
        confluence_score: float,
        active_fvg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        بررسی شروط کندلی ۵ دقیقه (CHoCH, Wick Rejection, Momentum Engulf) و شرط Limit Sniper.
        محاسبه قیمت دقیق سفارش Limit (Maker).
        """
        side = str(candidate_side).strip().upper()

        if df_5m is None or len(df_5m) < 5 or side not in ("LONG", "SHORT"):
            return {
                "triggered": False,
                "trigger_type": "NONE",
                "side": side,
                "market_price": 0.0,
                "limit_entry_price": 0.0,
                "atr_5m": 0.0,
                "details": "Insufficient 5m data or invalid candidate side",
            }

        opens = df_5m["open"].astype(float).values
        highs = df_5m["high"].astype(float).values
        lows = df_5m["low"].astype(float).values
        closes = df_5m["close"].astype(float).values

        if "atr" in df_5m.columns and not df_5m["atr"].isna().all():
            atr_5m = float(df_5m["atr"].iloc[-1])
        else:
            atr_5m = float((df_5m["high"] - df_5m["low"]).tail(14).mean())

        atr_5m = max(atr_5m, 1e-8)
        market_price = float(closes[-1])

        # مشخصات کندل فعلی (-1)، کندل قبلی (-2) و دو کندل قبل (-3)
        c_open, c_high, c_low, c_close = opens[-1], highs[-1], lows[-1], closes[-1]
        p_high, p_low = highs[-2], lows[-2]
        pp_close = closes[-3]

        candle_range = max(c_high - c_low, 1e-12)
        body_size = abs(c_close - c_open)
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low

        triggered = False
        trigger_type = "NONE"
        details = "Waiting for 5m micro confirmation"

        # ======================================================================
        # ۱. بررسی 5M_MICRO_CHOCH (بسته شدن کندل فعلی فراتر از سقف/کف کندل قبلی)
        # ======================================================================
        if side == "LONG" and c_close > p_high and c_close > c_open:
            triggered = True
            trigger_type = "5M_MICRO_CHOCH"
            details = f"Bullish 5m CHoCH: Close ({c_close:.4f}) broke above prior High ({p_high:.4f})"
        elif side == "SHORT" and c_close < p_low and c_close < c_open:
            triggered = True
            trigger_type = "5M_MICRO_CHOCH"
            details = f"Bearish 5m CHoCH: Close ({c_close:.4f}) broke below prior Low ({p_low:.4f})"

        # ======================================================================
        # ۲. بررسی 5M_WICK_REJECTION (پین‌بار با شدوی مخالف حداقل ۴۵٪ کل طول کندل)
        # ======================================================================
        if not triggered:
            if side == "LONG" and (lower_wick / candle_range) >= self.wick_rejection_ratio:
                triggered = True
                trigger_type = "5M_WICK_REJECTION"
                details = f"Bullish 5m Pinbar rejection (Lower wick {(lower_wick / candle_range)*100:.1f}% >= 45%)"
            elif side == "SHORT" and (upper_wick / candle_range) >= self.wick_rejection_ratio:
                triggered = True
                trigger_type = "5M_WICK_REJECTION"
                details = f"Bearish 5m Pinbar rejection (Upper wick {(upper_wick / candle_range)*100:.1f}% >= 45%)"

        # ======================================================================
        # ۳. بررسی 5M_MOMENTUM_ENGULF (بدنه حداقل ۵۵٪ رنج کندل و عبور از کلوز ۲ کندل قبل)
        # ======================================================================
        if not triggered:
            body_ratio = body_size / candle_range
            if (
                side == "LONG"
                and c_close > c_open
                and body_ratio >= self.engulf_body_ratio
                and c_close > pp_close
            ):
                triggered = True
                trigger_type = "5M_MOMENTUM_ENGULF"
                details = f"Bullish 5m Momentum Engulfing (Body {body_ratio*100:.1f}% >= 55%, Close > 2-bars ago)"
            elif (
                side == "SHORT"
                and c_close < c_open
                and body_ratio >= self.engulf_body_ratio
                and c_close < pp_close
            ):
                triggered = True
                trigger_type = "5M_MOMENTUM_ENGULF"
                details = f"Bearish 5m Momentum Engulfing (Body {body_ratio*100:.1f}% >= 55%, Close < 2-bars ago)"

        # ======================================================================
        # ۴. بررسی LIMIT_SNIPER_FVG (امتیاز فازی >= 75 و وجود active_fvg)
        # ======================================================================
        if not triggered:
            if float(confluence_score) >= self.sniper_score_threshold and active_fvg is not None:
                triggered = True
                trigger_type = "LIMIT_SNIPER_FVG"
                details = (
                    f"Golden Setup Sniper Trigger (Score {confluence_score:.1f} >= 75.0 "
                    f"with active 15m FVG zone)"
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
            "side": side,
            "market_price": round(market_price, 6),
            "limit_entry_price": limit_entry_price,
            "atr_5m": round(atr_5m, 6),
            "details": details,
        }