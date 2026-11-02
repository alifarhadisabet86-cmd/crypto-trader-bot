"""
مهارت اول (نسخه V2.5 Pro): تشخیص رژیم بازار ۱ ساعته و بایاس ۴ ساعته (ADX 14, EMA 20/50/200, ATR)
Institutional Trading Bot V2.5 - Market Regime & Volatility Filter
"""

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


class RegimeDetectorSkill:
    """
    کلاس تشخیص رژیم بازار (TRENDING_BULL, TRENDING_BEAR, RANGING, CHOPPY_NO_TRADE, EXTREME_VOLATILITY)
    با استفاده از ADX(14) استاندارد وایلدر، EMA 20 / 50 / 200 و رادار نوسان ATR.
    """

    def __init__(self) -> None:
        self.ema_fast_period: int = 20
        self.ema_slow_period: int = 50
        self.ema_macro_period: int = 200
        self.adx_period: int = 14
        self.atr_baseline_window: int = 40
        self.extreme_vol_threshold: float = 2.40
        self.choppy_vol_threshold: float = 0.40
        self.adx_trend_threshold: float = 20.0

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        محاسبه شاخص قدرت روند ADX(14) وایلدر به همراه ترکیب با Efficiency Ratio
        برای دقت بالا حتی در پنجره‌های کندلی کوتاه‌تر (۶۰ تا ۸۰ کندل).
        خروجی عددی بین ۰ تا ۱۰۰ است.
        """
        if df is None or len(df) < 5:
            return 0.0

        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values

        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        alpha = 1.0 / float(max(period, 2))
        tr_smooth = pd.Series(tr).ewm(alpha=alpha, adjust=False).mean().values
        plus_di = 100.0 * pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean().values / np.maximum(tr_smooth, 1e-12)
        minus_di = 100.0 * pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean().values / np.maximum(tr_smooth, 1e-12)

        dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-12)
        adx_val = float(pd.Series(dx).ewm(alpha=alpha, adjust=False).mean().iloc[-1])

        # ترکیب هوشمند با نسبت کارایی کافمن برای پایداری در داده‌های خطی/کوتاه
        lookback = min(16, len(closes) - 1)
        er_ratio = 0.0
        if lookback > 0:
            net_change = abs(closes[-1] - closes[-1 - lookback])
            step_changes = float(np.sum(np.abs(np.diff(closes[-(lookback + 1):]))))
            if step_changes > 1e-12:
                er_ratio = (net_change / step_changes) * 100.0

        combined_adx = max(adx_val, er_ratio * 0.65)
        return float(np.clip(round(combined_adx, 2), 0.0, 100.0))

    @staticmethod
    def _compute_ema(series: pd.Series, span: int) -> pd.Series:
        """محاسبه میانگین متحرک نمایی (EMA)."""
        return series.astype(float).ewm(span=span, adjust=False).mean()

    def _determine_htf_bias(self, df_4h: Optional[pd.DataFrame]) -> str:
        """
        تعیین بایاس ساختار کلان ۴ ساعته (BULLISH, BEARISH, NEUTRAL) با EMA 20/50/200.
        """
        if df_4h is None or len(df_4h) < 10:
            return "NEUTRAL"

        closes = df_4h["close"].astype(float)
        ema20 = self._compute_ema(closes, self.ema_fast_period)
        ema50 = self._compute_ema(closes, self.ema_slow_period)
        ema200 = self._compute_ema(closes, min(self.ema_macro_period, len(closes)))

        last_close = float(closes.iloc[-1])
        last_ema20 = float(ema20.iloc[-1])
        last_ema50 = float(ema50.iloc[-1])
        last_ema200 = float(ema200.iloc[-1])

        if last_close > last_ema20 and last_ema20 >= last_ema50 and last_close >= last_ema200:
            return "BULLISH"
        if last_close < last_ema20 and last_ema20 <= last_ema50 and last_close <= last_ema200:
            return "BEARISH"
        if last_close > last_ema20 and last_ema20 >= last_ema50:
            return "BULLISH"
        if last_close < last_ema20 and last_ema20 <= last_ema50:
            return "BEARISH"
        return "NEUTRAL"

    def detect_regime(
        self,
        df_1h: pd.DataFrame,
        df_4h: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        تحلیل کندل‌های 1h و 4h و استخراج رژیم فعلی بازار، استراتژی مجاز، ADX(14) و وضعیت tradable.
        """
        if df_1h is None or len(df_1h) < 20:
            return {
                "regime": "CHOPPY_NO_TRADE",
                "strategy": "NONE",
                "tradable": False,
                "htf_bias": "NEUTRAL",
                "adx": 0.0,
                "trend_strength": 0.0,
                "atr_ratio": 0.0,
                "ema20_1h": 0.0,
                "ema50_1h": 0.0,
                "ema200_1h": 0.0,
                "reason": "Insufficient 1H candle data",
            }

        # ۱. تعیین بایاس ۴ ساعته
        htf_bias = self._determine_htf_bias(df_4h if df_4h is not None else df_1h)

        # ۲. محاسبه EMA 20، EMA 50 و EMA 200 در تایم‌فریم ۱ ساعته
        closes_1h = df_1h["close"].astype(float)
        ema20_series = self._compute_ema(closes_1h, self.ema_fast_period)
        ema50_series = self._compute_ema(closes_1h, self.ema_slow_period)
        ema200_series = self._compute_ema(closes_1h, min(self.ema_macro_period, len(closes_1h)))

        current_price = float(closes_1h.iloc[-1])
        ema20_1h = float(ema20_series.iloc[-1])
        ema50_1h = float(ema50_series.iloc[-1])
        ema200_1h = float(ema200_series.iloc[-1])

        # ۳. محاسبه قدرت روند ADX(14)
        adx_val = self._calculate_adx(df_1h, period=self.adx_period)

        # ۴. محاسبه atr_ratio (نسبت ATR فعلی ۱ ساعته به میانگین ۴۰ کندل اخیر)
        if "atr" in df_1h.columns and not df_1h["atr"].isna().all():
            atr_series = df_1h["atr"].astype(float)
        else:
            atr_series = (df_1h["high"].astype(float) - df_1h["low"].astype(float))

        current_atr = float(atr_series.iloc[-1])
        baseline_window = min(self.atr_baseline_window, len(atr_series))
        mean_atr = float(atr_series.iloc[-baseline_window:].mean())
        atr_ratio = round(current_atr / mean_atr, 2) if mean_atr > 1e-12 else 1.0

        # ۵. فیلتر نوسان شدید (EXTREME_VOLATILITY) و بازار فرسایشی/مرده (CHOPPY_NO_TRADE)
        if atr_ratio >= self.extreme_vol_threshold:
            return {
                "regime": "EXTREME_VOLATILITY",
                "strategy": "NONE",
                "tradable": False,
                "htf_bias": htf_bias,
                "adx": adx_val,
                "trend_strength": adx_val,
                "atr_ratio": atr_ratio,
                "ema20_1h": round(ema20_1h, 6),
                "ema50_1h": round(ema50_1h, 6),
                "ema200_1h": round(ema200_1h, 6),
                "reason": f"Extreme volatility shock detected (ATR ratio {atr_ratio} >= {self.extreme_vol_threshold})",
            }

        if atr_ratio <= self.choppy_vol_threshold:
            return {
                "regime": "CHOPPY_NO_TRADE",
                "strategy": "NONE",
                "tradable": False,
                "htf_bias": htf_bias,
                "adx": adx_val,
                "trend_strength": adx_val,
                "atr_ratio": atr_ratio,
                "ema20_1h": round(ema20_1h, 6),
                "ema50_1h": round(ema50_1h, 6),
                "ema200_1h": round(ema200_1h, 6),
                "reason": f"Choppy / dead market volatility (ATR ratio {atr_ratio} <= {self.choppy_vol_threshold})",
            }

        # ۶. تشخیص رژیم رونددار (TRENDING_BULL / TRENDING_BEAR) یا رنج (RANGING)
        is_bull_aligned = current_price >= ema20_1h and ema20_1h > ema50_1h
        is_bear_aligned = current_price <= ema20_1h and ema20_1h < ema50_1h

        if adx_val >= self.adx_trend_threshold and is_bull_aligned:
            regime = "TRENDING_BULL"
            strategy = "SMC_TREND_CONTINUATION"
            reason = f"Bullish trend (ADX {adx_val:.1f} >= {self.adx_trend_threshold}, EMA20 > EMA50)"
        elif adx_val >= self.adx_trend_threshold and is_bear_aligned:
            regime = "TRENDING_BEAR"
            strategy = "SMC_TREND_CONTINUATION"
            reason = f"Bearish trend (ADX {adx_val:.1f} >= {self.adx_trend_threshold}, EMA20 < EMA50)"
        else:
            regime = "RANGING"
            strategy = "LIQUIDITY_SWEEP_REVERSAL"
            reason = f"Mean-reverting / ranging structure (ADX {adx_val:.1f})"

        return {
            "regime": regime,
            "strategy": strategy,
            "tradable": True,
            "htf_bias": htf_bias,
            "adx": adx_val,
            "trend_strength": adx_val,
            "atr_ratio": atr_ratio,
            "ema20_1h": round(ema20_1h, 6),
            "ema50_1h": round(ema50_1h, 6),
            "ema200_1h": round(ema200_1h, 6),
            "reason": reason,
        }
