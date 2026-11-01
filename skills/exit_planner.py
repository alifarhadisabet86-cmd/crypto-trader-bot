"""
مهارت ششم: طراحی نقشه خروج، استاپ ساختاری + ATR و تارگت دوگانه (TP1/TP2) (Exit Planner Skill)
Institutional Trading Bot V2 - Structural Stop-Loss & Dual-Target Planner
"""

from typing import Dict, Any, Optional, List
import numpy as np


class ExitPlannerSkill:
    """
    کلاس محاسبه حد ضرر ساختاری کلمپ‌شده بین [0.85*ATR, 2.20*ATR]،
    تارگت اول (TP1 در 1.15R برای بستن ۵۰٪ حجم و ریسک‌فری) و تارگت دوم (TP2 بر اساس استخر نقدینگی).
    """

    def __init__(self) -> None:
        self.base_atr_sl_mult: float = 1.35
        self.sweep_buffer_atr_mult: float = 0.35
        self.fvg_buffer_atr_mult: float = 0.40
        self.min_sl_atr_mult: float = 0.85
        self.max_sl_atr_mult: float = 2.20
        self.tp1_rr_ratio: float = 1.15
        self.min_tp2_rr_ranging: float = 1.75
        self.min_tp2_rr_trending: float = 2.30

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
        atr = max(float(atr_15m), entry * 0.001, 1e-8)

        scan = scan_data or {}
        reg = regime_data or {}
        regime_name = str(reg.get("regime", "RANGING")).upper()

        sweep_wick = float(scan.get("sweep_extreme_wick") or 0.0)
        active_fvg = scan.get("active_fvg")
        high_pool = float(scan.get("range_high_pool") or 0.0)
        low_pool = float(scan.get("range_low_pool") or 0.0)

        min_sl_dist = self.min_sl_atr_mult * atr
        max_sl_dist = self.max_sl_atr_mult * atr

        # ======================================================================
        # ۱. محاسبه کاندیدهای حد ضرر ساختاری و کلمپ در بازه [0.85 * ATR, 2.20 * ATR]
        # ======================================================================
        if clean_side == "LONG":
            candidates: List[float] = [entry - (self.base_atr_sl_mult * atr)]

            if sweep_wick > 0.0 and sweep_wick < entry:
                candidates.append(sweep_wick - (self.sweep_buffer_atr_mult * atr))

            if isinstance(active_fvg, dict) and active_fvg.get("bottom"):
                fvg_bottom = float(active_fvg["bottom"])
                if fvg_bottom < entry:
                    candidates.append(fvg_bottom - (self.fvg_buffer_atr_mult * atr))

            # امن‌ترین نقطه پشت ساختار برای LONG پایین‌ترین قیمت کاندید است
            raw_structural_sl = min(candidates)
            raw_sl_dist = entry - raw_structural_sl
            sl_dist = float(np.clip(raw_sl_dist, min_sl_dist, max_sl_dist))
            stop_loss = round(entry - sl_dist, 6)

        else:  # SHORT
            candidates = [entry + (self.base_atr_sl_mult * atr)]

            if sweep_wick > 0.0 and sweep_wick > entry:
                candidates.append(sweep_wick + (self.sweep_buffer_atr_mult * atr))

            if isinstance(active_fvg, dict) and active_fvg.get("top"):
                fvg_top = float(active_fvg["top"])
                if fvg_top > entry:
                    candidates.append(fvg_top + (self.fvg_buffer_atr_mult * atr))

            # امن‌ترین نقطه پشت ساختار برای SHORT بالاترین قیمت کاندید است
            raw_structural_sl = max(candidates)
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
            # اگر استخر نقدینگی بالاتر از حداقل ریوارد بود و بیش از 4.5R دور نبود، همان استخر هدف است
            tp2_dist = max(min_tp2_dist, min(pool_dist, 4.5 * sl_dist))
            tp2_final = round(entry + tp2_dist, 6)
        else:
            pool_dist = (entry - low_pool) if (0.0 < low_pool < entry) else 0.0
            tp2_dist = max(min_tp2_dist, min(pool_dist, 4.5 * sl_dist))
            tp2_final = round(entry - tp2_dist, 6)

        rr_tp1 = round(abs(tp1_breakeven - entry) / sl_dist, 2)
        rr_tp2 = round(abs(tp2_final - entry) / sl_dist, 2)
        blended_rr = round((0.5 * rr_tp1) + (0.5 * rr_tp2), 2)

        return {
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
            "partial_close_pct": 0.50,
            "regime_used": regime_name,
        }