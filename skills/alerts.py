"""
مهارت دوازدهم: اتاق فرمان دوطرفه تلگرام، گزارش پوزیشن‌های باز و رسم چارت (Telegram Alerts Skill)
Institutional Trading Bot V2 - Telegram Command Center & Dark-Theme Charting Engine
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

import matplotlib
matplotlib.use("Agg")  # بک‌اند بدون نیاز به نمایشگر برای اجرا در سرورهای ابری و GitHub Actions
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
import requests

from core.config import CHARTS_DIR, TELEGRAM_CONFIG


class TelegramAlertsSkill:
    """
    کلاس مدیریت ارتباط دوطرفه با تلگرام، رندرینگ چارت‌های ستاپ و منحنی سرمایه،
    محافظ طول کپشن HTML و نمایش درختی پوزیشن‌های باز.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        charts_dir: Optional[Path] = None,
    ) -> None:
        self.bot_token: str = (
            bot_token
            or os.getenv("TELEGRAM_BOT_TOKEN", "")
            or TELEGRAM_CONFIG.get("bot_token", "")
        ).strip()
        self.chat_id: str = (
            chat_id
            or os.getenv("TELEGRAM_CHAT_ID", "")
            or TELEGRAM_CONFIG.get("chat_id", "")
        ).strip()
        self.charts_dir: Path = charts_dir if charts_dir else CHARTS_DIR
        self.charts_dir.mkdir(parents=True, exist_ok=True)
        self.caption_safe_limit: int = 950

    @property
    def is_configured(self) -> bool:
        """بررسی تنظیم بودن توکن و چت‌آیدی تلگرام."""
        return bool(self.bot_token and self.chat_id)

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    # ==========================================================================
    # ۱. کیبورد شیشه‌ای داینامیک (Inline Keyboard)
    # ==========================================================================
    def _build_inline_keyboard(self, bot_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """ساخت کیبورد شیشه‌ای داینامیک بر اساس وضعیت فعلی ربات."""
        cfg = bot_config or {}
        is_paused = bool(cfg.get("is_paused", False)) or bool(cfg.get("panic_mode", False))

        toggle_btn = (
            {"text": "▶️ ادامه معاملات (/resume)", "callback_data": "/resume"}
            if is_paused
            else {"text": "⏸ توقف موقت (/pause)", "callback_data": "/pause"}
        )

        return {
            "inline_keyboard": [
                [
                    {"text": "📊 گزارش وضعیت (/status)", "callback_data": "/status"},
                    toggle_btn,
                ],
                [
                    {"text": "🛡️ ریسک کم", "callback_data": "/risk_low"},
                    {"text": "⚖️ ریسک عادی", "callback_data": "/risk_normal"},
                    {"text": "🔥 ریسک بالا", "callback_data": "/risk_high"},
                ],
                [
                    {"text": "⚠️ بستن همه (/close_all)", "callback_data": "/close_all"},
                    {"text": "🚨 قفل اضطراری (/panic)", "callback_data": "/panic"},
                ],
            ]
        }

    # ==========================================================================
    # ۲. ارسال پیام متنی و تصویر با محافظ طول کپشن ۹۵۰ کاراکتری
    # ==========================================================================
    def send_message(
        self,
        text: str,
        bot_config: Optional[Dict[str, Any]] = None,
        with_keyboard: bool = True,
    ) -> bool:
        """ارسال پیام متنی با فرمت HTML و کیبورد شیشه‌ای به تلگرام."""
        if not self.is_configured:
            print("ℹ️ [TelegramAlerts] Telegram credentials not configured. Skipping send_message.")
            return False

        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if with_keyboard:
            payload["reply_markup"] = json.dumps(self._build_inline_keyboard(bot_config))

        try:
            resp = requests.post(self._api_url("sendMessage"), data=payload, timeout=12)
            if resp.status_code == 200:
                return True
            print(f"⚠️ [TelegramAlerts] sendMessage HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"⚠️ [TelegramAlerts] sendMessage error: {e}")
        return False

    def send_photo(
        self,
        photo_path: str | Path,
        caption: str = "",
        bot_config: Optional[Dict[str, Any]] = None,
        with_keyboard: bool = True,
    ) -> bool:
        """
        ارسال تصویر چارت به تلگرام به همراه محافظ طول کپشن (۹۵۰ کاراکتر):
        اگر طول کپشن بیش از ۹۵۰ کاراکتر باشد، ابتدا عکس با یک کپشن کوتاه ارسال شده
        و بلافاصله متن کامل گزارش با send_message ارسال می‌گردد تا تگ‌های HTML نشکنند.
        """
        path_obj = Path(photo_path)
        if not path_obj.is_file():
            return self.send_message(caption, bot_config=bot_config, with_keyboard=with_keyboard)

        if not self.is_configured:
            print(f"ℹ️ [TelegramAlerts] Photo generated at {path_obj}, skipping Telegram upload.")
            return False

        # بررسی محافظ طول کپشن (۹۵۰ کاراکتر)
        if len(caption) > self.caption_safe_limit:
            short_caption = "📊 <b>چارت گرافیکی ستاپ / گزارش عملکرد پرتفوی V2</b>\n⬇️ <i>جزئیات کامل در پیام بعدی...</i>"
            photo_sent = self._upload_photo_raw(
                path_obj, short_caption, bot_config=bot_config, with_keyboard=False
            )
            msg_sent = self.send_message(
                caption, bot_config=bot_config, with_keyboard=with_keyboard
            )
            return photo_sent and msg_sent

        return self._upload_photo_raw(
            path_obj, caption, bot_config=bot_config, with_keyboard=with_keyboard
        )

    def _upload_photo_raw(
        self,
        path_obj: Path,
        caption: str,
        bot_config: Optional[Dict[str, Any]] = None,
        with_keyboard: bool = True,
    ) -> bool:
        data: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if with_keyboard:
            data["reply_markup"] = json.dumps(self._build_inline_keyboard(bot_config))

        try:
            with open(path_obj, "rb") as img_file:
                files = {"photo": img_file}
                resp = requests.post(self._api_url("sendPhoto"), data=data, files=files, timeout=20)
                if resp.status_code == 200:
                    return True
                print(f"⚠️ [TelegramAlerts] sendPhoto HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"⚠️ [TelegramAlerts] sendPhoto error: {e}")
        return False

    # ==========================================================================
    # ۳. موتور گرافیکی رسم چارت ستاپ ۱۵ دقیقه و منحنی سرمایه (Dark Theme #0d1117)
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
        score: float = 0.0,
        regime: str = "RANGING",
    ) -> Path:
        """
        رسم ۵۵ کندل آخر ۱۵ دقیقه با تم تاریک (#0d1117)، ناحیه طلایی‌رنگ FVG Zone،
        و خطوط افقی LIMIT ENTRY، STOP LOSS، TP1 و TP2 در فایل state/charts/setup_<coin>.png.
        """
        clean_coin = str(coin).strip().upper().replace("/", "_")
        out_path = self.charts_dir / f"setup_{clean_coin.lower()}.png"

        if df_15m is None or len(df_15m) < 5:
            return out_path

        df_plot = df_15m.tail(55).reset_index(drop=True)
        n = len(df_plot)

        fig, ax = plt.subplots(figsize=(11, 6), dpi=130)
        fig.patch.set_facecolor("#0d1117")
        ax.set_facecolor("#0d1117")

        opens = df_plot["open"].astype(float).values
        highs = df_plot["high"].astype(float).values
        lows = df_plot["low"].astype(float).values
        closes = df_plot["close"].astype(float).values

        # ۱. رسم کندل‌استیک‌ها (سبز #00e676 و قرمز #ff5252)
        candle_width = 0.62
        for i in range(n):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            color = "#00e676" if c >= o else "#ff5252"
            ax.plot([i, i], [l, h], color=color, linewidth=1.1, zorder=2)
            body_bottom = min(o, c)
            body_height = max(abs(c - o), (h - l) * 0.02, 1e-6)
            rect = Rectangle(
                (i - candle_width / 2.0, body_bottom),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.8,
                zorder=3,
            )
            ax.add_patch(rect)

        # ۲. رسم ناحیه طلایی‌رنگ FVG Zone (در صورت وجود)
        if isinstance(active_fvg, dict) and active_fvg.get("top") and active_fvg.get("bottom"):
            fvg_top = float(active_fvg["top"])
            fvg_bot = float(active_fvg["bottom"])
            ax.axhspan(
                fvg_bot,
                fvg_top,
                color="#ffd700",
                alpha=0.16,
                label=f"15m FVG Zone ({fvg_bot:.4f} - {fvg_top:.4f})",
                zorder=1,
            )

        # ۳. رسم خطوط افقی LIMIT ENTRY, STOP LOSS, TP1, TP2
        ax.axhline(
            entry_price,
            color="#29b6f6",
            linestyle="--",
            linewidth=1.5,
            label=f"LIMIT ENTRY: {entry_price:.4f}",
            zorder=4,
        )
        ax.axhline(
            stop_loss,
            color="#ff1744",
            linestyle="-",
            linewidth=1.5,
            label=f"STOP LOSS: {stop_loss:.4f}",
            zorder=4,
        )
        ax.axhline(
            tp1_price,
            color="#ffca28",
            linestyle=":",
            linewidth=1.5,
            label=f"TP1 (Risk-Free 50%): {tp1_price:.4f}",
            zorder=4,
        )
        ax.axhline(
            tp2_price,
            color="#00e676",
            linestyle="-.",
            linewidth=1.6,
            label=f"TP2 (Final Target): {tp2_price:.4f}",
            zorder=4,
        )

        # تنظیمات ظاهری و گرید
        title_str = (
            f"Institutional Bot V2 | {clean_coin} ({side}) — 15m Structure | "
            f"Score: {score:.1f}/100 | Regime: {regime}"
        )
        ax.set_title(title_str, color="#e6edf3", fontsize=11, fontweight="bold", pad=12)
        ax.set_xlabel("Recent 15m Candles (Last 55 Bars)", color="#8b949e", fontsize=9)
        ax.set_ylabel("Price (USDT)", color="#8b949e", fontsize=9)

        ax.grid(True, linestyle="--", linewidth=0.5, color="#21262d", alpha=0.8)
        ax.tick_params(colors="#8b949e", labelsize=8.5)
        for spine in ax.spines.values():
            spine.set_color("#30363d")

        legend = ax.legend(
            loc="upper left",
            facecolor="#161b22",
            edgecolor="#30363d",
            fontsize=8.5,
            labelcolor="#e6edf3",
        )
        legend.set_zorder(5)

        plt.tight_layout()
        fig.savefig(out_path, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return out_path

    def generate_equity_chart(self, portfolio: Dict[str, Any]) -> Path:
        """
        رسم نمودار منحنی رشد سرمایه در فایل state/charts/equity_curve.png با تم تاریک (#0d1117).
        """
        out_path = self.charts_dir / "equity_curve.png"
        curve = portfolio.get("equity_curve", [])
        initial_bal = float(portfolio.get("initial_balance_usdt", 1000.0))
        current_bal = float(portfolio.get("balance_usdt", initial_bal))

        equities = [float(item.get("equity", initial_bal)) for item in curve if isinstance(item, dict)]
        if not equities:
            equities = [initial_bal, current_bal]
        elif len(equities) == 1:
            equities.append(current_bal)

        x_vals = np.arange(len(equities))
        y_vals = np.array(equities, dtype=float)

        fig, ax = plt.subplots(figsize=(10, 5), dpi=130)
        fig.patch.set_facecolor("#0d1117")
        ax.set_facecolor("#0d1117")

        line_color = "#00e676" if y_vals[-1] >= initial_bal else "#ff5252"
        ax.plot(x_vals, y_vals, color=line_color, linewidth=2.2, marker="o", markersize=3.5, label="Portfolio Equity (USDT)")
        ax.axhline(initial_bal, color="#8b949e", linestyle="--", linewidth=1.1, label=f"Initial Baseline (${initial_bal:,.2f})")
        ax.fill_between(x_vals, initial_bal, y_vals, color=line_color, alpha=0.14)

        pnl_total = y_vals[-1] - initial_bal
        pnl_pct = ((y_vals[-1] / initial_bal) - 1.0) * 100.0 if initial_bal > 0 else 0.0

        ax.set_title(
            f"Institutional Portfolio V2 — Equity Curve | Balance: ${y_vals[-1]:,.2f} ({pnl_pct:+.2f}%)",
            color="#e6edf3",
            fontsize=11,
            fontweight="bold",
            pad=12,
        )
        ax.set_xlabel("Trade Sequence / Checkpoints", color="#8b949e", fontsize=9)
        ax.set_ylabel("Equity (USDT)", color="#8b949e", fontsize=9)

        ax.grid(True, linestyle="--", linewidth=0.5, color="#21262d", alpha=0.8)
        ax.tick_params(colors="#8b949e", labelsize=8.5)
        for spine in ax.spines.values():
            spine.set_color("#30363d")

        ax.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d", fontsize=8.5, labelcolor="#e6edf3")
        plt.tight_layout()
        fig.savefig(out_path, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return out_path

    # ==========================================================================
    # ۴. نمایش درختی و کامل پوزیشن‌های باز و گزارش وضعیت (Status & Nightly Report)
    # ==========================================================================
    def _format_open_positions_section(self, open_positions: List[Dict[str, Any]]) -> str:
        """
        نمایش جزئیات کامل پوزیشن‌های باز به صورت درختی شامل:
        نام ارز، جهت (🟢 LONG / 🔴 SHORT)، امتیاز، قیمت ورود، استاپ فعلی، تارگت ۱ و ۲،
        و وضعیت ریسک‌فری شدن (🛡️ Risk-Free به همراه سود سیوشده یا ⚡ فعال به همراه ریسک و حجم).
        """
        if not open_positions:
            return "📂 <b>پوزیشن‌های باز فعلی:</b>\n└ <i>هیچ پوزیشن بازی وجود ندارد (0/5 اسلات اشغال)</i>"

        lines: List[str] = [f"📂 <b>لیست پوزیشن‌های باز ({len(open_positions)}/5 اسلات):</b>"]

        for idx, pos in enumerate(open_positions, start=1):
            coin = str(pos.get("coin", "UNKNOWN"))
            side = str(pos.get("side", "LONG")).upper()
            side_badge = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
            score = float(pos.get("score", 0.0))
            entry = float(pos.get("entry_price", 0.0))
            curr_sl = float(pos.get("current_stop_loss", 0.0))
            tp1 = float(pos.get("tp1_price", 0.0))
            tp2 = float(pos.get("tp2_price", 0.0))
            tp1_hit = bool(pos.get("tp1_hit", False))
            partial_pnl = float(pos.get("realized_partial_pnl", 0.0))
            risk_usdt = float(pos.get("risk_amount_usdt", 0.0))
            rem_qty = float(pos.get("remaining_quantity", 0.0))

            if tp1_hit:
                state_str = f"🛡️ <b>Risk-Free (TP1 Hit)</b> | سود سیوشده: <code>{partial_pnl:+.2f}$</code>"
            else:
                state_str = f"⚡ <b>فعال (Active Risk)</b> | ریسک: <code>{risk_usdt:.2f}$</code> | حجم: <code>{rem_qty:.4f}</code>"

            lines.append(
                f"\n<b>{idx}. {coin} ({side_badge})</b> — امتیاز: <code>{score:.1f}</code>\n"
                f"├ ورود: <code>{entry:.4f}</code> | استاپ فعلی: <code>{curr_sl:.4f}</code>\n"
                f"├ تارگت ۱: <code>{tp1:.4f}</code> | تارگت ۲: <code>{tp2:.4f}</code>\n"
                f"└ وضعیت: {state_str}"
            )

        return "\n".join(lines)

    def build_status_report(
        self,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        shadow_portfolio: Optional[Dict[str, Any]] = None,
        sentiment_data: Optional[Dict[str, Any]] = None,
        title: str = "🏛️ گزارش جامع اتاق فرمان (Institutional Bot V2)",
    ) -> str:
        """
        ساخت متن کامل گزارش وضعیت (برای دستور /status و گزارش شبانه) شامل:
        موجودی، سود روزانه، وضعیت مدارشکن، آمار وین‌ریت، رادار سایه و جزئیات درختی پوزیشن‌های باز.
        """
        bal = float(portfolio.get("balance_usdt", 1000.0))
        init_bal = float(portfolio.get("initial_balance_usdt", 1000.0))
        daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        total_pnl_pct = ((bal / init_bal) - 1.0) * 100.0 if init_bal > 0 else 0.0

        cb_active = bool(portfolio.get("daily_circuit_breaker", False))
        is_paused = bool(bot_config.get("is_paused", False))
        panic_mode = bool(bot_config.get("panic_mode", False))
        risk_mode = str(bot_config.get("risk_mode", "NORMAL")).upper()

        if panic_mode:
            bot_state_str = "🚨 PANIC LOCKED"
        elif is_paused:
            bot_state_str = "⏸ PAUSED"
        elif cb_active:
            bot_state_str = "🛑 CIRCUIT BREAKER TRIPPED"
        else:
            bot_state_str = "🟢 ACTIVE & HUNTING"

        stats = portfolio.get("stats", {})
        total_trades = int(stats.get("total_trades", 0))
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        win_rate = float(stats.get("win_rate_pct", 0.0))
        max_dd = float(stats.get("max_drawdown_pct", 0.0))

        open_positions = portfolio.get("open_positions", [])
        rf_count = sum(1 for p in open_positions if bool(p.get("tp1_hit", False)))
        active_risk_count = len(open_positions) - rf_count

        sh_stats = (shadow_portfolio or {}).get("stats", {})
        saved_losses = int(sh_stats.get("saved_from_loss", 0))
        shield_acc = float(sh_stats.get("shield_accuracy", 100.0))

        sent = sentiment_data or {}
        fng_val = sent.get("value", 50)
        fng_cls = sent.get("classification", "Neutral")
        fng_bar = sent.get("bar", "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜")

        open_pos_section = self._format_open_positions_section(open_positions)

        report = (
            f"<b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <b>وضعیت سیستم:</b> <code>{bot_state_str}</code>\n"
            f"⚙️ <b>مد ریسک:</b> <code>{risk_mode}</code> | <b>اسلات‌ها:</b> <code>{len(open_positions)}/5</code> "
            f"(⚡فعال: <code>{active_risk_count}</code> | 🛡️ریسک‌فری: <code>{rf_count}</code>)\n\n"
            f"💰 <b>موجودی فعلی:</b> <code>${bal:,.2f}</code> (<code>{total_pnl_pct:+.2f}%</code>)\n"
            f"📅 <b>سود/زیان امروز:</b> <code>${daily_pnl:+.2f}</code> | <b>Max DD:</b> <code>{max_dd:.2f}%</code>\n"
            f"📈 <b>آمار کل:</b> <code>{total_trades}</code> معامله (✅ <code>{wins}</code> برد | ❌ <code>{losses}</code> باخت | WinRate: <code>{win_rate:.1f}%</code>)\n"
            f"🛡️ <b>سپر رادار سایه:</b> <code>{saved_losses}</code> ضرر مهارشده (دقت سپر: <code>{shield_acc:.1f}%</code>)\n\n"
            f"🧭 <b>سنتیمنت بازار (F&G):</b> <code>{fng_val} ({fng_cls})</code>\n"
            f"{fng_bar}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{open_pos_section}"
        )
        return report

    def build_trade_opened_caption(
        self,
        pos: Dict[str, Any],
        timemachine_data: Dict[str, Any],
        spread_data: Dict[str, Any],
    ) -> str:
        """ساخت کپشن گزارش باز شدن پوزیشن جدید به همراه آمار مونت‌کارلو و اسپرد."""
        coin = pos.get("coin", "")
        side = pos.get("side", "LONG")
        badge = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
        score = float(pos.get("score", 0.0))
        tier = pos.get("tier", "")
        regime = pos.get("regime", "")
        trigger = pos.get("trigger_type", "")
        entry = float(pos.get("entry_price", 0.0))
        sl = float(pos.get("initial_stop_loss", 0.0))
        tp1 = float(pos.get("tp1_price", 0.0))
        tp2 = float(pos.get("tp2_price", 0.0))
        risk_usdt = float(pos.get("risk_amount_usdt", 0.0))
        risk_pct = float(pos.get("effective_risk_pct", 0.5))
        margin = float(pos.get("margin_used_usdt", 0.0))

        tm_wr = float(timemachine_data.get("win_rate_pct", 0.0))
        tm_ev = float(timemachine_data.get("expected_value_r", 0.0))
        sp_ratio = float(spread_data.get("spread_ratio_pct", 0.0))

        return (
            f"🎯 <b>شلیک ستاپ سازمانی جدید | {coin} ({badge})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>امتیاز هم‌گرایی:</b> <code>{score:.1f}/100</code> ({tier})\n"
            f"🧭 <b>رژیم بازار:</b> <code>{regime}</code> | <b>ماشه:</b> <code>{trigger}</code>\n"
            f"⏳ <b>ماشین زمان (1000 مسیر):</b> WinRate <code>{tm_wr:.1f}%</code> | EV: <code>{tm_ev:+.2f}R</code>\n"
            f"🛡️ <b>گارد اسپرد:</b> <code>{sp_ratio:.2f}%</code> از تارگت (تایید شده)\n\n"
            f"📍 <b>ورود (Limit Maker):</b> <code>{entry:.4f}</code>\n"
            f"🛑 <b>حد ضرر ساختاری (SL):</b> <code>{sl:.4f}</code>\n"
            f"🥇 <b>تارگت ۱ (50% + Risk-Free):</b> <code>{tp1:.4f}</code>\n"
            f"🏆 <b>تارگت ۲ (نقدینگی نهایی):</b> <code>{tp2:.4f}</code>\n"
            f"💼 <b>ریسک معامله:</b> <code>${risk_usdt:.2f} ({risk_pct:.2f}%)</code> | <b>مارجین:</b> <code>${margin:.2f}</code>"
        )

    # ==========================================================================
    # ۵. پردازشگر دستورات از راه دور تلگرام (Remote Command Polling)
    # ==========================================================================
    def process_incoming_commands(
        self,
        state_manager: Any,
        broker: Any,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        shadow_portfolio: Optional[Dict[str, Any]] = None,
        sentiment_data: Optional[Dict[str, Any]] = None,
        live_prices: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        """
        دریافت آپدیت‌های جدید تلگرام بر اساس last_update_id و اجرای دستورات:
        /status, /panic, /close_all, /pause, /resume, /risk_low, /risk_normal, /risk_high, /reset
        """
        if not self.is_configured:
            return []

        last_update_id = int(bot_config.get("last_update_id", 0))
        executed_commands: List[str] = []

        try:
            params = {"offset": last_update_id + 1, "timeout": 4}
            resp = requests.get(self._api_url("getUpdates"), params=params, timeout=8)
            if resp.status_code != 200:
                return []

            updates = resp.json().get("result", [])
            for upd in updates:
                upd_id = int(upd.get("update_id", 0))
                if upd_id > last_update_id:
                    last_update_id = upd_id
                    bot_config["last_update_id"] = last_update_id

                # استخراج دستور از پیام متنی یا کلیک روی دکمه شیشه‌ای (callback_query)
                cmd_text = ""
                chat_from = ""

                if "message" in upd and isinstance(upd["message"], dict):
                    msg = upd["message"]
                    cmd_text = str(msg.get("text", "")).strip()
                    chat_from = str(msg.get("chat", {}).get("id", ""))
                elif "callback_query" in upd and isinstance(upd["callback_query"], dict):
                    cb = upd["callback_query"]
                    cmd_text = str(cb.get("data", "")).strip()
                    chat_from = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                    # پاسخ به callback_query برای بسته شدن لودینگ دکمه در تلگرام
                    cb_id = cb.get("id")
                    if cb_id:
                        try:
                            requests.post(
                                self._api_url("answerCallbackQuery"),
                                data={"callback_query_id": cb_id},
                                timeout=4,
                            )
                        except Exception:
                            pass

                if not cmd_text or (self.chat_id and chat_from and chat_from != self.chat_id):
                    continue

                cmd = cmd_text.split()[0].lower()
                if "@" in cmd:
                    cmd = cmd.split("@")[0]

                if cmd == "/status":
                    report = self.build_status_report(
                        portfolio, bot_config, shadow_portfolio, sentiment_data
                    )
                    eq_chart = self.generate_equity_chart(portfolio)
                    self.send_photo(eq_chart, caption=report, bot_config=bot_config)
                    executed_commands.append("/status")

                elif cmd == "/panic":
                    closed = broker.close_all_panic(
                        portfolio, bot_config, live_prices=live_prices, lock_panic=True
                    )
                    state_manager.save_portfolio(portfolio)
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        f"🚨 <b>قفل اضطراری (/panic) فعال شد!</b>\n"
                        f"تمام پوزیشن‌های باز (<code>{len(closed)}</code> مورد) بسته شدند و ربات قفل گردید.",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/panic")

                elif cmd == "/close_all":
                    closed = broker.close_all_panic(
                        portfolio, bot_config, live_prices=live_prices, lock_panic=False
                    )
                    state_manager.save_portfolio(portfolio)
                    self.send_message(
                        f"⚠️ <b>دستور بستن همه پوزیشن‌ها (/close_all) اجرا شد.</b>\n"
                        f"تعداد <code>{len(closed)}</code> پوزیشن به صورت دستی بسته شد.",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/close_all")

                elif cmd == "/pause":
                    bot_config["is_paused"] = True
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        "⏸ <b>ربات به حالت توقف موقت (Paused) رفت.</b>\nپوزیشن‌های قبلی مدیریت می‌شوند اما معامله جدیدی باز نخواهد شد.",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/pause")

                elif cmd == "/resume":
                    bot_config["is_paused"] = False
                    bot_config["panic_mode"] = False
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        "▶️ <b>ربات مجدداً فعال شد (Active & Hunting)!</b>",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/resume")

                elif cmd == "/risk_low":
                    bot_config["risk_mode"] = "CONSERVATIVE"
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        "🛡️ <b>مد ریسک روی حالت محافظه‌کارانه (CONSERVATIVE - 0.25%) قرار گرفت.</b>",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/risk_low")

                elif cmd == "/risk_normal":
                    bot_config["risk_mode"] = "NORMAL"
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        "⚖️ <b>مد ریسک روی حالت استاندارد (NORMAL - 0.50%) قرار گرفت.</b>",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/risk_normal")

                elif cmd == "/risk_high":
                    bot_config["risk_mode"] = "AGGRESSIVE"
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        "🔥 <b>مد ریسک روی حالت تهاجمی (AGGRESSIVE - 0.80%) قرار گرفت.</b>",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/risk_high")

                elif cmd == "/reset":
                    fresh_pf = state_manager.reset_portfolio()
                    portfolio.clear()
                    portfolio.update(fresh_pf)
                    bot_config["is_paused"] = False
                    bot_config["panic_mode"] = False
                    state_manager.save_bot_config(bot_config)
                    self.send_message(
                        "🔄 <b>پرتفوی با موفقیت به حالت اولیه ($1,000.00) ریست شد.</b>",
                        bot_config=bot_config,
                    )
                    executed_commands.append("/reset")

            if updates:
                state_manager.save_bot_config(bot_config)

        except Exception as e:
            print(f"⚠️ [TelegramAlerts] Error polling Telegram updates: {e}")

        return executed_commands