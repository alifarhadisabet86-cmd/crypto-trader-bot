"""
مهارت دوم (نسخه V2.5): اسکنر ساختار ۱۵ دقیقه، FVG، شکار نقدینگی و رنج سشن آسیا
Institutional Trading Bot V2.5 - 15m SMC Scanner & Asian Range Liquidity
"""

from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class MarketScannerSkill:
    """
    کلاس اسکنر ساختار بازار در تایم‌فریم ۱۵ دقیقه شامل:
    - استخراج FVGهای دست‌نخورده (Unmitigated FVGs)
    - تشخیص شکار نقدینگی سوئینگ‌ها (Liquidity Sweep)
    - استخراج سقف و کف سشن آسیا (Asian Session High/Low) و شکار آن
    - محاسبه موقعیت قیمت در رنج (Premium / Discount)
    """

    def __init__(
        self,
        swing_lookback: int = 40,
        fvg_scan_bars: int = 25,
        min_fvg_atr_ratio: float = 0.15,
    ) -> None:
        self.swing_lookback: int = swing_lookback
        self.fvg_scan_bars: int = fvg_scan_bars
        self.min_fvg_atr_ratio: float = min_fvg_atr_ratio

    def scan_structure(
        self,
        df_15m: pd.DataFrame,
        regime_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if df_15m is None or len(df_15m) < 30:
            return self._empty_scan_result("INSUFFICIENT_15M_DATA")

        df = df_15m.copy().reset_index(drop=True)
        current_price = float(df["close"].iloc[-1])
        atr_15m = self._get_latest_atr(df)

        # ۱. محاسبه محدوده رنج ۵۰ کندل اخیر و درصد Premium / Discount
        window_df = df.tail(self.swing_lookback)
        swing_high = float(window_df["high"].max())
        swing_low = float(window_df["low"].min())
        range_span = max(swing_high - swing_low, 1e-8)

        range_position_pct = float(
            np.clip(((current_price - swing_low) / range_span) * 100.0, 0.0, 100.0)
        )
        zone = (
            "DISCOUNT"
            if range_position_pct <= 45.0
            else ("PREMIUM" if range_position_pct >= 55.0 else "EQUILIBRIUM")
        )

        # ۲. شناسایی FVGهای دست‌نخورده (Unmitigated FVGs)
        fvgs = self._detect_unmitigated_fvgs(df, atr_15m)
        bullish_fvgs = [f for f in fvgs if f["type"] == "BULLISH"]
        bearish_fvgs = [f for f in fvgs if f["type"] == "BEARISH"]

        # ۳. تشخیص شکار نقدینگی (Liquidity Sweep / Stop-Hunt)
        sweep_info = self._detect_liquidity_sweep(df)

        # ۴. استخراج سقف و کف سشن آسیا (Asian Session Range: 00:00 - 06:00 UTC)
        asian_info = self._extract_asian_range(df, current_price)

        # ۵. بررسی اسپایک حجم (Volume Spike)
        vol_series = df["volume"].astype(float)
        vol_sma = float(vol_series.tail(20).mean()) if len(vol_series) >= 20 else float(vol_series.mean())
        current_vol = float(vol_series.iloc[-1])
        vol_ratio = current_vol / max(vol_sma, 1e-8)
        volume_spike = bool(vol_ratio >= 1.20)

        # ۶. تعیین جهت کاندید و بهترین FVG فعال
        regime = (regime_data or {}).get("regime", "RANGING")
        candidate_side, active_fvg = self._select_candidate_setup(
            current_price=current_price,
            atr_15m=atr_15m,
            regime=regime,
            zone=zone,
            bullish_fvgs=bullish_fvgs,
            bearish_fvgs=bearish_fvgs,
            sweep_info=sweep_info,
            asian_info=asian_info,
        )

        return {
            "valid": True,
            "current_price": round(current_price, 6),
            "atr_15m": round(atr_15m, 6),
            "swing_high": round(swing_high, 6),
            "swing_low": round(swing_low, 6),
            "range_position_pct": round(range_position_pct, 2),
            "zone": zone,
            "candidate_side": candidate_side,
            "active_fvg": active_fvg,
            "bullish_fvg_count": len(bullish_fvgs),
            "bearish_fvg_count": len(bearish_fvgs),
            "liquidity_sweep": sweep_info["sweep_type"],
            "sweep_level": sweep_info["sweep_level"],
            "sweep_wick_extreme": sweep_info["wick_extreme"],
            "asian_range": asian_info,
            "volume_ratio": round(vol_ratio, 2),
            "volume_spike": volume_spike,
            "reason": "OK",
        }

    def _extract_asian_range(
        self, df: pd.DataFrame, current_price: float
    ) -> Dict[str, Any]:
        """
        استخراج سقف و کف سشن آسیا (ساعت 00:00 تا 06:00 UTC) و بررسی شکار نقدینگی آن.
        """
        if "timestamp" in df.columns:
            try:
                ts = pd.to_datetime(df["timestamp"], utc=True)
                asian_mask = (ts.dt.hour >= 0) & (ts.dt.hour < 6)
                asian_df = df[asian_mask].tail(24)
            except Exception:
                asian_df = pd.DataFrame()
        else:
            asian_df = pd.DataFrame()

        if asian_df.empty:
            # در صورتی که ستون زمان نباشد، از یک‌پنجم ابتدایی پنجره اخیر به عنوان مرجع رنج اولیه استفاده می‌شود
            asian_df = df.iloc[max(0, len(df) - 48) : max(12, len(df) - 24)]

        asian_high = float(asian_df["high"].max())
        asian_low = float(asian_df["low"].min())

        recent_3 = df.tail(3)
        recent_max_h = float(recent_3["high"].max())
        recent_min_l = float(recent_3["low"].min())

        asian_sweep = "NONE"
        if recent_min_l < asian_low and current_price > asian_low:
            asian_sweep = "ASIAN_LOW_SWEEP_BULL"
        elif recent_max_h > asian_high and current_price < asian_high:
            asian_sweep = "ASIAN_HIGH_SWEEP_BEAR"

        return {
            "asian_high": round(asian_high, 6),
            "asian_low": round(asian_low, 6),
            "asian_sweep": asian_sweep,
        }

    def _detect_unmitigated_fvgs(
        self, df: pd.DataFrame, atr_15m: float
    ) -> List[Dict[str, Any]]:
        fvgs: List[Dict[str, Any]] = []
        n = len(df)
        start_idx = max(2, n - self.fvg_scan_bars)

        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        min_gap = atr_15m * self.min_fvg_atr_ratio

        for i in range(start_idx, n):
            h_prev2 = highs[i - 2]
            l_curr = lows[i]
            if l_curr - h_prev2 >= min_gap:
                gap_top = float(l_curr)
                gap_bottom = float(h_prev2)
                mitigated = False
                for j in range(i + 1, n):
                    if closes[j] < gap_bottom:
                        mitigated = True
                        break
                if not mitigated:
                    fvgs.append({
                        "type": "BULLISH",
                        "top": round(gap_top, 6),
                        "bottom": round(gap_bottom, 6),
                        "mid": round((gap_top + gap_bottom) / 2.0, 6),
                        "size": round(gap_top - gap_bottom, 6),
                        "age_bars": int(n - 1 - i),
                    })

            l_prev2 = lows[i - 2]
            h_curr = highs[i]
            if l_prev2 - h_curr >= min_gap:
                gap_top = float(l_prev2)
                gap_bottom = float(h_curr)
                mitigated = False
                for j in range(i + 1, n):
                    if closes[j] > gap_top:
                        mitigated = True
                        break
                if not mitigated:
                    fvgs.append({
                        "type": "BEARISH",
                        "top": round(gap_top, 6),
                        "bottom": round(gap_bottom, 6),
                        "mid": round((gap_top + gap_bottom) / 2.0, 6),
                        "size": round(gap_top - gap_bottom, 6),
                        "age_bars": int(n - 1 - i),
                    })

        return fvgs

    def _detect_liquidity_sweep(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 25:
            return {"sweep_type": "NONE", "sweep_level": None, "wick_extreme": None}

        prior_pool = df.iloc[-23:-3]
        pool_low = float(prior_pool["low"].min())
        pool_high = float(prior_pool["high"].max())

        recent_bars = df.iloc[-3:]
        for _, row in recent_bars.iloc[::-1].iterrows():
            low_val = float(row["low"])
            high_val = float(row["high"])
            close_val = float(row["close"])

            if low_val < pool_low and close_val > pool_low:
                return {
                    "sweep_type": "BULLISH_SWEEP",
                    "sweep_level": round(pool_low, 6),
                    "wick_extreme": round(low_val, 6),
                }
            if high_val > pool_high and close_val < pool_high:
                return {
                    "sweep_type": "BEARISH_SWEEP",
                    "sweep_level": round(pool_high, 6),
                    "wick_extreme": round(high_val, 6),
                }

        return {"sweep_type": "NONE", "sweep_level": None, "wick_extreme": None}

    @staticmethod
    def _select_candidate_setup(
        current_price: float,
        atr_15m: float,
        regime: str,
        zone: str,
        bullish_fvgs: List[Dict[str, Any]],
        bearish_fvgs: List[Dict[str, Any]],
        sweep_info: Dict[str, Any],
        asian_info: Dict[str, Any],
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        def closest_fvg(fvg_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not fvg_list:
                return None
            return min(fvg_list, key=lambda f: abs(current_price - f["mid"]))

        best_bull_fvg = closest_fvg(bullish_fvgs)
        best_bear_fvg = closest_fvg(bearish_fvgs)

        def is_near_fvg(fvg: Optional[Dict[str, Any]]) -> bool:
            if not fvg:
                return False
            if fvg["bottom"] <= current_price <= fvg["top"]:
                return True
            dist = min(abs(current_price - fvg["top"]), abs(current_price - fvg["bottom"]))
            return dist <= (1.5 * atr_15m)

        sweep_type = sweep_info.get("sweep_type", "NONE")
        asian_sweep = asian_info.get("asian_sweep", "NONE")

        if regime == "TRENDING_BULL":
            if is_near_fvg(best_bull_fvg) or sweep_type == "BULLISH_SWEEP" or asian_sweep == "ASIAN_LOW_SWEEP_BULL" or zone == "DISCOUNT":
                return "LONG", best_bull_fvg
        elif regime == "TRENDING_BEAR":
            if is_near_fvg(best_bear_fvg) or sweep_type == "BEARISH_SWEEP" or asian_sweep == "ASIAN_HIGH_SWEEP_BEAR" or zone == "PREMIUM":
                return "SHORT", best_bear_fvg
        elif regime == "RANGING":
            if sweep_type == "BULLISH_SWEEP" or asian_sweep == "ASIAN_LOW_SWEEP_BULL" or (zone == "DISCOUNT" and is_near_fvg(best_bull_fvg)):
                return "LONG", best_bull_fvg
            if sweep_type == "BEARISH_SWEEP" or asian_sweep == "ASIAN_HIGH_SWEEP_BEAR" or (zone == "PREMIUM" and is_near_fvg(best_bear_fvg)):
                return "SHORT", best_bear_fvg

        if best_bull_fvg and is_near_fvg(best_bull_fvg):
            return "LONG", best_bull_fvg
        if best_bear_fvg and is_near_fvg(best_bear_fvg):
            return "SHORT", best_bear_fvg

        return "NONE", None

    @staticmethod
    def _get_latest_atr(df: pd.DataFrame, period: int = 14) -> float:
        if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]):
            val = float(df["atr"].iloc[-1])
            if val > 0:
                return val
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat(
            [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr_val = float(tr.ewm(alpha=1.0 / period, adjust=False).mean().iloc[-1])
        return max(atr_val, float(close.iloc[-1]) * 0.001)

    @staticmethod
    def _empty_scan_result(reason: str) -> Dict[str, Any]:
        return {
            "valid": False,
            "current_price": 0.0,
            "atr_15m": 0.0,
            "swing_high": 0.0,
            "swing_low": 0.0,
            "range_position_pct": 50.0,
            "zone": "EQUILIBRIUM",
            "candidate_side": "NONE",
            "active_fvg": None,
            "bullish_fvg_count": 0,
            "bearish_fvg_count": 0,
            "liquidity_sweep": "NONE",
            "sweep_level": None,
            "sweep_wick_extreme": None,
            "asian_range": {"asian_high": 0.0, "asian_low": 0.0, "asian_sweep": "NONE"},
            "volume_ratio": 1.0,
            "volume_spike": False,
            "reason": reason,
        }