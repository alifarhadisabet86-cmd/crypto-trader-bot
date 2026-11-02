"""
مهارت ششم (نسخه V2.5 Pro): طراحی نقشه خروج، استاپ ساختاری + بافر 0.20*ATR و تارگت دوگانه (TP1/TP2)
Institutional Trading Bot V2.5 - Structural Stop-Loss & Dual-Target Planner
"""

from typing import Dict, Any, Optional, List
import numpy as np

from core.config import EXCHANGE_CONFIG


class ExitPlannerSkill:
    """
    کلاس محاسبه حد ضرر ساختاری (پشت شدوی استاپ‌هانت یا مرز بیرونی FVG + بافر 0.20*ATR_15m)
    کلمپ‌شده بین [0.85*ATR, 2.20*ATR]، تارگت اول (TP1 در 1.15R برای بستن ۵۰٪ حجم و ریسک‌فری)
    و تارگت دوم (TP2 بر اساس استخر نقدینگی با حداقل R:R 1.75 در رنج و 2.30 در روند).
    """

    def __init__(self) -> None:
        self.base_atr_sl_mult: float = 1.25
        self.sl_buffer_atr_mult: float = float(EXCHANGE_CONFIG.get("SL_BUFFER_ATR_MULT", 0.20))
        self.min_sl_atr_mult: float = float(EXCHANGE_CONFIG.get("SL_MIN_ATR_MULT", 0.85))
        self.max_sl_atr_mult: float = float(EXCHANGE_CONFIG.get("SL_MAX_ATR_MULT", 2.20))
        self.tp1_rr_ratio: float = float(EXCHANGE_CONFIG.get("TP1_R_MULTIPLE", 1.15))
        self.tp1_close_pct: float = float(EXCHANGE_CONFIG.get("TP1_CLOSE_PCT", 0.50))
        self.min_tp2_rr_ranging: float = float(EXCHANGE_CONFIG.get("MIN_RR_RANGING", 1.75))
        self.min_tp2_rr_trending: float = float(EXCHANGE_CONFIG.get("MIN_RR_TRENDING", 2.30))

    def plan_exit(
        self,
        entry_price: float,
        side: str,
        atr_15m: float,
        scan_data: Optional[Dict[str, Any]] = None,
        regime_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        محاسبه نقاط دقیق stop_loss، tp1_breakeven و tp2_final به همراه نسبت‌های ریسک به ریوارد.
        """
        clean_side = str(side).strip().upper()
        entry = float(entry_price)
        if entry <= 0.0 or clean_side not in ("LONG", "SHORT"):
            return {
                "valid": False,
                "side": clean_side,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "sl_distance": 0.0,
                "sl_pct": 0.0,
                "tp1_breakeven": 0.0,
                "tp2_final": 0.0,
                "rr_tp1": 0.0,
                "rr_tp2": 0.0,
                "blended_rr": 0.0,
                "partial_close_pct": self.tp1_close_pct,
                "regime_used": "RANGING",
            }

        atr = max(float(atr_15m), entry * 0.001, 1e-8)

        scan = scan_data or {}
        reg = regime_data or {}
        regime_name = str(reg.get("regime", "RANGING")).upper()

        sweep_wick = float(
            scan.get("sweep_wick_extreme")
            or scan.get("sweep_extreme_wick")
            or 0.0
        )
        active_fvg = scan.get("active_fvg")
        high_pool = float(
            scan.get("swing_high")
            or scan.get("range_high_pool")
            or 0.0
        )
        low_pool = float(
            scan.get("swing_low")
            or scan.get("range_low_pool")
            or 0.0
        )

        min_sl_dist = self.min_sl_atr_mult * atr
        max_sl_dist = self.max_sl_atr_mult * atr
        buffer_dist = self.sl_buffer_atr_mult * atr

        # ======================================================================
        # ۱. محاسبه حد ضرر ساختاری (پشت شدوی استاپ‌هانت یا مرز بیرونی باکس FVG + 0.20*ATR)
        #    و کلمپ در بازه [0.85 * ATR, 2.20 * ATR]
        # ======================================================================
        if clean_side == "LONG":
            structural_candidates: List[float] = []

            if sweep_wick > 0.0 and sweep_wick < entry:
                structural_candidates.append(sweep_wick - buffer_dist)

            if isinstance(active_fvg, dict) and active_fvg.get("bottom"):
                fvg_bottom = float(active_fvg["bottom"])
                if fvg_bottom < entry:
                    structural_candidates.append(fvg_bottom - buffer_dist)

            if structural_candidates:
                raw_structural_sl = min(structural_candidates)
            else:
                raw_structural_sl = entry - (self.base_atr_sl_mult * atr)

            raw_sl_dist = entry - raw_structural_sl
            sl_dist = float(np.clip(raw_sl_dist, min_sl_dist, max_sl_dist))
            stop_loss = round(entry - sl_dist, 6)

        else:  # SHORT
            structural_candidates = []

            if sweep_wick > 0.0 and sweep_wick > entry:
                structural_candidates.append(sweep_wick + buffer_dist)

            if isinstance(active_fvg, dict) and active_fvg.get("top"):
                fvg_top = float(active_fvg["top"])
                if fvg_top > entry:
                    structural_candidates.append(fvg_top + buffer_dist)

            if structural_candidates:
                raw_structural_sl = max(structural_candidates)
            else:
                raw_structural_sl = entry + (self.base_atr_sl_mult * atr)

            raw_sl_dist = raw_structural_sl - entry
            sl_dist = float(np.clip(raw_sl_dist, min_sl_dist, max_sl_dist))
            stop_loss = round(entry + sl_dist, 6)

        sl_dist = max(abs(entry - stop_loss), 1e-8)

        # ======================================================================
        # ۲. محاسبه تارگت اول (TP1: سیو سود ۵۰٪ و انتقال استاپ به نقطه ورود در 1.15R)
        # ======================================================================
        tp1_dist = self.tp1_rr_ratio * sl_dist
        if clean_side == "LONG":
            tp1_breakeven = round(entry + tp1_dist, 6)
        else:
            tp1_breakeven = round(entry - tp1_dist, 6)

        # ======================================================================
        # ۳. محاسبه تارگت دوم (TP2: استخر نقدینگی با تضمین حداقل R:R رژیم بازار)
        # ======================================================================
        is_trending = regime_name in ("TRENDING_BULL", "TRENDING_BEAR")
        min_tp2_rr = self.min_tp2_rr_trending if is_trending else self.min_tp2_rr_ranging
        min_tp2_dist = min_tp2_rr * sl_dist

        if clean_side == "LONG":
            pool_dist = (high_pool - entry) if high_pool > entry else 0.0
            tp2_dist = max(min_tp2_dist, min(pool_dist, 4.5 * sl_dist))
            tp2_final = round(entry + tp2_dist, 6)
        else:
            pool_dist = (entry - low_pool) if (0.0 < low_pool < entry) else 0.0
            tp2_dist = max(min_tp2_dist, min(pool_dist, 4.5 * sl_dist))
            tp2_final = round(entry - tp2_dist, 6)

        rr_tp1 = round(abs(tp1_breakeven - entry) / sl_dist, 2)
        rr_tp2 = round(abs(tp2_final - entry) / sl_dist, 2)
        blended_rr = round((self.tp1_close_pct * rr_tp1) + ((1.0 - self.tp1_close_pct) * rr_tp2), 2)

        return {
            "valid": True,
            "side": clean_side,
            "entry_price": round(entry, 6),
            "stop_loss": stop_loss,
            "sl_distance": round(sl_dist, 6),
            "sl_pct": round((sl_dist / entry) * 100.0, 4) if entry > 0 else 0.0,
            "tp1_breakeven": tp1_breakeven,
            "tp2_final": tp2_final,
            "rr_tp1": rr_tp1,
            "rr_tp2": rr_tp2,
            "blended_rr": blended_rr,
            "partial_close_pct": self.tp1_close_pct,
            "regime_used": regime_name,
        }
