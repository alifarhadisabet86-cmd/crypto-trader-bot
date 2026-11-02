"""
مهارت دوازدهم (نسخه V2.5 Pro): اتاق فرمان تلگرام، چارت‌های دوطبقه با حجم، کارت PnL و کیبورد شیشه‌ای نسل جدید
Institutional Trading Bot V2.5 - Telegram Command Center, Volume Charts, PnL Cards & On-Demand Radar
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "mplconfig_v25"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
import requests

from core.config import (
    CHARTS_DIR,
    TELEGRAM_CONFIG,
    WATCHLIST,
    BROKER_URLS,
    RISK_CONFIG,
    format_price,
)
from core.state_manager import StateManager


class TelegramAlertsSkill:
    """
    کلاس جامع ارتباط با تلگرام و مصورسازی سازمانی V2.5:
    - رسم چارت کندل‌استیک ۱۵ دقیقه + ساب‌چارت حجم (Volume) + FVG + سقف/کف سشن آسیا
    - رسم چارت تحلیلی درخواستی (On-Demand Asset Analysis) برای هر ۵ دارایی
    - رسم کارت گرافیکی سود/زیان (PnL Share Card) و منحنی سرمایه (Equity Curve)
    - تفکیک «بیلان شبانه جمع‌وجور» از «استاتوس جامع لحظه‌ای» و قالب ترکیبی «شکار جدید (X-Ray)»
    - کیبورد شیشه‌ای ۴ ردیفه جدید (چارت ۵ ارز، لینک بروکرها، ریسک‌فری سریع و سیو سود ۵۰٪)
    """

    DARK_BG = "#0d1117"
    PANEL_BG = "#161b22"
    GRID_COLOR = "#21262d"
    TEXT_COLOR = "#e6edf3"
    BULL_COLOR = "#2ea043"
    BEAR_COLOR = "#f85149"
    FVG_COLOR = "#d29922"
    ASIAN_COLOR = "#a371f7"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        charts_dir: Optional[Path] = None,
    ) -> None:
        self.bot_token: str = (
            bot_token if bot_token is not None else os.getenv("TELEGRAM_BOT_TOKEN", TELEGRAM_CONFIG.get("bot_token", ""))
        ).strip()
        self.chat_id: str = (
            chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CONFIG.get("chat_id", ""))
        ).strip()
        self.charts_dir: Path = charts_dir if charts_dir else CHARTS_DIR
        self.charts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    # ==========================================================================
    # ۱. کیبوردهای شیشه‌ای نسل جدید (۴ ردیف عملیاتی + کیبورد اختصاصی شکار)
    # ==========================================================================
    @staticmethod
    def build_inline_keyboard(bot_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        کیبورد ۴ ردیفه استاندارد زیر پیام‌های استاتوس و بیلان شبانه:
        - ردیف ۱ و ۲: چارت و تحلیل زنده هر ۵ ارز (BTC, ETH, SOL, XRP, XAU)
        - ردیف ۳: لینک مستقیم بروکر طلا (OpoFinance) و صرافی رمزارز (Bitunix)
        - ردیف ۴: دکمه‌های اقدام فوری [ 🛡️ ریسک‌فری سریع ] و [ 💰 سیو سود پله‌ای (۵۰٪) ]
        """
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 تحلیل BTC", "callback_data": "ANLZ_BTC"},
                    {"text": "📊 تحلیل ETH", "callback_data": "ANLZ_ETH"},
                    {"text": "📊 تحلیل SOL", "callback_data": "ANLZ_SOL"},
                ],
                [
                    {"text": "📊 تحلیل XRP", "callback_data": "ANLZ_XRP"},
                    {"text": "🪙 تحلیل طلا (XAU)", "callback_data": "ANLZ_XAU"},
                ],
                [
                    {"text": "🌐 بروکر طلا (OpoFinance)", "url": BROKER_URLS["opofinance"]},
                    {"text": "🌐 صرافی (Bitunix)", "url": BROKER_URLS["bitunix"]},
                ],
                [
                    {"text": "🛡️ ریسک‌فری سریع", "callback_data": "ACT_RISK_FREE"},
                    {"text": "💰 سیو سود پله‌ای (۵۰٪)", "callback_data": "ACT_SAVE_50"},
                ],
            ]
        }

    @staticmethod
    def build_hunt_inline_keyboard(coin: str = "XAU") -> Dict[str, Any]:
        """
        کیبورد شیشه‌ای اختصاصی زیر پیام شکار جدید (ترکیب لینک چارت زنده، بروکر و تحلیل سایر ارزها).
        """
        clean_coin = str(coin).upper().strip()
        tv_url = WATCHLIST.get(clean_coin, {}).get("tv_url", BROKER_URLS["tradingview_gold"])
        broker_label = "🏛️ بروکر OpoFinance" if clean_coin == "XAU" else "🏛️ صرافی Bitunix"
        broker_link = BROKER_URLS["opofinance"] if clean_coin == "XAU" else BROKER_URLS["bitunix"]

        return {
            "inline_keyboard": [
                [
                    {"text": f"📈 چارت زنده {clean_coin} (TradingView)", "url": tv_url},
                    {"text": broker_label, "url": broker_link},
                ],
                [
                    {"text": "📊 BTC", "callback_data": "ANLZ_BTC"},
                    {"text": "📊 ETH", "callback_data": "ANLZ_ETH"},
                    {"text": "📊 SOL", "callback_data": "ANLZ_SOL"},
                    {"text": "📊 XRP", "callback_data": "ANLZ_XRP"},
                    {"text": "🪙 طلا", "callback_data": "ANLZ_XAU"},
                ],
                [
                    {"text": "🛡️ ریسک‌فری سریع", "callback_data": "ACT_RISK_FREE"},
                    {"text": "💰 سیو سود پله‌ای (۵۰٪)", "callback_data": "ACT_SAVE_50"},
                ],
            ]
        }

    # ==========================================================================
    # ۲. موتور گرافیکی ۱: چارت دوطبقه شکار و تحلیل (Candles + Volume + FVG + Asian Range)
    # ==========================================================================
    def generate_setup_chart(
        self,
        coin: str,
        df_15m: pd.DataFrame,
        side: str,
        entry_price: float,
        stop_loss: float,
        tp1_price: float,
        tp2_price: float,
        active_fvg: Optional[Dict[str, Any]] = None,
        regime: str = "RANGING",
        asian_range: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        رسم چارت شکار ستاپ در دو پنل (کندل‌استیک + حجم معاملات) با تم تاریک،
        ناحیه FVG، سقف/کف سشن آسیا و خطوط قیمت استاندارد.
        """
        clean_coin = str(coin).upper()
        df = df_15m.tail(55).reset_index(drop=True) if len(df_15m) > 55 else df_15m.copy().reset_index(drop=True)

        fig, (ax, ax_vol) = plt.subplots(
            2, 1, figsize=(11, 6.8), dpi=130, sharex=True,
            gridspec_kw={"height_ratios": [3.6, 1.0], "hspace": 0.06},
            facecolor=self.DARK_BG,
        )
        ax.set_facecolor(self.PANEL_BG)
        ax_vol.set_facecolor(self.PANEL_BG)

        self._plot_candles_and_volume(ax, ax_vol, df)

        n_bars = max(len(df), 10)
        # رسم باکس FVG دست‌نخورده
        if isinstance(active_fvg, dict) and "top" in active_fvg and "bottom" in active_fvg:
            f_top = float(active_fvg["top"])
            f_bot = float(active_fvg["bottom"])
            fvg_rect = Rectangle(
                (0, f_bot),
                width=n_bars + 4,
                height=max(f_top - f_bot, 1e-6),
                facecolor=self.FVG_COLOR,
                edgecolor=self.FVG_COLOR,
                alpha=0.18,
                label=f"FVG Zone ({format_price(f_bot, clean_coin)} - {format_price(f_top, clean_coin)})",
            )
            ax.add_patch(fvg_rect)

        # رسم خطوط سقف و کف سشن آسیا (در صورت وجود)
        if isinstance(asian_range, dict):
            ah = float(asian_range.get("asian_high", 0.0))
            al = float(asian_range.get("asian_low", 0.0))
            if ah > 0 and al > 0:
                ax.axhline(ah, color=self.ASIAN_COLOR, linestyle=":", linewidth=1.0, alpha=0.75, label=f"Asian High: {format_price(ah, clean_coin)}")
                ax.axhline(al, color=self.ASIAN_COLOR, linestyle=":", linewidth=1.0, alpha=0.75, label=f"Asian Low: {format_price(al, clean_coin)}")

        # رسم خطوط ورود، استاپ، TP1 و TP2
        ax.axhline(entry_price, color="#58a6ff", linestyle="--", linewidth=1.5, label=f"LIMIT ENTRY: {format_price(entry_price, clean_coin)}")
        ax.axhline(stop_loss, color="#f85149", linestyle="-", linewidth=1.6, label=f"STOP LOSS: {format_price(stop_loss, clean_coin)}")
        ax.axhline(tp1_price, color="#d29922", linestyle="-.", linewidth=1.4, label=f"TP1 (50% + Risk-Free): {format_price(tp1_price, clean_coin)}")
        ax.axhline(tp2_price, color="#3fb950", linestyle="-", linewidth=1.7, label=f"TP2 (Final Target): {format_price(tp2_price, clean_coin)}")

        symbol_str = WATCHLIST.get(clean_coin, {}).get("symbol", f"{clean_coin}/USDT")
        ax.set_title(
            f"INSTITUTIONAL V2.5 | {clean_coin} ({symbol_str}) — {side.upper()} | Regime: {regime}",
            color=self.TEXT_COLOR, fontsize=11, fontweight="bold", pad=10,
        )

        self._style_axes(ax, ax_vol, n_bars)
        ax.legend(loc="upper left", facecolor=self.DARK_BG, edgecolor=self.GRID_COLOR, labelcolor=self.TEXT_COLOR, fontsize=8)

        out_path = self.charts_dir / f"setup_{clean_coin.lower()}.png"
        fig.savefig(out_path, bbox_inches="tight", facecolor=self.DARK_BG)
        plt.close(fig)
        return str(out_path)

    def generate_asset_analysis_chart(
        self,
        coin: str,
        df_15m: pd.DataFrame,
        scan_data: Dict[str, Any],
        regime_data: Dict[str, Any],
    ) -> str:
        """
        رسم چارت تحلیلی درخواستی (On-Demand Analysis Chart) وقتی کاربر روی دکمه شیشه‌ای
        [ 📊 تحلیل BTC / ETH / SOL / XRP / XAU ] کلیک می‌کند.
        """
        clean_coin = str(coin).upper()
        df = df_15m.tail(55).reset_index(drop=True) if len(df_15m) > 55 else df_15m.copy().reset_index(drop=True)

        fig, (ax, ax_vol) = plt.subplots(
            2, 1, figsize=(11, 6.5), dpi=130, sharex=True,
            gridspec_kw={"height_ratios": [3.5, 1.0], "hspace": 0.06},
            facecolor=self.DARK_BG,
        )
        ax.set_facecolor(self.PANEL_BG)
        ax_vol.set_facecolor(self.PANEL_BG)

        self._plot_candles_and_volume(ax, ax_vol, df)
        n_bars = max(len(df), 10)

        curr_p = float(scan_data.get("current_price", df["close"].iloc[-1] if not df.empty else 0.0))
        sw_high = float(scan_data.get("swing_high", 0.0))
        sw_low = float(scan_data.get("swing_low", 0.0))

        if sw_high > 0 and sw_low > 0:
            eq_mid = (sw_high + sw_low) / 2.0
            ax.axhline(sw_high, color="#f85149", linestyle="--", linewidth=1.2, alpha=0.8, label=f"Swing High Pool: {format_price(sw_high, clean_coin)}")
            ax.axhline(eq_mid, color="#8b949e", linestyle=":", linewidth=1.0, alpha=0.7, label=f"Equilibrium (50%): {format_price(eq_mid, clean_coin)}")
            ax.axhline(sw_low, color="#3fb950", linestyle="--", linewidth=1.2, alpha=0.8, label=f"Swing Low Pool: {format_price(sw_low, clean_coin)}")

        active_fvg = scan_data.get("active_fvg")
        if isinstance(active_fvg, dict) and "top" in active_fvg and "bottom" in active_fvg:
            f_top = float(active_fvg["top"])
            f_bot = float(active_fvg["bottom"])
            rect = Rectangle(
                (0, f_bot), width=n_bars + 4, height=max(f_top - f_bot, 1e-6),
                facecolor=self.FVG_COLOR, edgecolor=self.FVG_COLOR, alpha=0.20,
                label=f"Active {active_fvg.get('type','')} FVG ({format_price(f_bot, clean_coin)} - {format_price(f_top, clean_coin)})",
            )
            ax.add_patch(rect)

        asian_range = scan_data.get("asian_range", {})
        if isinstance(asian_range, dict) and float(asian_range.get("asian_high", 0.0)) > 0:
            ah = float(asian_range["asian_high"])
            al = float(asian_range["asian_low"])
            ax.axhline(ah, color=self.ASIAN_COLOR, linestyle="-.", linewidth=1.0, alpha=0.7, label=f"Asian High: {format_price(ah, clean_coin)}")
            ax.axhline(al, color=self.ASIAN_COLOR, linestyle="-.", linewidth=1.0, alpha=0.7, label=f"Asian Low: {format_price(al, clean_coin)}")

        if curr_p > 0:
            ax.axhline(curr_p, color="#58a6ff", linestyle="-", linewidth=1.3, label=f"Live Price: {format_price(curr_p, clean_coin)}")

        reg_name = regime_data.get("regime", "RANGING")
        htf_bias = regime_data.get("htf_bias", "NEUTRAL")
        ax.set_title(
            f"LIVE RADAR X-RAY | {clean_coin}/USDT (15m) | Regime: {reg_name} | 4H Bias: {htf_bias}",
            color=self.TEXT_COLOR, fontsize=11, fontweight="bold", pad=10,
        )

        self._style_axes(ax, ax_vol, n_bars)
        ax.legend(loc="upper left", facecolor=self.DARK_BG, edgecolor=self.GRID_COLOR, labelcolor=self.TEXT_COLOR, fontsize=8)

        out_path = self.charts_dir / f"radar_{clean_coin.lower()}.png"
        fig.savefig(out_path, bbox_inches="tight", facecolor=self.DARK_BG)
        plt.close(fig)
        return str(out_path)

    def _plot_candles_and_volume(self, ax: Any, ax_vol: Any, df: pd.DataFrame) -> None:
        if df.empty:
            return
        opens = df["open"].astype(float).values
        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        vols = df["volume"].astype(float).values if "volume" in df.columns else np.ones(len(df))

        price_span = max(float(np.max(highs) - np.min(lows)), 1e-6)
        min_body = price_span * 0.003

        colors = [self.BULL_COLOR if closes[i] >= opens[i] else self.BEAR_COLOR for i in range(len(df))]

        for i in range(len(df)):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            color = colors[i]
            ax.plot([i, i], [l, h], color=color, linewidth=1.1, zorder=2)
            body_bottom = min(o, c)
            body_height = max(abs(c - o), min_body)
            rect = Rectangle(
                (i - 0.32, body_bottom), width=0.64, height=body_height,
                facecolor=color, edgecolor=color, alpha=0.92, zorder=3,
            )
            ax.add_patch(rect)

        x_idx = np.arange(len(df))
        ax_vol.bar(x_idx, vols, width=0.64, color=colors, alpha=0.75, zorder=2)
        if len(vols) >= 5:
            vol_sma = pd.Series(vols).rolling(min(20, len(vols)), min_periods=1).mean().values
            ax_vol.plot(x_idx, vol_sma, color="#58a6ff", linewidth=1.1, alpha=0.85, label="Vol SMA20")

    def _style_axes(self, ax: Any, ax_vol: Any, n_bars: int) -> None:
        ax.set_xlim(-1, n_bars + 3)
        ax.grid(True, color=self.GRID_COLOR, linestyle=":", linewidth=0.7, alpha=0.7)
        ax_vol.grid(True, color=self.GRID_COLOR, linestyle=":", linewidth=0.6, alpha=0.5)
        ax.tick_params(colors=self.TEXT_COLOR, labelsize=8)
        ax_vol.tick_params(colors=self.TEXT_COLOR, labelsize=7)
        ax_vol.set_ylabel("Vol", color="#8b949e", fontsize=8)
        for a in (ax, ax_vol):
            for spine in a.spines.values():
                spine.set_color(self.GRID_COLOR)

    # ==========================================================================
    # ۳. موتور گرافیکی ۲: کارت سود/زیان (PnL Share Card) و چارت منحنی سرمایه
    # ==========================================================================
    def generate_pnl_card(
        self,
        trade_record: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> str:
        """
        تولید کارت گرافیکی سود/زیان (PnL Share Card) با تم دارک سازمانی هنگام بسته شدن معامله.
        """
        coin = str(trade_record.get("coin", "BTC")).upper()
        side = str(trade_record.get("side", "LONG")).upper()
        pnl_usdt = float(trade_record.get("net_pnl_usdt", trade_record.get("pnl_usdt", 0.0)))
        r_mult = float(trade_record.get("r_multiple", trade_record.get("realized_r", 0.0)))
        entry_p = float(trade_record.get("entry_price", 0.0))
        exit_p = float(trade_record.get("exit_price", 0.0))
        reason = str(trade_record.get("exit_reason", trade_record.get("close_reason", "TARGET_HIT")))

        is_win = pnl_usdt >= 0.0
        accent_color = self.BULL_COLOR if is_win else self.BEAR_COLOR
        sign = "+" if pnl_usdt >= 0 else ""

        gate = StateManager.get_paper_gate_progress(portfolio)

        fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=130, facecolor=self.DARK_BG)
        ax.set_facecolor(self.PANEL_BG)
        ax.axis("off")

        border = Rectangle((0.02, 0.04), 0.96, 0.92, fill=False, edgecolor=accent_color, linewidth=2.2, transform=ax.transAxes)
        ax.add_patch(border)

        ax.text(0.07, 0.84, "INSTITUTIONAL TRADING BOT V2.5 — PNL CARD", color="#8b949e", fontsize=10, fontweight="bold", transform=ax.transAxes)
        ax.text(0.07, 0.68, f"{coin}/USDT  |  {side}", color=self.TEXT_COLOR, fontsize=20, fontweight="bold", transform=ax.transAxes)
        ax.text(0.07, 0.44, f"{sign}{r_mult:.2f}R   ({sign}${pnl_usdt:.2f})", color=accent_color, fontsize=28, fontweight="bold", transform=ax.transAxes)

        info_line = (
            f"Entry: {format_price(entry_p, coin)}   |   "
            f"Exit: {format_price(exit_p, coin)}   |   "
            f"Reason: {reason}"
        )
        ax.text(0.07, 0.25, info_line, color=self.TEXT_COLOR, fontsize=10.5, transform=ax.transAxes)

        footer_line = (
            f"Balance: ${float(portfolio.get('balance_usdt', 1000.0)):,.2f}   |   "
            f"50-Trade Paper Gate: {gate['completed_trades']}/{gate['target_trades']} ({gate['progress_pct']:.0f}%)"
        )
        ax.text(0.07, 0.11, footer_line, color="#58a6ff", fontsize=9.5, fontweight="bold", transform=ax.transAxes)

        out_path = self.charts_dir / f"pnl_card_{coin.lower()}.png"
        fig.savefig(out_path, bbox_inches="tight", facecolor=self.DARK_BG)
        plt.close(fig)
        return str(out_path)

    def generate_equity_chart(self, portfolio: Dict[str, Any]) -> str:
        curve = portfolio.get("equity_curve", [])
        equities = [float(pt.get("equity", 1000.0)) for pt in curve] if curve else [1000.0]
        if len(equities) == 1:
            equities = [equities[0], equities[0]]

        init_bal = float(portfolio.get("initial_balance_usdt", 1000.0))
        curr_bal = float(portfolio.get("balance_usdt", equities[-1]))
        line_color = self.BULL_COLOR if curr_bal >= init_bal else self.BEAR_COLOR

        fig, ax = plt.subplots(figsize=(10, 4.5), dpi=130, facecolor=self.DARK_BG)
        ax.set_facecolor(self.PANEL_BG)

        x_vals = list(range(len(equities)))
        ax.plot(x_vals, equities, color=line_color, linewidth=2.3, marker="o", markersize=3.5, label="Portfolio Equity (USDT)")
        ax.axhline(init_bal, color="#8b949e", linestyle="--", linewidth=1.0, label=f"Initial Baseline (${init_bal:,.2f})")
        ax.fill_between(x_vals, equities, init_bal, color=line_color, alpha=0.12)

        pnl_pct = ((curr_bal - init_bal) / max(init_bal, 1e-8)) * 100.0
        gate = StateManager.get_paper_gate_progress(portfolio)
        ax.set_title(
            f"Institutional Portfolio V2.5 — Balance: ${curr_bal:,.2f} ({pnl_pct:+.2f}%) | Paper Gate: {gate['completed_trades']}/{gate['target_trades']}",
            color=self.TEXT_COLOR, fontsize=10.5, fontweight="bold", pad=10,
        )
        ax.set_xlabel("Trade Checkpoints", color=self.TEXT_COLOR, fontsize=9)
        ax.set_ylabel("Equity (USDT)", color=self.TEXT_COLOR, fontsize=9)
        ax.grid(True, color=self.GRID_COLOR, linestyle=":", linewidth=0.8)
        ax.tick_params(colors=self.TEXT_COLOR, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(self.GRID_COLOR)

        ax.legend(loc="upper left", facecolor=self.DARK_BG, edgecolor=self.GRID_COLOR, labelcolor=self.TEXT_COLOR, fontsize=8)

        out_path = self.charts_dir / "equity_curve.png"
        fig.savefig(out_path, bbox_inches="tight", facecolor=self.DARK_BG)
        plt.close(fig)
        return str(out_path)

    # ==========================================================================
    # ۴. قالب‌های متنی تلگرام (تفکیک بیلان شبانه، استاتوس جامع، شکار جدید و تحلیل ارز)
    # ==========================================================================
    def build_nightly_pulse_report(
        self,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        shadow_portfolio: Dict[str, Any],
        sentiment_data: Dict[str, Any],
    ) -> str:
        """
        ۱. بیلان شبانه (Nightly Pulse): جمع‌وجور، مدیریتی و متمرکز بر دارایی، سود/زیان پوزیشن‌ها و دروازه ۵۰ ترید.
        """
        bal = float(portfolio.get("balance_usdt", 1000.0))
        init_bal = float(portfolio.get("initial_balance_usdt", 1000.0))
        total_pnl_pct = ((bal - init_bal) / max(init_bal, 1e-8)) * 100.0
        daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        open_pos = portfolio.get("open_positions", [])
        unrealized_total = sum(float(p.get("unrealized_pnl_usdt", 0.0)) for p in open_pos)

        gate = StateManager.get_paper_gate_progress(portfolio)
        sh_stats = shadow_portfolio.get("stats", {})
        filtered_cnt = int(sh_stats.get("total_filtered", 0))
        saved_cnt = int(sh_stats.get("saved_from_loss", 0))

        sys_badge = "🟢 روشن و ایمن"
        if bot_config.get("panic_mode"):
            sys_badge = "🚨 قفل اضطراری"
        elif portfolio.get("daily_circuit_breaker") or portfolio.get("weekly_circuit_breaker"):
            sys_badge = "🔒 مدارشکن فعال"
        elif bot_config.get("is_paused"):
            sys_badge = "⏸ متوقف (Paused)"

        pos_lines: List[str] = []
        if not open_pos:
            pos_lines.append("  └ <i>هیچ پوزیشن بازی وجود ندارد (0/5)</i>")
        else:
            for idx, p in enumerate(open_pos, start=1):
                c = p["coin"]
                s = p["side"]
                u_pnl = float(p.get("unrealized_pnl_usdt", 0.0))
                margin_u = max(float(p.get("margin_used_usdt", 1.0)), 1e-8)
                u_pct = (u_pnl / margin_u) * 100.0
                st_icon = "🛡️ Risk-Free" if (p.get("is_risk_free") or p.get("risk_free")) else "⚡ فعال"
                pnl_ic = "🟢" if u_pnl >= 0 else "🔴"
                pos_lines.append(
                    f"  {idx}. {pnl_ic} <b>{c}</b> ({s}) | PnL: <code>{u_pnl:+.2f}$ ({u_pct:+.1f}%)</code> | {st_icon}"
                )

        fng_val = sentiment_data.get("value", 50)
        fng_cls = sentiment_data.get("classification", "Neutral")
        fng_bar = sentiment_data.get("bar", "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜")

        lines = [
            "🌙 <b>پالس و بیلان شبانه ربات سازمانی (V2.5 Pro)</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"🤖 <b>وضعیت سیستم:</b> <code>{sys_badge}</code> | <b>حالت:</b> <code>{gate['mode']}</code>",
            f"💰 <b>موجودی نقد:</b> <code>${bal:,.2f}</code> (<code>{total_pnl_pct:+.2f}%</code>)",
            f"📅 <b>سود/زیان امروز:</b> <code>{daily_pnl:+.2f}$</code> | <b>شناور فعلی:</b> <code>{unrealized_total:+.2f}$</code>",
            "",
            f"🎯 <b>دروازه ۵۰ معامله کاغذی:</b> <code>{gate['completed_trades']}/{gate['target_trades']}</code> (برد: <code>{gate['win_rate_pct']:.1f}%</code>)",
            f"{gate['bar']} <code>{gate['progress_pct']:.0f}%</code>",
            "",
            f"📂 <b>پوزیشن‌های باز و سود/زیان ({len(open_pos)}/5):</b>",
            *pos_lines,
            "",
            f"🛡️ <b>سپر رادار سایه:</b> <code>{filtered_cnt}</code> ردشده | <code>{saved_cnt}</code> نجات قطعی از استاپ",
            f"🧭 <b>سنتیمنت بازار:</b> <code>{fng_val} ({fng_cls})</code>\n{fng_bar}",
        ]
        return "\n".join(lines)

    def build_status_report(
        self,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        shadow_portfolio: Dict[str, Any],
        sentiment_data: Dict[str, Any],
        title: str = "🏛️ اتاق فرمان ربات سازمانی V2.5 | گزارش جامع وضعیت",
        market_regimes: Optional[Dict[str, Any]] = None,
        strategy_memory: Optional[Dict[str, Any]] = None,
        news_status: Optional[Dict[str, Any]] = None,
        killzone_status: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        ۲. استاتوس جامع لحظه‌ای (Comprehensive Live Status):
        شامل تمام جزئیات مالی، مارجین آزاد/درگیر، وضعیت سشن و خبر اقتصادی،
        پوزیشن‌های باز با قیمت‌های گردشده، ماتریس رادار ۵ ارز و ضرایب ML.
        """
        bal = float(portfolio.get("balance_usdt", 1000.0))
        init_bal = float(portfolio.get("initial_balance_usdt", 1000.0))
        total_pnl_pct = ((bal - init_bal) / max(init_bal, 1e-8)) * 100.0
        daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        weekly_pnl = float(portfolio.get("weekly_pnl_usdt", 0.0))
        stats = portfolio.get("stats", {})
        max_dd = float(stats.get("max_drawdown_pct", 0.0))

        open_pos = portfolio.get("open_positions", [])
        unrealized_total = sum(float(p.get("unrealized_pnl_usdt", 0.0)) for p in open_pos)
        used_margin = sum(float(p.get("margin_used_usdt", 0.0)) for p in open_pos)
        used_margin_pct = (used_margin / max(bal, 1e-8)) * 100.0

        gate = StateManager.get_paper_gate_progress(portfolio)

        # وضعیت سیستم و مدارشکن‌ها
        sys_state = "🟢 روشن و در حال شکار"
        if bot_config.get("panic_mode"):
            sys_state = "🚨 قفل اضطراری (PANIC)"
        elif bot_config.get("is_paused"):
            sys_state = "⏸ متوقف موقت (PAUSED)"

        cb_daily = "🔒 قفل (۲٪)" if portfolio.get("daily_circuit_breaker") else "🟢 ایمن"
        cb_weekly = "🔒 قفل (۵٪)" if portfolio.get("weekly_circuit_breaker") else "🟢 ایمن"

        # پوزیشن‌های باز با اعشار استاندارد
        pos_lines: List[str] = []
        if not open_pos:
            pos_lines.append("  └ <i>هیچ پوزیشن بازی وجود ندارد (0/5 اسلات)</i>")
        else:
            for idx, p in enumerate(open_pos, start=1):
                c = p["coin"]
                s = p["side"]
                sc = float(p.get("confluence_score", p.get("score", 70.0)))
                ep = format_price(p.get("entry_price", 0.0), c)
                sl = format_price(p.get("stop_loss", p.get("current_stop_loss", 0.0)), c)
                tp1 = format_price(p.get("tp1_breakeven", p.get("tp1_price", 0.0)), c)
                tp2 = format_price(p.get("tp2_final", p.get("tp2_price", 0.0)), c)
                u_pnl = float(p.get("unrealized_pnl_usdt", 0.0))
                r_usdt = float(p.get("initial_risk_usdt", p.get("risk_amount_usdt", 3.75)))
                if p.get("trailing_active"):
                    st_badge = "🚀 تریلینگ"
                elif p.get("is_risk_free") or p.get("risk_free"):
                    st_badge = "🛡️ ریسک‌فری"
                else:
                    st_badge = "⚡ فعال"
                pos_lines.append(
                    f"{idx}. <b>{c} ({s})</b> | PnL: <code>{u_pnl:+.2f}$</code> | {st_badge} (امتیاز: <code>{sc:.0f}</code> | ریسک: <code>{r_usdt:.2f}$</code>)\n"
                    f"   └ ورود: <code>{ep}</code> | SL: <code>{sl}</code> | TP1: <code>{tp1}</code> | TP2: <code>{tp2}</code>"
                )

        # خلاصه رادار ۵ دارایی
        radar_lines: List[str] = []
        regimes_dict = market_regimes or {}
        if "regimes" in regimes_dict and isinstance(regimes_dict["regimes"], dict):
            regimes_dict = regimes_dict["regimes"]
        for coin_key in WATCHLIST.keys():
            r_info = regimes_dict.get(coin_key, {})
            if isinstance(r_info, dict) and r_info:
                reg_lbl = r_info.get("regime", "RANGING")
                side_lbl = r_info.get("candidate_side", "NONE")
                score_lbl = float(r_info.get("confluence_score", 0.0))
                price_lbl = format_price(r_info.get("current_price", 0.0), coin_key)
                radar_lines.append(
                    f" • <b>{coin_key}</b> (<code>{price_lbl}</code>) | <code>{reg_lbl}</code> ➔ <b>{side_lbl}</b> (<code>{score_lbl:.0f}/100</code>)"
                )

        if not radar_lines:
            radar_lines.append(" • <i>در انتظار بروزرسانی اسکنر...</i>")

        # سپر سایه و ضرایب ML
        sh_stats = shadow_portfolio.get("stats", {})
        sh_filtered = int(sh_stats.get("total_filtered", 0))
        sh_saved = int(sh_stats.get("saved_from_loss", 0))
        sh_eval = int(sh_stats.get("evaluated_count", sh_saved + int(sh_stats.get("missed_winners", 0))))
        sh_acc_str = f"{float(sh_stats.get('shield_accuracy', 0.0)):.1f}%" if sh_eval > 0 else "در حال پایش"

        ml_line = ""
        if isinstance(strategy_memory, dict) and "coin_multipliers" in strategy_memory:
            cm = strategy_memory["coin_multipliers"]
            ml_line = " | ".join([f"{k}:<code>{float(cm.get(k, 1.0)):.2f}x</code>" for k in WATCHLIST.keys()])

        session_str = (killzone_status or {}).get("session_fa", "🌐 سشن جهانی در جریان")
        news_str = (news_status or {}).get("summary_fa", "🟢 تقویم اقتصادی ایمن")

        fng_val = sentiment_data.get("value", 50)
        fng_cls = sentiment_data.get("classification", "Neutral")
        fng_bar = sentiment_data.get("bar", "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜")

        lines = [
            f"<b>{title}</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"🤖 <b>وضعیت:</b> {sys_state} | 🛡️ <b>مدارشکن روزانه:</b> {cb_daily} | <b>هفتگی:</b> {cb_weekly}",
            f"💰 <b>موجودی نقد:</b> <code>${bal:,.2f}</code> (<code>{total_pnl_pct:+.2f}%</code>) | <b>شناور:</b> <code>{unrealized_total:+.2f}$</code>",
            f"📅 <b>امروز:</b> <code>{daily_pnl:+.2f}$</code> | <b>هفته:</b> <code>{weekly_pnl:+.2f}$</code> | <b>Max DD:</b> <code>{max_dd:.2f}%</code>",
            f"🏦 <b>مارجین درگیر:</b> <code>${used_margin:,.1f} ({used_margin_pct:.1f}%)</code> | <b>ریسک:</b> <code>{bot_config.get('risk_mode','NORMAL')}</code>",
            f"🎯 <b>دروازه ۵۰ ترید کاغذی:</b> <code>{gate['completed_trades']}/{gate['target_trades']}</code> (برد: <code>{gate['win_rate_pct']:.1f}%</code>)\n{gate['bar']} (<code>{gate['remaining_trades']}</code> تا Live)",
            f"🕒 <b>سشن:</b> {session_str} | 📰 <b>اخبار:</b> {news_str}",
            "",
            f"📂 <b>پوزیشن‌های باز فعلی ({len(open_pos)}/5):</b>",
            *pos_lines,
            "",
            "🛰️ <b>خلاصه رادار ۵ دارایی:</b>",
            *radar_lines,
            "",
            f"🛡️ <b>رادار سایه:</b> فیلتر: <code>{sh_filtered}</code> | نجات: <code>{sh_saved}</code> (<code>{sh_acc_str}</code>)",
        ]
        if ml_line:
            lines.append(f"🧠 <b>ضرایب ML:</b> {ml_line}")

        lines.append(f"🧭 <b>سنتیمنت:</b> <code>{fng_val} ({fng_cls})</code> {fng_bar}")
        return "\n".join(lines)

    def build_hunt_caption(
        self,
        coin: str,
        side: str,
        regime_data: Dict[str, Any],
        confluence_data: Dict[str, Any],
        entry_plan: Dict[str, Any],
        exit_plan: Dict[str, Any],
        tm_data: Dict[str, Any],
        allocation: Dict[str, Any],
        sentiment_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        ۳. قالب ترکیبی «شکار جدید سازمانی» (دقیقاً منطبق با اسکرین‌شات محبوب شما + فرمت استاندارد اعشار و جعبه X-Ray).
        """
        c = str(coin).upper()
        s = str(side).upper()
        reg_name = regime_data.get("regime", "RANGING")
        strat_name = regime_data.get("strategy", "SMC_SETUP")

        score = float(confluence_data.get("final_score", 70.0))
        tier = confluence_data.get("tier", "STANDARD_SIZE")
        size_pct = int(round(float(confluence_data.get("size_multiplier", 0.75)) * 100))
        xray_fa = confluence_data.get("xray_summary_fa", "تایید ساختار ۱۵ دقیقه و نقدینگی")

        trig = entry_plan.get("trigger_type", "5M_MICRO_CHOCH")
        ep = format_price(exit_plan["entry_price"], c)
        sl = format_price(exit_plan["stop_loss"], c)
        tp1 = format_price(exit_plan["tp1_breakeven"], c)
        tp2 = format_price(exit_plan["tp2_final"], c)
        rr = float(exit_plan.get("rr_tp2", 2.0))

        wr = float(tm_data.get("win_rate_pct", 50.0))
        ev = float(tm_data.get("expected_value_r", 0.15))
        risk_u = float(allocation.get("risk_amount_usdt", 3.75))
        notional_u = float(allocation.get("notional_usdt", 500.0))

        fng_val = (sentiment_data or {}).get("value", 50)
        fng_cls = (sentiment_data or {}).get("classification", "Neutral")
        fng_bar = (sentiment_data or {}).get("bar", "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜")

        lines = [
            f"🎯 <b>شکار جدید سازمانی | {c} ({s})</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"🧭 <b>رژیم بازار:</b> <code>{reg_name} ({strat_name})</code>",
            f"🧠 <b>امتیاز هم‌گرایی فازی:</b> <code>{score:.1f}/100</code> (<code>{tier} - {size_pct}%</code>)",
            f"⚡ <b>ماشه ۵ دقیقه:</b> <code>{trig}</code>",
            "",
            f"📌 <b>ورود (LIMIT Maker):</b> <code>{ep}</code>",
            f"🛑 <b>حد ضرر (MARKET):</b> <code>{sl}</code>",
            f"🛡️ <b>تارگت ۱ (Risk-Free 50%):</b> <code>{tp1}</code>",
            f"🚀 <b>تارگت ۲ (نهایی):</b> <code>{tp2}</code> (<code>R:R = 1:{rr:.1f}</code>)",
            "",
            "🔬 <b>جعبه X-Ray و مونت‌کارلو:</b>",
            f" • <b>شبیه‌ساز ۱۰۰۰ مسیر:</b> برد <code>{wr:.1f}%</code> | امید ریاضی: <code>{ev:+.2f}R</code>",
            f" • <b>ریسک درگیر:</b> <code>${risk_u:.2f}</code> | <b>ارزش پوزیشن:</b> <code>${notional_u:.2f}</code>",
            f" • <b>دلایل:</b> {xray_fa}",
            "",
            f"🌡️ <b>سنتیمنت:</b> <code>{fng_val} ({fng_cls})</code>\n{fng_bar}",
        ]
        return "\n".join(lines)

    def build_asset_analysis_caption(
        self,
        coin: str,
        regime_data: Dict[str, Any],
        scan_data: Dict[str, Any],
        confluence_data: Dict[str, Any],
        orderbook_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        ۴. کپشن گزارش تحلیلی اختصاصی وقتی کاربر روی دکمه شیشه‌ای چارت یک ارز کلیک می‌کند.
        """
        c = str(coin).upper()
        curr_p = format_price(scan_data.get("current_price", 0.0), c)
        reg = regime_data.get("regime", "RANGING")
        htf = regime_data.get("htf_bias", "NEUTRAL")
        adx = float(regime_data.get("adx", regime_data.get("trend_strength", 20.0)))

        zone = scan_data.get("zone", "EQUILIBRIUM")
        rng_pct = float(scan_data.get("range_position_pct", 50.0))
        cand_side = scan_data.get("candidate_side", "NONE")
        sweep = scan_data.get("liquidity_sweep", "NONE")
        asian = scan_data.get("asian_range", {})
        ah = format_price(asian.get("asian_high", 0.0), c)
        al = format_price(asian.get("asian_low", 0.0), c)

        fvg = scan_data.get("active_fvg")
        if isinstance(fvg, dict) and "top" in fvg:
            fvg_str = f"{fvg.get('type')} ({format_price(fvg['bottom'], c)} - {format_price(fvg['top'], c)})"
        else:
            fvg_str = "ندارد (در انتظار تشکیل شکاف)"

        buy_p = float((orderbook_data or {}).get("buy_pressure_pct", 50.0))
        score = float(confluence_data.get("final_score", 0.0))
        xray = confluence_data.get("xray_summary_fa", "در حال رصد ساختار")

        return "\n".join([
            f"📊 <b>رادار و کالبدشکافی زنده | {c}/USDT (تایم‌فریم ۱۵m)</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"💵 <b>قیمت لحظه‌ای:</b> <code>{curr_p}</code>",
            f"🧭 <b>رژیم ۱ ساعته:</b> <code>{reg}</code> (ADX: <code>{adx:.1f}</code>) | <b>بایاس ۴H:</b> <code>{htf}</code>",
            f"📐 <b>موقعیت در رنج:</b> <code>{rng_pct:.1f}% ({zone})</code>",
            f"🟨 <b>ناحیه FVG فعال:</b> <code>{fvg_str}</code>",
            f"🌏 <b>رنج سشن آسیا:</b> سقف <code>{ah}</code> | کف <code>{al}</code>",
            f"💧 <b>شکار نقدینگی اخیر:</b> <code>{sweep}</code>",
            f"⚖️ <b>فشار خرید اردربوک:</b> <code>{buy_p:.1f}%</code>",
            "",
            f"🎯 <b>جهت کاندید فعلی:</b> <b>{cand_side}</b> | <b>امتیاز آمادگی:</b> <code>{score:.1f}/100</code>",
            f"🔬 <b>جزئیات X-Ray:</b> {xray}",
        ])

    # ==========================================================================
    # ۵. متدهای ارسال پیام و تصویر به تلگرام
    # ==========================================================================
    def send_message(
        self,
        text: str,
        bot_config: Optional[Dict[str, Any]] = None,
        with_keyboard: bool = True,
        custom_keyboard: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.is_configured:
            return False

        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if custom_keyboard is not None:
            payload["reply_markup"] = json.dumps(custom_keyboard)
        elif with_keyboard:
            payload["reply_markup"] = json.dumps(self.build_inline_keyboard(bot_config))

        try:
            resp = requests.post(self._api_url("sendMessage"), data=payload, timeout=12)
            if resp.status_code == 200:
                return True
            print(f"⚠️ [Telegram sendMessage] HTTP {resp.status_code}: {resp.text[:250]}")
            plain_payload = dict(payload)
            plain_payload.pop("parse_mode", None)
            plain_payload["text"] = re.sub(r"<[^>]+>", "", text)[:4000]
            resp2 = requests.post(self._api_url("sendMessage"), data=plain_payload, timeout=12)
            return resp2.status_code == 200
        except Exception as err:
            print(f"⚠️ [Telegram sendMessage Exception]: {err}")
            return False

    def send_photo(
        self,
        photo_path: str,
        caption: str,
        bot_config: Optional[Dict[str, Any]] = None,
        with_keyboard: bool = True,
        custom_keyboard: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.is_configured or not os.path.isfile(photo_path):
            return False

        plain_caption = re.sub(r"<[^>]+>", "", caption or "")
        utf16_len = len(plain_caption.encode("utf-16-le")) // 2

        if utf16_len <= 1015:
            data: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if custom_keyboard is not None:
                data["reply_markup"] = json.dumps(custom_keyboard)
            elif with_keyboard:
                data["reply_markup"] = json.dumps(self.build_inline_keyboard(bot_config))

            try:
                with open(photo_path, "rb") as img_f:
                    resp = requests.post(
                        self._api_url("sendPhoto"),
                        data=data,
                        files={"photo": img_f},
                        timeout=18,
                    )
                if resp.status_code == 200:
                    return True
                print(f"⚠️ [Telegram sendPhoto] HTTP {resp.status_code} (utf16_len={utf16_len}): {resp.text[:250]}")
            except Exception as err:
                print(f"⚠️ [Telegram sendPhoto Exception]: {err}")

        # Fallback: اگر طول کپشن بیش از محدودیت ۱۰۲۴ کاراکتری تلگرام باشد یا sendPhoto با کپشن بلند خطا بدهد،
        # ابتدا تصویر چارت با تیتر کوتاه ارسال می‌شود و بلافاصله متن کامل گزارش + کیبورد شیشه‌ای ارسال می‌گردد.
        header_line = (caption or "").splitlines()[0] if caption else "📊 Institutional Chart V2.5"
        short_data: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "caption": header_line[:200],
            "parse_mode": "HTML",
        }
        photo_ok = False
        try:
            with open(photo_path, "rb") as img_f:
                resp_short = requests.post(
                    self._api_url("sendPhoto"),
                    data=short_data,
                    files={"photo": img_f},
                    timeout=18,
                )
            photo_ok = resp_short.status_code == 200
        except Exception as err:
            print(f"⚠️ [Telegram sendPhoto Fallback Exception]: {err}")

        msg_ok = self.send_message(
            text=caption,
            bot_config=bot_config,
            with_keyboard=with_keyboard,
            custom_keyboard=custom_keyboard,
        )
        return photo_ok or msg_ok

    # ==========================================================================
    # ۶. پردازش دستورات و دکمه‌های شیشه‌ای نسل جدید (چارت ۵ ارز + ریسک‌فری + سیو سود)
    # ==========================================================================
    def process_incoming_commands(
        self,
        state_manager: Any,
        broker: Any,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        shadow_portfolio: Dict[str, Any],
        live_prices: Optional[Dict[str, float]] = None,
        on_demand_callback: Optional[Any] = None,
    ) -> List[str]:
        """
        دریافت و اجرای دستورات متنی و کالبک‌های شیشه‌ای جدید:
        - ANLZ_BTC, ANLZ_ETH, ANLZ_SOL, ANLZ_XRP, ANLZ_XAU: ارسال فوری چارت و رادار آن ارز
        - ACT_RISK_FREE: ریسک‌فری سریع تمام پوزیشن‌های در سود
        - ACT_SAVE_50: سیو سود پله‌ای ۵۰٪ تمام پوزیشن‌های در سود
        - دستورات متنی: /status, /nightly, /pause, /resume, /panic, /reset
        """
        if not self.is_configured:
            return []

        last_update_id = int(bot_config.get("last_update_id", 0))
        executed_cmds: List[str] = []

        try:
            resp = requests.get(
                self._api_url("getUpdates"),
                params={"offset": last_update_id + 1, "timeout": 2},
                timeout=6,
            )
            if resp.status_code != 200:
                return []
            updates = resp.json().get("result", [])
        except Exception:
            return []

        for upd in updates:
            upd_id = int(upd.get("update_id", 0))
            if upd_id > last_update_id:
                last_update_id = upd_id
                bot_config["last_update_id"] = last_update_id

            raw_cmd = ""
            cb_id = None

            if "message" in upd and "text" in upd["message"]:
                msg_chat_id = str(upd["message"].get("chat", {}).get("id", ""))
                if msg_chat_id and msg_chat_id != self.chat_id:
                    continue
                raw_cmd = str(upd["message"]["text"]).strip()

            elif "callback_query" in upd:
                cb = upd["callback_query"]
                cb_id = cb.get("id")
                cb_chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                if cb_chat_id and cb_chat_id != self.chat_id:
                    continue
                raw_cmd = str(cb.get("data", "")).strip()

            if not raw_cmd:
                continue

            if cb_id:
                try:
                    requests.post(
                        self._api_url("answerCallbackQuery"),
                        data={"callback_query_id": cb_id, "text": f"⏳ اجرای فرمان: {raw_cmd}"},
                        timeout=4,
                    )
                except Exception:
                    pass

            action = self._execute_single_command(
                raw_cmd=raw_cmd,
                state_manager=state_manager,
                broker=broker,
                portfolio=portfolio,
                bot_config=bot_config,
                shadow_portfolio=shadow_portfolio,
                live_prices=live_prices,
                on_demand_callback=on_demand_callback,
            )
            if action:
                executed_cmds.append(action)

        if updates:
            state_manager.save_bot_config(bot_config)
            state_manager.save_portfolio(portfolio)

        return executed_cmds

    def _execute_single_command(
        self,
        raw_cmd: str,
        state_manager: Any,
        broker: Any,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        shadow_portfolio: Dict[str, Any],
        live_prices: Optional[Dict[str, float]] = None,
        on_demand_callback: Optional[Any] = None,
    ) -> Optional[str]:
        cmd = raw_cmd.split("@")[0].strip()
        cmd_upper = cmd.upper()

        # ۱. دکمه‌های شیشه‌ای چارت و تحلیل زنده ۵ ارز (ANLZ_BTC, ANLZ_ETH, ...)
        if cmd_upper.startswith("ANLZ_"):
            target_coin = cmd_upper.replace("ANLZ_", "").strip()
            if target_coin in WATCHLIST:
                if callable(on_demand_callback):
                    on_demand_callback(target_coin)
                else:
                    self._send_cached_or_live_asset_analysis(target_coin, state_manager, bot_config)
                return f"ANALYZE_{target_coin}"

        # ۲. دکمه شیشه‌ای [ 🛡️ ریسک‌فری سریع ]
        if cmd_upper in ("ACT_RISK_FREE", "/RISKFREE"):
            res = broker.risk_free_all_in_profit(portfolio, live_prices=live_prices)
            cnt = res["updated_count"]
            coins_str = "، ".join(res["updated_coins"]) if res["updated_coins"] else "—"
            if cnt > 0:
                msg = (
                    f"🛡️ <b>عملیات ریسک‌فری سریع انجام شد!</b>\n"
                    f"حد ضرر <code>{cnt}</code> پوزیشن در سود (<b>{coins_str}</b>) به نقطه ورود منتقل گردید."
                )
            else:
                msg = "ℹ️ <b>ریسک‌فری سریع:</b> در حال حاضر پوزیشن جدیدی در سود (که قبلاً ریسک‌فری نشده باشد) وجود ندارد."
            self.send_message(msg, bot_config=bot_config)
            return "ACT_RISK_FREE"

        # ۳. دکمه شیشه‌ای [ 💰 سیو سود پله‌ای (۵۰٪) ]
        if cmd_upper in ("ACT_SAVE_50", "/SAVE50"):
            res = broker.partial_close_all_in_profit(portfolio, close_fraction=0.50, live_prices=live_prices)
            cnt = res["closed_count"]
            locked = res["total_locked_pnl_usdt"]
            coins_str = "، ".join(res["closed_coins"]) if res["closed_coins"] else "—"
            if cnt > 0:
                msg = (
                    f"💰 <b>سیو سود پله‌ای (۵۰٪) با موفقیت اجرا شد!</b>\n"
                    f"• پوزیشن‌های نقدشده: <b>{coins_str}</b>\n"
                    f"• سود خالص واریزی به بالانس: <code>+${locked:.2f} USDT</code>\n"
                    f"• وضعیت ۵۰٪ باقی‌مانده: 🛡️ <b>Risk-Free (استاپ در نقطه ورود)</b>"
                )
            else:
                msg = "ℹ️ <b>سیو سود پله‌ای:</b> در حال حاضر پوزیشنی در سود برای نقد کردن ۵۰٪ وجود ندارد."
            self.send_message(msg, bot_config=bot_config)
            return "ACT_SAVE_50"

        # ۴. گزارش جامع وضعیت (/status)
        if cmd.lower() in ("/status", "/start"):
            eq_chart = self.generate_equity_chart(portfolio)
            regimes = state_manager.load_market_regime()
            mem = state_manager.load_strategy_memory()
            caption = self.build_status_report(
                portfolio=portfolio,
                bot_config=bot_config,
                shadow_portfolio=shadow_portfolio,
                sentiment_data={"value": 50, "classification": "Live", "bar": "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜"},
                market_regimes=regimes,
                strategy_memory=mem,
            )
            self.send_photo(eq_chart, caption=caption, bot_config=bot_config)
            return "STATUS"

        # ۵. بیلان شبانه (/nightly)
        if cmd.lower() == "/nightly":
            eq_chart = self.generate_equity_chart(portfolio)
            caption = self.build_nightly_pulse_report(
                portfolio=portfolio,
                bot_config=bot_config,
                shadow_portfolio=shadow_portfolio,
                sentiment_data={"value": 50, "classification": "Live", "bar": "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜"},
            )
            self.send_photo(eq_chart, caption=caption, bot_config=bot_config)
            return "NIGHTLY"

        # ۶. دستورات کنترلی پایه
        if cmd.lower() == "/pause":
            bot_config["is_paused"] = True
            self.send_message("⏸ <b>ربات موقتاً متوقف شد.</b> پوزیشن‌های فعلی مدیریت می‌شوند اما ورود جدیدی انجام نمی‌شود.", bot_config=bot_config)
            return "PAUSE"

        if cmd.lower() in ("/resume", "/unpause"):
            bot_config["is_paused"] = False
            bot_config["panic_mode"] = False
            self.send_message("▶️ <b>ربات مجدداً فعال شد و در حال شکار ستاپ‌هاست.</b>", bot_config=bot_config)
            return "RESUME"

        if cmd.lower() in ("/close_all", "/panic"):
            closed = broker.close_all_positions(portfolio, live_prices=live_prices, reason=f"TELEGRAM_{cmd_upper.strip('/')}")
            if cmd.lower() == "/panic":
                bot_config["panic_mode"] = True
                bot_config["is_paused"] = True
            self.send_message(f"🚨 <b>خروج اضطراری انجام شد:</b> تعداد <code>{len(closed)}</code> پوزیشن بسته شد.", bot_config=bot_config)
            return cmd_upper.strip("/")

        if cmd.lower() == "/reset":
            fresh = state_manager.reset_portfolio()
            portfolio.clear()
            portfolio.update(fresh)
            bot_config["panic_mode"] = False
            bot_config["is_paused"] = False
            self.send_message("🔄 <b>پرتفوی کاغذی به $1,000.00 و دروازه ۰/۵۰ ریست شد.</b>", bot_config=bot_config)
            return "RESET"

        if cmd.lower().startswith("/risk"):
            parts = cmd.lower().split()
            mode = parts[1].upper() if len(parts) > 1 else "NORMAL"
            if mode in ("LOW", "NORMAL", "HIGH"):
                bot_config["risk_mode"] = mode
                self.send_message(f"⚙️ <b>مد ریسک روی <code>{mode}</code> تنظیم شد.</b>", bot_config=bot_config)
                return f"RISK_{mode}"

        return None

    def _send_cached_or_live_asset_analysis(
        self, coin: str, state_manager: Any, bot_config: Dict[str, Any]
    ) -> None:
        """ارسال فوری چارت و کالبدشکافی ارز انتخاب‌شده با دریافت زنده کندل‌های ۱۵ دقیقه."""
        try:
            from core.data_engine import DataEngine
            from skills.regime_detector import RegimeDetectorSkill
            from skills.scanner import MarketScannerSkill
            from skills.confluence_scorer import ConfluenceScorerSkill
            from skills.market_intel import MarketIntelSkill

            de = DataEngine()
            rd = RegimeDetectorSkill()
            sc = MarketScannerSkill()
            cs = ConfluenceScorerSkill()
            mi = MarketIntelSkill()

            df_4h = de.fetch_ohlcv(coin, "4h", limit=60)
            df_1h = de.fetch_ohlcv(coin, "1h", limit=80)
            df_15m = de.fetch_ohlcv(coin, "15m", limit=70)
            ob = de.fetch_order_book_imbalance(coin)
            kz = mi.check_killzone_session()

            reg_res = rd.detect_regime(df_1h, df_4h)
            scan_res = sc.scan_structure(df_15m, reg_res)
            side = scan_res.get("candidate_side", "LONG")
            if side == "NONE":
                side = "LONG" if reg_res.get("htf_bias") != "BEARISH" else "SHORT"
            mem = state_manager.load_strategy_memory()
            conf_res = cs.evaluate_confluence(coin, side, reg_res, scan_res, ob, kz, {}, mem)

            chart_path = self.generate_asset_analysis_chart(coin, df_15m, scan_res, reg_res)
            caption = self.build_asset_analysis_caption(coin, reg_res, scan_res, conf_res, ob)
            self.send_photo(
                chart_path,
                caption=caption,
                bot_config=bot_config,
                custom_keyboard=self.build_hunt_inline_keyboard(coin),
            )
        except Exception as err:
            self.send_message(f"⚠️ خطا در تولید چارت لحظه‌ای {coin}: <code>{err}</code>", bot_config=bot_config)
