"""
موتور دریافت دیتای بازار، محاسبه ATR، اسپرد لحظه‌ای و تحلیل اردربوک (Data Engine)
Institutional Trading Bot V2 - Market Data & Microstructure Engine
"""

import time
from typing import Dict, Any, Optional

import ccxt
import numpy as np
import pandas as pd

from core.config import WATCHLIST, EXECUTION_RULES


class DataEngine:
    """
    کلاس اتصال به صرافی مرجع دیتا (KuCoin) با CCXT برای دریافت کندل‌ها،
    اسپرد زنده و جریان سفارشات (OrderBook Imbalance).
    """

    def __init__(self, exchange_id: Optional[str] = None) -> None:
        self.exchange_id: str = exchange_id or EXECUTION_RULES.get("cloud_data_feed", "kucoin")
        exchange_class = getattr(ccxt, self.exchange_id, ccxt.kucoin)
        self.exchange: ccxt.Exchange = exchange_class({
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {
                "defaultType": "spot",
            },
        })

    @staticmethod
    def resolve_symbol(coin_or_symbol: str) -> str:
        """
        تبدیل نام دارایی به نماد استاندارد صرافی:
        XAU, XAUUSD, GOLD -> PAXG/USDT
        سایر کلیدها -> <COIN>/USDT
        """
        clean = coin_or_symbol.strip().upper()
        if clean in ("XAU", "XAUUSD", "GOLD", "XAU/USDT"):
            return "PAXG/USDT"
        if clean in WATCHLIST:
            return str(WATCHLIST[clean]["symbol"])
        if "/" in clean:
            return clean
        return f"{clean}/USDT"

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        محاسبه دقیق Average True Range (ATR) با دوره ۱۴ بر پایه میانگین متحرک.
        """
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period, min_periods=1).mean()
        return atr.bfill().fillna(tr1)

    def fetch_ohlcv(
        self,
        coin_or_symbol: str,
        timeframe: str = "15m",
        limit: int = 120,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """
        دریافت کندل‌ها با حداکثر ۳ بار تلاش مجدد (Retry)، حذف Timestampهای تکراری،
        مرتب‌سازی صعودی و محاسبه ستون atr با دوره ۱۴.
        """
        symbol = self.resolve_symbol(coin_or_symbol)
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                raw_ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                if not raw_ohlcv or len(raw_ohlcv) == 0:
                    raise ValueError(f"Empty OHLCV returned for {symbol} ({timeframe})")

                df = pd.DataFrame(
                    raw_ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )

                # حذف Timestampهای تکراری و مرتب‌سازی صعودی
                df = df.drop_duplicates(subset=["timestamp"], keep="last")
                df = df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)

                # تبدیل نوع داده‌ها به عدد اعشاری استاندارد
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df["atr"] = self._compute_atr(df, period=14)

                return df

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(0.8 * attempt)

        print(f"⚠️ [DataEngine] Failed to fetch OHLCV for {symbol} ({timeframe}) after {max_retries} retries: {last_error}")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "datetime", "atr"])

    def fetch_live_spread(self, coin_or_symbol: str) -> Dict[str, Any]:
        """
        دریافت bid و ask لحظه‌ای و محاسبه spread_abs و spread_pct.
        """
        symbol = self.resolve_symbol(coin_or_symbol)
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            bid = float(ticker.get("bid") or 0.0)
            ask = float(ticker.get("ask") or 0.0)
            last_price = float(ticker.get("last") or ticker.get("close") or 0.0)

            # اگر در لحظه خاص bid یا ask در تیکر نبود، از اردربوک سطح اول بگیرد
            if bid <= 0.0 or ask <= 0.0:
                ob = self.exchange.fetch_order_book(symbol, limit=5)
                if ob.get("bids") and len(ob["bids"]) > 0:
                    bid = float(ob["bids"][0][0])
                if ob.get("asks") and len(ob["asks"]) > 0:
                    ask = float(ob["asks"][0][0])

            if bid > 0.0 and ask > 0.0 and ask >= bid:
                spread_abs = round(ask - bid, 8)
                mid_price = (ask + bid) / 2.0
                spread_pct = round((spread_abs / mid_price) * 100.0, 6) if mid_price > 0 else 0.0
                return {
                    "symbol": symbol,
                    "bid": bid,
                    "ask": ask,
                    "last": last_price if last_price > 0 else mid_price,
                    "spread_abs": spread_abs,
                    "spread_pct": spread_pct,
                    "valid": True,
                }
        except Exception as e:
            print(f"⚠️ [DataEngine] Error fetching live spread for {symbol}: {e}")

        return {
            "symbol": symbol,
            "bid": 0.0,
            "ask": 0.0,
            "last": 0.0,
            "spread_abs": 0.0,
            "spread_pct": 0.0,
            "valid": False,
        }

    def fetch_order_book_imbalance(self, coin_or_symbol: str, depth: int = 20) -> Dict[str, Any]:
        """
        جمع حجم ۲۰ سفارش اول bids و asks؛ محاسبه buy_pressure_pct.
        بالای ۵۸٪ = BUY_WALL، زیر ۴۲٪ = SELL_WALL، بین این دو = BALANCED.
        """
        symbol = self.resolve_symbol(coin_or_symbol)
        try:
            ob = self.exchange.fetch_order_book(symbol, limit=depth)
            bids = ob.get("bids", [])[:depth]
            asks = ob.get("asks", [])[:depth]

            bid_vol = float(sum( float(item[1]) for item in bids if len(item) >= 2 ))
            ask_vol = float(sum( float(item[1]) for item in asks if len(item) >= 2 ))
            total_vol = bid_vol + ask_vol

            if total_vol > 0.0:
                buy_pressure_pct = round((bid_vol / total_vol) * 100.0, 2)
            else:
                buy_pressure_pct = 50.0

            if buy_pressure_pct > 58.0:
                status = "BUY_WALL"
            elif buy_pressure_pct < 42.0:
                status = "SELL_WALL"
            else:
                status = "BALANCED"

            return {
                "symbol": symbol,
                "bid_volume": round(bid_vol, 4),
                "ask_volume": round(ask_vol, 4),
                "buy_pressure_pct": buy_pressure_pct,
                "imbalance_state": status,
                "status": status,
                "valid": True,
            }
        except Exception as e:
            print(f"⚠️ [DataEngine] Error fetching OrderBook for {symbol}: {e}")
            return {
                "symbol": symbol,
                "bid_volume": 0.0,
                "ask_volume": 0.0,
                "buy_pressure_pct": 50.0,
                "imbalance_state": "BALANCED",
                "status": "BALANCED",
                "valid": False,
            }