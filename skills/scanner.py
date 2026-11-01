"""
مهارت دوم: اسکنر ساختار ۱۵ دقیقه برای استخراج FVG، Sweep و استخر نقدینگی (Market Scanner Skill)
Institutional Trading Bot V2 - 15m Smart Money Structure Scanner
"""

from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class MarketScannerSkill:
    """
    کلاس اسکنر تایم‌فریم ۱۵ دقیقه جهت شناسایی استخرهای نقدینگی، نواحی Premium/Discount،
    شکاف‌های ارزش منصفانه پرنشده (Unmitigated FVGs) و شکار نقدینگی (Liquidity Sweeps).
    """

    def __init__(self) -> None:
        self.range_lookback: int = 40
        self.fvg_lookback: int = 35
        self.sweep_pool_lookback: int = 25
        self.sweep_recent_candles: int = 3
        self.vol_ma_period: int = 20
        self.fvg_atr_proximity: float = 1.8

    def _find_unmitigated_fvgs(self, df: pd.DataFrame, current_atr: float) -> Dict[str, Any]:
        """
        جستجوی شکاف‌های ارزش منصفانه (FVG) صعودی و نزولی پرنشده در ۳۵ کندل اخیر.
        اگر قیمت فعلی در فاصله <= 1.8 * ATR از مرکز FVG باشد، near_fvg = True می‌شود.
        """
        result: Dict[str, Any] = {
            "bullish_fvgs": [],
            "bearish_fvgs": [],
            "nearest_bull_fvg": None,
            "nearest_bear_fvg": None,
            "near_bull_fvg": False,
            "near_bear_fvg": False,
        }

        if df is None or len(df) < 10:
            return result

        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        current_price = float(closes[-1])

        n = len(df)
        start_idx = max(2, n - self.fvg_lookback)

        bull_list: List[Dict[str, Any]] = []
        bear_list: List[Dict[str, Any]] = []

        for i in range(start_idx, n):
            # ۱. بررسی FVG صعودی: کف کندل i بالاتر از سقف کندل i-2
            if lows[i] > highs[i - 2]:
                top = float(lows[i])
                bottom = float(highs[i - 2])
                subsequent_lows = lows[i + 1 :] if (i + 1) < n else np.array([top])
                if len(subsequent_lows) == 0 or float(np.min(subsequent_lows)) > bottom:
                    mid = (top + bottom) / 2.0
                    dist = abs(current_price - mid)
                    bull_list.append({
                        "type": "BULLISH",
                        "top": round(top, 6),
                        "bottom": round(bottom, 6),
                        "midpoint": round(mid, 6),
                        "candle_index": int(i),
                        "distance": round(dist, 6),
                    })

            # ۲. بررسی FVG نزولی: سقف کندل i پایین‌تر از کف کندل i-2
            if highs[i] < lows[i - 2]:
                top = float(lows[i - 2])
                bottom = float(highs[i])
                subsequent_highs = highs[i + 1 :] if (i + 1) < n else np.array([bottom])
                if len(subsequent_highs) == 0 or float(np.max(subsequent_highs)) < top:
                    mid = (top + bottom) / 2.0
                    dist = abs(current_price - mid)
                    bear_list.append({
                        "type": "BEARISH",
                        "top": round(top, 6),
                        "bottom": round(bottom, 6),
                        "midpoint": round(mid, 6),
                        "candle_index": int(i),
                        "distance": round(dist, 6),
                    })

        result["bullish_fvgs"] = bull_list
        result["bearish_fvgs"] = bear_list

        max_dist = self.fvg_atr_proximity * max(current_atr, 1e-8)

        if bull_list:
            nearest_bull = min(bull_list, key=lambda x: x["distance"])
            result["nearest_bull_fvg"] = nearest_bull
            in_zone = nearest_bull["bottom"] <= current_price <= nearest_bull["top"]
            if in_zone or nearest_bull["distance"] <= max_dist:
                result["near_bull_fvg"] = True

        if bear_list:
            nearest_bear = min(bear_list, key=lambda x: x["distance"])
            result["nearest_bear_fvg"] = nearest_bear
            in_zone = nearest_bear["bottom"] <= current_price <= nearest_bear["top"]
            if in_zone or nearest_bear["distance"] <= max_dist:
                result["near_bear_fvg"] = True

        return result

    def _detect_liquidity_sweep(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        بررسی ۳ کندل اخیر برای تشخیص شکار نقدینگی (Liquidity Sweep) زیر کف یا بالای سقف
        ۲۵ کندل قبلی، به همراه محاسبه اسپایک حجم (volume_spike).
        """
        default_res: Dict[str, Any] = {
            "sweep_detected": False,
            "sweep_type": "NONE",
            "sweep_extreme_wick": 0.0,
            "swept_level": 0.0,
            "volume_spike": 1.0,
        }

        if df is None or len(df) < 12:
            return default_res

        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        volumes = df["volume"].astype(float).values

        n = len(df)
        vol_window = min(self.vol_ma_period, n)
        avg_vol = float(np.mean(volumes[-vol_window:])) if vol_window > 0 else 1.0
        current_vol_spike = round(float(volumes[-1]) / avg_vol, 2) if avg_vol > 1e-12 else 1.0

        recent_count = min(self.sweep_recent_candles, n - 5)
        best_sweep: Dict[str, Any] = dict(default_res)
        best_sweep["volume_spike"] = current_vol_spike

        # بررسی ۳ کندل آخر (از جدیدترین کندل به عقب)
        for offset in range(1, recent_count + 1):
            idx = n - offset
            pool_start = max(0, idx - self.sweep_pool_lookback)
            if idx <= pool_start:
                continue

            prior_low_pool = float(np.min(lows[pool_start:idx]))
            prior_high_pool = float(np.max(highs[pool_start:idx]))

            c_low = float(lows[idx])
            c_high = float(highs[idx])
            c_close = float(closes[idx])
            c_vol_spike = round(float(volumes[idx]) / avg_vol, 2) if avg_vol > 1e-12 else 1.0

            # Bullish Sweep: شدو به زیر کف قبلی و بسته شدن کندل بالای آن کف
            if c_low < prior_low_pool and c_close > prior_low_pool:
                return {
                    "sweep_detected": True,
                    "sweep_type": "BULLISH_SWEEP",
                    "sweep_extreme_wick": round(c_low, 6),
                    "swept_level": round(prior_low_pool, 6),
                    "volume_spike": max(current_vol_spike, c_vol_spike),
                }

            # Bearish Sweep: شدو به بالای سقف قبلی و بسته شدن کندل زیر آن سقف
            if c_high > prior_high_pool and c_close < prior_high_pool:
                return {
                    "sweep_detected": True,
                    "sweep_type": "BEARISH_SWEEP",
                    "sweep_extreme_wick": round(c_high, 6),
                    "swept_level": round(prior_high_pool, 6),
                    "volume_spike": max(current_vol_spike, c_vol_spike),
                }

        return best_sweep

    def scan_structure(
        self,
        df_15m: pd.DataFrame,
        regime_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        تحلیل کامل ساختار ۱۵ دقیقه و خروجی دادن استخرهای نقدینگی، FVG، Sweep،
        جهت کاندید (candidate_side) و دیتافریم df_15m برای رسم چارت.
        """
        if df_15m is None or len(df_15m) < 15:
            return {
                "valid": False,
                "candidate_side": "NONE",
                "current_price": 0.0,
                "atr_15m": 0.0,
                "range_high_pool": 0.0,
                "range_low_pool": 0.0,
                "range_position_pct": 50.0,
                "zone": "EQUILIBRIUM",
                "near_fvg": False,
                "active_fvg": None,
                "sweep_detected": False,
                "sweep_type": "NONE",
                "sweep_extreme_wick": 0.0,
                "volume_spike": 1.0,
                "df_15m": df_15m,
            }

        regime = (regime_data or {}).get("regime", "RANGING")
        current_price = float(df_15m["close"].iloc[-1])

        if "atr" in df_15m.columns and not df_15m["atr"].isna().all():
            atr_15m = float(df_15m["atr"].iloc[-1])
        else:
            atr_15m = float((df_15m["high"] - df_15m["low"]).tail(14).mean())

        # ۱. محاسبه استخر نقدینگی سقف و کف ۴۰ کندل اخیر و موقعیت قیمت در رنج
        lookback = min(self.range_lookback, len(df_15m))
        recent_slice = df_15m.iloc[-lookback:]
        range_high_pool = float(recent_slice["high"].max())
        range_low_pool = float(recent_slice["low"].min())
        total_range = range_high_pool - range_low_pool

        if total_range > 1e-12:
            range_position_pct = round(((current_price - range_low_pool) / total_range) * 100.0, 2)
            range_position_pct = float(np.clip(range_position_pct, 0.0, 100.0))
        else:
            range_position_pct = 50.0

        if range_position_pct <= 30.0:
            zone = "DISCOUNT"
        elif range_position_pct >= 70.0:
            zone = "PREMIUM"
        else:
            zone = "EQUILIBRIUM"

        # ۲. استخراج FVGها و شکار نقدینگی (Sweep)
        fvg_info = self._find_unmitigated_fvgs(df_15m, atr_15m)
        sweep_info = self._detect_liquidity_sweep(df_15m)

        # ۳. تعیین جهت کاندید (candidate_side) بر اساس رژیم و ساختار
        if regime == "TRENDING_BULL":
            candidate_side = "LONG"
        elif regime == "TRENDING_BEAR":
            candidate_side = "SHORT"
        else:
            if sweep_info["sweep_type"] == "BULLISH_SWEEP":
                candidate_side = "LONG"
            elif sweep_info["sweep_type"] == "BEARISH_SWEEP":
                candidate_side = "SHORT"
            elif range_position_pct <= 48.0:
                candidate_side = "LONG"
            else:
                candidate_side = "SHORT"

        # ۴. انتخاب FVG هم‌جهت با candidate_side
        if candidate_side == "LONG":
            near_fvg = bool(fvg_info["near_bull_fvg"])
            active_fvg = fvg_info["nearest_bull_fvg"]
        else:
            near_fvg = bool(fvg_info["near_bear_fvg"])
            active_fvg = fvg_info["nearest_bear_fvg"]

        return {
            "valid": True,
            "candidate_side": candidate_side,
            "current_price": round(current_price, 6),
            "atr_15m": round(atr_15m, 6),
            "range_high_pool": round(range_high_pool, 6),
            "range_low_pool": round(range_low_pool, 6),
            "range_position_pct": range_position_pct,
            "zone": zone,
            "near_fvg": near_fvg,
            "active_fvg": active_fvg,
            "all_bull_fvgs": fvg_info["bullish_fvgs"],
            "all_bear_fvgs": fvg_info["bearish_fvgs"],
            "sweep_detected": bool(sweep_info["sweep_detected"]),
            "sweep_type": sweep_info["sweep_type"],
            "sweep_extreme_wick": sweep_info["sweep_extreme_wick"],
            "swept_level": sweep_info["swept_level"],
            "volume_spike": sweep_info["volume_spike"],
            "df_15m": df_15m,
        }