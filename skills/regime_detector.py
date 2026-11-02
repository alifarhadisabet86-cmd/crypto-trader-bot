"""
مهارت اول: تشخیص رژیم بازار در ۱ ساعته و ۴ ساعته + فیلتر شوک خبری (Regime Detector Skill)
Institutional Trading Bot V2.5 - Market Regime & Volatility Filter
"""

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


class RegimeDetectorSkill:
    """
    کلاس تشخیص رژیم بازار (TRENDING_BULL, TRENDING_BEAR, RANGING, NEWS_SHOCK, DEAD_MARKET)
    با استفاده از EMA 20/50، نسبت کارایی کافمن (ADX Proxy) و رادار نوسان ATR.
    """

    def __init__(self) -> None:
        self.ema_fast_period: int = 20
        self.ema_slow_period: int = 50
        self.er_lookback: int = 16
        self.atr_baseline_window: int = 40
        self.news_shock_threshold: float = 2.40
        self.dead_market_threshold: float = 0.40
        self.trend_strength_threshold: float = 28.0

    def _calculate_adx_proxy(self, df: pd.DataFrame, period: int = 16) -> float:
        """
        محاسبه قدرت روند بر پایه فرمول Efficiency Ratio کافمن در ۱۶ کندل اخیر.
        خروجی عددی بین ۰ تا ۱۰۰ است.
        """
        if df is None or len(df) < 3:
            return 0.0

        closes = df["close"].astype(float).values
        lookback = min(period, len(closes) - 1)
        if lookback <= 0:
            return 0.0

        net_change = abs(closes[-1] - closes[-1 - lookback])
        step_changes = np.sum(np.abs(np.diff(closes[-(lookback + 1):])))

        if step_changes <= 1e-12:
            return 0.0

        er_ratio = (net_change / step_changes) * 100.0
        return float(np.clip(round(er_ratio, 2), 0.0, 100.0))

    @staticmethod
    def _compute_ema(series: pd.Series, span: int) -> pd.Series:
        """محاسبه میانگین متحرک نمایی (EMA)."""
        return series.astype(float).ewm(span=span, adjust=False).mean()

    def _determine_htf_bias(self, df_4h: Optional[pd.DataFrame]) -> str:
        """
        تعیین بایاس ساختار کلان ۴ ساعته (BULLISH, BEARISH, NEUTRAL).
        """
        if df_4h is None or len(df_4h) < 10:
            return "NEUTRAL"

        closes = df_4h["close"].astype(float)
        ema20 = self._compute_ema(closes, self.ema_fast_period)
        ema50 = self._compute_ema(closes, self.ema_slow_period)

        last_close = float(closes.iloc[-1])
        last_ema20 = float(ema20.iloc[-1])
        last_ema50 = float(ema50.iloc[-1])

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
        تحلیل کندل‌های 1h و 4h و استخراج رژیم فعلی بازار، استراتژی مجاز، ADX و وضعیت tradable.
        """
        if df_1h is None or len(df_1h) < 20:
            return {
                "regime": "DEAD_MARKET",
                "strategy": "NONE",
                "tradable": False,
                "htf_bias": "NEUTRAL",
                "adx": 0.0,
                "trend_strength": 0.0,
                "atr_ratio": 0.0,
                "ema20_1h": 0.0,
                "ema50_1h": 0.0,
                "reason": "Insufficient 1H candle data",
            }

        # ۱. تعیین بایاس ۴ ساعته
        htf_bias = self._determine_htf_bias(df_4h if df_4h is not None else df_1h)

        # ۲. محاسبه EMA 20 و EMA 50 در تایم‌فریم ۱ ساعته
        closes_1h = df_1h["close"].astype(float)
        ema20_series = self._compute_ema(closes_1h, self.ema_fast_period)
        ema50_series = self._compute_ema(closes_1h, self.ema_slow_period)

        current_price = float(closes_1h.iloc[-1])
        ema20_1h = float(ema20_series.iloc[-1])
        ema50_1h = float(ema50_series.iloc[-1])

        # ۳. محاسبه قدرت روند (Efficiency Ratio / ADX Proxy)
        trend_strength = self._calculate_adx_proxy(df_1h, period=self.er_lookback)

        # ۴. محاسبه atr_ratio (نسبت ATR فعلی ۱ ساعته به میانگین ۴۰ کندل اخیر)
        if "atr" in df_1h.columns and not df_1h["atr"].isna().all():
            atr_series = df_1h["atr"].astype(float)
        else:
            atr_series = (df_1h["high"].astype(float) - df_1h["low"].astype(float))

        current_atr = float(atr_series.iloc[-1])
        baseline_window = min(self.atr_baseline_window, len(atr_series))
        mean_atr = float(atr_series.iloc[-baseline_window:].mean())
        atr_ratio = round(current_atr / mean_atr, 2) if mean_atr > 1e-12 else 1.0

        # ۵. فیلتر شوک خبری (NEWS_SHOCK) و بازار مرده (DEAD_MARKET)
        if atr_ratio >= self.news_shock_threshold:
            return {
                "regime": "NEWS_SHOCK",
                "strategy": "NONE",
                "tradable": False,
                "htf_bias": htf_bias,
                "adx": trend_strength,
                "trend_strength": trend_strength,
                "atr_ratio": atr_ratio,
                "ema20_1h": round(ema20_1h, 6),
                "ema50_1h": round(ema50_1h, 6),
                "reason": f"Extreme volatility shock detected (ATR ratio {atr_ratio} >= {self.news_shock_threshold})",
            }

        if atr_ratio <= self.dead_market_threshold:
            return {
                "regime": "DEAD_MARKET",
                "strategy": "NONE",
                "tradable": False,
                "htf_bias": htf_bias,
                "adx": trend_strength,
                "trend_strength": trend_strength,
                "atr_ratio": atr_ratio,
                "ema20_1h": round(ema20_1h, 6),
                "ema50_1h": round(ema50_1h, 6),
                "reason": f"Dead market / ultra-low volatility (ATR ratio {atr_ratio} <= {self.dead_market_threshold})",
            }

        # ۶. تشخیص رژیم رونددار (TRENDING_BULL / TRENDING_BEAR) یا رنج (RANGING)
        is_bull_aligned = current_price > ema20_1h and ema20_1h > ema50_1h
        is_bear_aligned = current_price < ema20_1h and ema20_1h < ema50_1h

        if trend_strength >= self.trend_strength_threshold and is_bull_aligned:
            regime = "TRENDING_BULL"
            strategy = "TREND_PULLBACK"
            reason = f"Strong bullish trend (Strength {trend_strength} >= 28, Price > EMA20 > EMA50)"
        elif trend_strength >= self.trend_strength_threshold and is_bear_aligned:
            regime = "TRENDING_BEAR"
            strategy = "TREND_PULLBACK"
            reason = f"Strong bearish trend (Strength {trend_strength} >= 28, Price < EMA20 < EMA50)"
        else:
            regime = "RANGING"
            strategy = "LIQUIDITY_SWEEP_RANGE"
            reason = f"Mean-reverting / ranging structure (Strength {trend_strength})"

        return {
            "regime": regime,
            "strategy": strategy,
            "tradable": True,
            "htf_bias": htf_bias,
            "adx": trend_strength,
            "trend_strength": trend_strength,
            "atr_ratio": atr_ratio,
            "ema20_1h": round(ema20_1h, 6),
            "ema50_1h": round(ema50_1h, 6),
            "reason": reason,
        }
