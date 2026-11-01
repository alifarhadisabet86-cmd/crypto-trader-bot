"""
مهارت دهم: گارد اسپرد ۵٪، اجرای سفارش، مدیریت TP1/TP2/SL و رادار سایه (Broker Execution Skill)
Institutional Trading Bot V2 - Order Execution, Lifecycle & Shadow Recorder Engine
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import pandas as pd

from core.config import EXECUTION_RULES, RISK_RULES


class BrokerExecutionSkill:
    """
    کلاس اجرای سفارشات، بررسی گارد اسپرد ۵٪، مدیریت پوزیشن‌های باز (صرفاً بر اساس TP1/TP2/SL
    و بدون خروج زمانی)، بستن اضطراری (/panic) و ثبت ستاپ‌های فیلترشده در رادار سایه.
    """

    def __init__(self) -> None:
        self.maker_fee: float = float(EXECUTION_RULES.get("maker_fee", 0.0002))
        self.taker_fee: float = float(EXECUTION_RULES.get("taker_fee", 0.0006))
        self.max_spread_ratio: float = float(
            EXECUTION_RULES.get("max_spread_to_target_ratio", 0.05)
        )
        self.max_daily_dd_pct: float = float(RISK_RULES.get("max_daily_drawdown_pct", 2.0))

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ==========================================================================
    # ۱. گارد اسپرد ۵٪ (Spread Guard)
    # ==========================================================================
    def check_spread_guard(
        self,
        spread_data: Dict[str, Any],
        entry_price: float,
        tp2_price: float,
    ) -> Dict[str, Any]:
        """
        بررسی نسبت اسپرد لحظه‌ای به فاصله تارگت نهایی:
        spread_abs / abs(tp2 - entry) <= 0.05 (5%)
        """
        spread_abs = float(spread_data.get("spread_abs", 0.0))
        target_dist = abs(float(tp2_price) - float(entry_price))

        if target_dist <= 1e-12:
            return {
                "passed": False,
                "spread_ratio": 1.0,
                "spread_ratio_pct": 100.0,
                "max_allowed_pct": self.max_spread_ratio * 100.0,
                "details": "Invalid target distance (zero).",
            }

        spread_ratio = spread_abs / target_dist
        passed = spread_ratio <= self.max_spread_ratio

        return {
            "passed": bool(passed),
            "spread_abs": round(spread_abs, 8),
            "target_distance": round(target_dist, 6),
            "spread_ratio": round(spread_ratio, 4),
            "spread_ratio_pct": round(spread_ratio * 100.0, 2),
            "max_allowed_pct": round(self.max_spread_ratio * 100.0, 2),
            "details": (
                f"Spread Ratio: {spread_ratio * 100.0:.2f}% "
                f"({'<= ' if passed else '> '}{self.max_spread_ratio * 100.0:.1f}% limit)"
            ),
        }

    # ==========================================================================
    # ۲. باز کردن پوزیشن جدید (Open Position)
    # ==========================================================================
    def open_position(
        self,
        portfolio: Dict[str, Any],
        coin: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_plan: Dict[str, Any],
        risk_info: Dict[str, Any],
        confluence_info: Dict[str, Any],
        regime_info: Dict[str, Any],
        trigger_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        ساخت رکورد پوزیشن جدید با شناسه یکتا، کسر کارمزد ورود Maker و افزودن به open_positions.
        """
        clean_side = str(side).strip().upper()
        entry = float(entry_price)
        qty = float(risk_info.get("quantity", 0.0))
        notional = round(entry * qty, 4)

        # کارمزد ورود با سفارش Limit (Maker: 0.02%)
        entry_fee = round(notional * self.maker_fee, 4)

        pos_id = f"POS-{coin}-{uuid.uuid4().hex[:6].upper()}"
        now_iso = self._utc_now_iso()

        position_record: Dict[str, Any] = {
            "position_id": pos_id,
            "coin": coin,
            "symbol": symbol,
            "side": clean_side,
            "regime": str(regime_info.get("regime", "RANGING")),
            "strategy": str(regime_info.get("strategy", "TREND_PULLBACK")),
            "trigger_type": str((trigger_info or {}).get("trigger_type", "LIMIT_SNIPER")),
            "score": float(confluence_info.get("final_score", 0.0)),
            "tier": str(confluence_info.get("tier", "STANDARD_SIZE (75%)")),
            "slot_type": str(risk_info.get("slot_type", "STANDARD_SLOT")),
            "entry_price": round(entry, 6),
            "initial_stop_loss": float(exit_plan.get("stop_loss", 0.0)),
            "current_stop_loss": float(exit_plan.get("stop_loss", 0.0)),
            "tp1_price": float(exit_plan.get("tp1_breakeven", 0.0)),
            "tp2_price": float(exit_plan.get("tp2_final", 0.0)),
            "initial_quantity": round(qty, 6),
            "remaining_quantity": round(qty, 6),
            "notional_usdt": notional,
            "margin_used_usdt": float(risk_info.get("margin_used_usdt", 0.0)),
            "leverage": int(risk_info.get("leverage", 10)),
            "risk_amount_usdt": float(risk_info.get("risk_amount_usdt", 0.0)),
            "effective_risk_pct": float(risk_info.get("effective_risk_pct", 0.5)),
            "tp1_hit": False,
            "risk_free": False,
            "realized_partial_pnl": round(-entry_fee, 4),
            "entry_fee_usdt": entry_fee,
            "opened_at": now_iso,
            "last_checked": now_iso,
        }

        # اعمال کارمزد ورود روی موجودی و سود روزانه
        portfolio["balance_usdt"] = round(float(portfolio.get("balance_usdt", 1000.0)) - entry_fee, 4)
        portfolio["daily_pnl_usdt"] = round(float(portfolio.get("daily_pnl_usdt", 0.0)) - entry_fee, 4)

        if "open_positions" not in portfolio or not isinstance(portfolio["open_positions"], list):
            portfolio["open_positions"] = []
        portfolio["open_positions"].append(position_record)

        return position_record

    # ==========================================================================
    # ۳. مدیریت پوزیشن‌های باز (صرفاً بر اساس برخورد به TP1 / TP2 / SL)
    # ==========================================================================
    def manage_open_positions(
        self,
        portfolio: Dict[str, Any],
        market_data_5m: Dict[str, pd.DataFrame],
    ) -> List[Dict[str, Any]]:
        """
        بررسی پوزیشن‌های باز با کندل‌های ۵ دقیقه:
        - پوزیشن‌ها فقط با برخورد به SL یا TP2 بسته می‌شوند (بدون هیچ گونه Time-Stop).
        - در صورت برخورد به TP1: بستن ۵۰٪ حجم با کارمزد Maker، ثبت در realized_partial_pnl،
          تغییر tp1_hit = True و انتقال current_stop_loss به entry_price (Risk-Free).
        """
        open_positions = portfolio.get("open_positions", [])
        if not open_positions:
            return []

        events: List[Dict[str, Any]] = []
        still_open: List[Dict[str, Any]] = []
        now_iso = self._utc_now_iso()

        for pos in open_positions:
            coin = str(pos.get("coin", ""))
            df_5m = market_data_5m.get(coin)
            if df_5m is None or (isinstance(df_5m, pd.DataFrame) and df_5m.empty):
                df_5m = market_data_5m.get(pos.get("symbol", ""))

            if df_5m is None or len(df_5m) == 0:
                still_open.append(pos)
                continue

            # بررسی آخرین کندل‌های ۵ دقیقه (حداکثر ۳ کندل اخیر در چرخه ۱۵ دقیقه‌ای)
            recent_bars = df_5m.tail(3)
            bar_high = float(recent_bars["high"].astype(float).max())
            bar_low = float(recent_bars["low"].astype(float).min())

            side = str(pos.get("side", "LONG")).upper()
            entry = float(pos.get("entry_price", 0.0))
            curr_sl = float(pos.get("current_stop_loss", 0.0))
            tp1 = float(pos.get("tp1_price", 0.0))
            tp2 = float(pos.get("tp2_price", 0.0))
            init_qty = float(pos.get("initial_quantity", 0.0))
            rem_qty = float(pos.get("remaining_quantity", init_qty))
            tp1_hit = bool(pos.get("tp1_hit", False))

            pos["last_checked"] = now_iso
            closed_completely = False

            # الف) بررسی برخورد به حد ضرر فعلی (SL یا نقطه سر‌به‌سر پس از TP1)
            sl_triggered = (side == "LONG" and bar_low <= curr_sl) or (
                side == "SHORT" and bar_high >= curr_sl
            )

            if sl_triggered:
                exit_price = curr_sl
                gross_pnl = (
                    (exit_price - entry) * rem_qty
                    if side == "LONG"
                    else (entry - exit_price) * rem_qty
                )
                exit_fee = (exit_price * rem_qty) * self.taker_fee
                net_leg_pnl = round(gross_pnl - exit_fee, 4)

                # بروزرسانی موجودی و آمار نهایی معامله
                portfolio["balance_usdt"] = round(float(portfolio["balance_usdt"]) + net_leg_pnl, 4)
                portfolio["daily_pnl_usdt"] = round(float(portfolio["daily_pnl_usdt"]) + net_leg_pnl, 4)

                total_trade_pnl = round(float(pos.get("realized_partial_pnl", 0.0)) + net_leg_pnl, 4)
                close_reason = "BREAKEVEN_STOP_AFTER_TP1" if tp1_hit else "STOP_LOSS_HIT"

                closed_record = self._finalize_closed_trade(
                    portfolio=portfolio,
                    pos=pos,
                    exit_price=exit_price,
                    total_pnl_usdt=total_trade_pnl,
                    close_reason=close_reason,
                )
                events.append({
                    "event_type": "POSITION_CLOSED",
                    "reason": close_reason,
                    "coin": coin,
                    "side": side,
                    "pnl_usdt": total_trade_pnl,
                    "trade": closed_record,
                })
                closed_completely = True

            # ب) اگر استاپ نخورده، بررسی برخورد به TP1 (در صورتی که قبلاً TP1 نخورده باشد)
            if not closed_completely and not tp1_hit:
                tp1_triggered = (side == "LONG" and bar_high >= tp1) or (
                    side == "SHORT" and bar_low <= tp1
                )
                if tp1_triggered:
                    half_qty = round(init_qty * 0.50, 6)
                    rem_qty = round(max(0.0, init_qty - half_qty), 6)

                    gross_partial = (
                        (tp1 - entry) * half_qty
                        if side == "LONG"
                        else (entry - tp1) * half_qty
                    )
                    partial_fee = (tp1 * half_qty) * self.maker_fee
                    net_partial_pnl = round(gross_partial - partial_fee, 4)

                    portfolio["balance_usdt"] = round(
                        float(portfolio["balance_usdt"]) + net_partial_pnl, 4
                    )
                    portfolio["daily_pnl_usdt"] = round(
                        float(portfolio["daily_pnl_usdt"]) + net_partial_pnl, 4
                    )

                    pos["tp1_hit"] = True
                    pos["risk_free"] = True
                    pos["remaining_quantity"] = rem_qty
                    pos["current_stop_loss"] = entry  # انتقال استاپ به نقطه ورود (Risk-Free)
                    pos["realized_partial_pnl"] = round(
                        float(pos.get("realized_partial_pnl", 0.0)) + net_partial_pnl, 4
                    )
                    pos["margin_used_usdt"] = round(float(pos.get("margin_used_usdt", 0.0)) * 0.5, 4)
                    tp1_hit = True

                    events.append({
                        "event_type": "TP1_PARTIAL_AND_RISK_FREE",
                        "reason": "TP1_HIT",
                        "coin": coin,
                        "side": side,
                        "partial_pnl_usdt": net_partial_pnl,
                        "new_sl": entry,
                        "position": dict(pos),
                    })

            # ج) بررسی برخورد به تارگت نهایی (TP2)
            if not closed_completely:
                tp2_triggered = (side == "LONG" and bar_high >= tp2) or (
                    side == "SHORT" and bar_low <= tp2
                )
                if tp2_triggered:
                    exit_price = tp2
                    gross_final = (
                        (exit_price - entry) * rem_qty
                        if side == "LONG"
                        else (entry - exit_price) * rem_qty
                    )
                    final_fee = (exit_price * rem_qty) * self.maker_fee
                    net_final_pnl = round(gross_final - final_fee, 4)

                    portfolio["balance_usdt"] = round(
                        float(portfolio["balance_usdt"]) + net_final_pnl, 4
                    )
                    portfolio["daily_pnl_usdt"] = round(
                        float(portfolio["daily_pnl_usdt"]) + net_final_pnl, 4
                    )

                    total_trade_pnl = round(
                        float(pos.get("realized_partial_pnl", 0.0)) + net_final_pnl, 4
                    )
                    closed_record = self._finalize_closed_trade(
                        portfolio=portfolio,
                        pos=pos,
                        exit_price=exit_price,
                        total_pnl_usdt=total_trade_pnl,
                        close_reason="TP2_FINAL_TARGET_HIT",
                    )
                    events.append({
                        "event_type": "POSITION_CLOSED",
                        "reason": "TP2_FINAL_TARGET_HIT",
                        "coin": coin,
                        "side": side,
                        "pnl_usdt": total_trade_pnl,
                        "trade": closed_record,
                    })
                    closed_completely = True

            if not closed_completely:
                still_open.append(pos)

        portfolio["open_positions"] = still_open
        self._check_and_update_circuit_breaker(portfolio)
        return events

    # ==========================================================================
    # ۴. بستن اضطراری تمام پوزیشن‌ها (/panic یا /close_all)
    # ==========================================================================
    def close_all_panic(
        self,
        portfolio: Dict[str, Any],
        bot_config: Dict[str, Any],
        live_prices: Optional[Dict[str, float]] = None,
        lock_panic: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        بستن فوری تمام پوزیشن‌های باز با قیمت مارکت (یا قیمت ورود در صورت عدم دسترسی به قیمت لحظه‌ای)
        و قفل کردن ربات در صورت lock_panic = True.
        """
        open_positions = portfolio.get("open_positions", [])
        closed_events: List[Dict[str, Any]] = []
        prices = live_prices or {}

        for pos in open_positions:
            coin = str(pos.get("coin", ""))
            side = str(pos.get("side", "LONG")).upper()
            entry = float(pos.get("entry_price", 0.0))
            rem_qty = float(pos.get("remaining_quantity", pos.get("initial_quantity", 0.0)))
            exit_price = float(prices.get(coin) or prices.get(pos.get("symbol", "")) or entry)

            gross_pnl = (
                (exit_price - entry) * rem_qty
                if side == "LONG"
                else (entry - exit_price) * rem_qty
            )
            exit_fee = (exit_price * rem_qty) * self.taker_fee
            net_leg_pnl = round(gross_pnl - exit_fee, 4)

            portfolio["balance_usdt"] = round(float(portfolio["balance_usdt"]) + net_leg_pnl, 4)
            portfolio["daily_pnl_usdt"] = round(float(portfolio["daily_pnl_usdt"]) + net_leg_pnl, 4)

            total_trade_pnl = round(float(pos.get("realized_partial_pnl", 0.0)) + net_leg_pnl, 4)
            reason = "PANIC_EMERGENCY_CLOSE" if lock_panic else "MANUAL_CLOSE_ALL"

            closed_rec = self._finalize_closed_trade(
                portfolio=portfolio,
                pos=pos,
                exit_price=exit_price,
                total_pnl_usdt=total_trade_pnl,
                close_reason=reason,
            )
            closed_events.append(closed_rec)

        portfolio["open_positions"] = []
        if lock_panic:
            bot_config["panic_mode"] = True
            bot_config["is_paused"] = True

        self._check_and_update_circuit_breaker(portfolio)
        return closed_events

    # ==========================================================================
    # ۵. ثبت سیگنال‌های فیلترشده در رادار سایه (Shadow Portfolio Recorder)
    # ==========================================================================
    def record_shadow_trade(
        self,
        shadow_portfolio: Dict[str, Any],
        coin: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        tp1_price: float,
        tp2_price: float,
        filter_reason: str,
        score: float = 0.0,
        regime: str = "RANGING",
    ) -> Dict[str, Any]:
        """
        ثبت ستاپ ردشده در لیست active_shadows فایل shadow_portfolio.json جهت ارزیابی بعدی توسط ML.
        """
        if "active_shadows" not in shadow_portfolio or not isinstance(
            shadow_portfolio["active_shadows"], list
        ):
            shadow_portfolio["active_shadows"] = []

        # جلوگیری از ثبت سایه تکراری روی همان ارز و همان جهت در یک زمان
        for existing in shadow_portfolio["active_shadows"]:
            if existing.get("coin") == coin and existing.get("side") == side:
                return existing

        shadow_item: Dict[str, Any] = {
            "shadow_id": f"SHD-{coin}-{uuid.uuid4().hex[:6].upper()}",
            "coin": coin,
            "side": str(side).upper(),
            "regime": regime,
            "score": round(float(score), 2),
            "entry_price": round(float(entry_price), 6),
            "stop_loss": round(float(stop_loss), 6),
            "tp1_price": round(float(tp1_price), 6),
            "tp2_price": round(float(tp2_price), 6),
            "filter_reason": filter_reason,
            "created_at": self._utc_now_iso(),
        }

        shadow_portfolio["active_shadows"].append(shadow_item)
        if "stats" in shadow_portfolio and isinstance(shadow_portfolio["stats"], dict):
            shadow_portfolio["stats"]["total_filtered"] = (
                int(shadow_portfolio["stats"].get("total_filtered", 0)) + 1
            )

        return shadow_item

    # ==========================================================================
    # متدهای کمکی محاسبه آمار پرتفوی، منحنی سرمایه و مدارشکن
    # ==========================================================================
    def _finalize_closed_trade(
        self,
        portfolio: Dict[str, Any],
        pos: Dict[str, Any],
        exit_price: float,
        total_pnl_usdt: float,
        close_reason: str,
    ) -> Dict[str, Any]:
        """ثبت معامله بسته‌شده در تاریخچه، آپدیت برد/باخت متوالی، آمار کل و منحنی سرمایه."""
        now_iso = self._utc_now_iso()
        risk_amt = max(float(pos.get("risk_amount_usdt", 5.0)), 1e-6)
        realized_r = round(total_pnl_usdt / risk_amt, 2)
        is_win = total_pnl_usdt >= 0.0

        closed_record: Dict[str, Any] = {
            "position_id": pos.get("position_id", ""),
            "coin": pos.get("coin", ""),
            "symbol": pos.get("symbol", ""),
            "side": pos.get("side", "LONG"),
            "regime": pos.get("regime", "RANGING"),
            "strategy": pos.get("strategy", ""),
            "score": pos.get("score", 0.0),
            "entry_price": pos.get("entry_price", 0.0),
            "exit_price": round(float(exit_price), 6),
            "stop_loss": pos.get("initial_stop_loss", 0.0),
            "tp1_price": pos.get("tp1_price", 0.0),
            "tp2_price": pos.get("tp2_price", 0.0),
            "tp1_hit": bool(pos.get("tp1_hit", False)),
            "pnl_usdt": round(total_pnl_usdt, 4),
            "realized_r": realized_r,
            "result": "WIN" if is_win else "LOSS",
            "close_reason": close_reason,
            "opened_at": pos.get("opened_at", now_iso),
            "closed_at": now_iso,
        }

        if "trade_history" not in portfolio or not isinstance(portfolio["trade_history"], list):
            portfolio["trade_history"] = []
        portfolio["trade_history"].append(closed_record)

        # بروزرسانی برد و باخت‌های متوالی
        if is_win:
            portfolio["consecutive_wins"] = int(portfolio.get("consecutive_wins", 0)) + 1
            portfolio["consecutive_losses"] = 0
        else:
            portfolio["consecutive_losses"] = int(portfolio.get("consecutive_losses", 0)) + 1
            portfolio["consecutive_wins"] = 0

        # بروزرسانی منحنی سرمایه (Equity Curve)
        curr_bal = round(float(portfolio.get("balance_usdt", 1000.0)), 4)
        if "equity_curve" not in portfolio or not isinstance(portfolio["equity_curve"], list):
            portfolio["equity_curve"] = []
        portfolio["equity_curve"].append({"timestamp": now_iso, "equity": curr_bal})

        # بروزرسانی آمار کل (Stats)
        stats = portfolio.get("stats", {})
        total_trades = int(stats.get("total_trades", 0)) + 1
        wins = int(stats.get("wins", 0)) + (1 if is_win else 0)
        losses = int(stats.get("losses", 0)) + (0 if is_win else 1)
        win_rate = round((wins / total_trades) * 100.0, 2) if total_trades > 0 else 0.0
        total_pnl = round(float(stats.get("total_pnl_usdt", 0.0)) + total_pnl_usdt, 4)

        # محاسبه حداکثر افت سرمایه تاریخی (Max Drawdown %)
        equities = [float(pt.get("equity", curr_bal)) for pt in portfolio["equity_curve"]]
        peak = equities[0] if equities else 1000.0
        max_dd = float(stats.get("max_drawdown_pct", 0.0))
        for eq in equities:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = ((peak - eq) / peak) * 100.0
                if dd > max_dd:
                    max_dd = round(dd, 2)

        portfolio["stats"] = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate,
            "total_pnl_usdt": total_pnl,
            "max_drawdown_pct": max_dd,
        }

        return closed_record

    def _check_and_update_circuit_breaker(self, portfolio: Dict[str, Any]) -> None:
        """بررسی فعال شدن مدارشکن روزانه پس از بسته شدن هر معامله."""
        day_eq = float(portfolio.get("day_start_equity", 1000.0))
        daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        if day_eq > 0 and daily_pnl < 0:
            dd_pct = (abs(daily_pnl) / day_eq) * 100.0
            if dd_pct >= self.max_daily_dd_pct:
                portfolio["daily_circuit_breaker"] = True