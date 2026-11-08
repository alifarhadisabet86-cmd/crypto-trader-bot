"""
مهارت دهم (نسخه V2.6 Pro): اجرای سفارشات، گارد اسپرد ۵٪، قفل سود ۳ پله‌ای با حفظ ۱۰۰٪ حجم در TP1 و اکشن‌های فوری تلگرام
Institutional Trading Bot V2.6 Pro - Broker Execution, 3-Stage Full-Volume Profit Lock & Quick Actions
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import uuid

import pandas as pd

from core.config import RISK_CONFIG, EXCHANGE_CONFIG


class BrokerExecutionSkill:
    """
    کلاس مدیریت چرخه حیات پوزیشن‌ها در پرتفوی شامل:
    - گارد اسپرد ۵٪ و باز کردن پوزیشن با کارمزد Maker (0.02%)
    - قفل سود ۳ پله‌ای با حفظ ۱۰۰٪ حجم پوزیشن:
      * پله ۱ (لمس TP1 در 1.15R): حفظ ۱۰۰٪ حجم + انتقال استاپ به Entry + 0.25R (پوشش کامل کارمزد + سود اولیه)
      * پله ۲ (عبور از 1.60R): انتقال استاپ ۱۰۰٪ پوزیشن به روی خط TP1 (1.15R) یا پشت سوئینگ ۱۵ دقیقه
      * پله ۳ (رسیدن به ۸۰٪ مسیر TP2): قفل استاپ روی ۷۰٪ مسیر TP2 برای جلوگیری از بازگشت سود در لحظه آخر
    - اکشن‌های فوری تلگرام: ریسک‌فری سریع و سیو سود پله‌ای دستی ۵۰٪
    """

    def __init__(self) -> None:
        self.maker_fee: float = float(RISK_CONFIG["MAKER_FEE_RATE"])
        self.taker_fee: float = float(RISK_CONFIG["TAKER_FEE_RATE"])
        self.max_spread_ratio: float = float(RISK_CONFIG["MAX_SPREAD_TO_TP_RATIO"])
        self.tp1_lock_offset_r: float = float(EXCHANGE_CONFIG.get("TP1_LOCK_OFFSET_R", 0.25))

    @staticmethod
    def _now_utc_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ==========================================================================
    # ۱. گارد اسپرد ۵٪ (5% Spread-to-Profit Guard)
    # ==========================================================================
    def check_spread_guard(
        self,
        spread_data: Dict[str, Any],
        entry_price: float,
        tp2_final: float,
    ) -> Dict[str, Any]:
        spread_abs = float(spread_data.get("spread_abs", 0.0))
        target_dist = abs(float(tp2_final) - float(entry_price))

        if target_dist <= 1e-8:
            return {
                "passed": False,
                "spread_to_tp_ratio": 1.0,
                "spread_to_tp_pct": 100.0,
                "reason": "ZERO_TARGET_DISTANCE",
            }

        ratio = spread_abs / target_dist
        passed = bool(ratio <= self.max_spread_ratio + 1e-9)

        return {
            "passed": passed,
            "spread_abs": round(spread_abs, 6),
            "target_distance": round(target_dist, 6),
            "spread_to_tp_ratio": round(ratio, 4),
            "spread_to_tp_pct": round(ratio * 100.0, 2),
            "max_allowed_pct": round(self.max_spread_ratio * 100.0, 2),
            "reason": "OK" if passed else "SPREAD_GUARD_5PCT_BLOCKED",
        }

    # ==========================================================================
    # ۲. باز کردن پوزیشن جدید
    # ==========================================================================
    def open_paper_position(
        self,
        portfolio: Dict[str, Any],
        coin: str,
        side: str,
        entry_plan: Dict[str, Any],
        exit_plan: Dict[str, Any],
        allocation: Dict[str, Any],
        regime_data: Dict[str, Any],
        confluence_data: Dict[str, Any],
        spread_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entry_price = float(exit_plan["entry_price"])
        tp2_final = float(exit_plan["tp2_final"])

        if spread_data is not None:
            guard = self.check_spread_guard(spread_data, entry_price, tp2_final)
            if not guard["passed"]:
                return {"opened": False, "reason": guard["reason"], "guard": guard}

        notional_usdt = float(allocation["notional_usdt"])
        qty = float(allocation["qty"])
        entry_fee_usdt = notional_usdt * self.maker_fee

        portfolio["balance_usdt"] = round(float(portfolio["balance_usdt"]) - entry_fee_usdt, 4)
        portfolio["daily_pnl_usdt"] = round(float(portfolio.get("daily_pnl_usdt", 0.0)) - entry_fee_usdt, 4)
        portfolio["weekly_pnl_usdt"] = round(float(portfolio.get("weekly_pnl_usdt", 0.0)) - entry_fee_usdt, 4)
        portfolio["stats"]["total_fees_paid_usdt"] = round(
            float(portfolio["stats"].get("total_fees_paid_usdt", 0.0)) + entry_fee_usdt, 4
        )

        pos_id = f"POS-{coin.upper()}-{uuid.uuid4().hex[:6].upper()}"
        stop_loss = float(exit_plan["stop_loss"])
        stop_dist = max(abs(entry_price - stop_loss), 1e-8)

        position_obj: Dict[str, Any] = {
            "id": pos_id,
            "coin": str(coin).upper(),
            "side": str(side).upper(),
            "order_type": entry_plan.get("order_type", "LIMIT"),
            "trigger_type": entry_plan.get("trigger_type", "LIMIT_MAKER"),
            "regime": regime_data.get("regime", "RANGING"),
            "confluence_score": float(confluence_data.get("final_score", 70.0)),
            "xray_summary_fa": confluence_data.get("xray_summary_fa", ""),
            "slot_type": allocation.get("slot_type", "STANDARD_SLOT"),
            "entry_price": round(entry_price, 6),
            "current_price": round(entry_price, 6),
            "stop_loss": round(stop_loss, 6),
            "initial_stop_loss": round(stop_loss, 6),
            "stop_distance": round(stop_dist, 6),
            "tp1_breakeven": round(float(exit_plan["tp1_breakeven"]), 6),
            "tp2_final": round(tp2_final, 6),
            "initial_qty": round(qty, 6),
            "remaining_qty": round(qty, 6),
            "initial_notional_usdt": round(notional_usdt, 2),
            "remaining_notional_usdt": round(notional_usdt, 2),
            "margin_used_usdt": round(float(allocation["margin_used_usdt"]), 2),
            "initial_risk_usdt": round(float(allocation["risk_amount_usdt"]), 2),
            "tp1_hit": False,
            "is_risk_free": False,
            "trailing_active": False,
            "realized_pnl_usdt": round(-entry_fee_usdt, 4),
            "unrealized_pnl_usdt": 0.0,
            "fees_paid_usdt": round(entry_fee_usdt, 4),
            "opened_at": self._now_utc_iso(),
        }

        portfolio.setdefault("open_positions", []).append(position_obj)
        return {"opened": True, "position": position_obj, "reason": "OK"}

    # ==========================================================================
    # ۳. مدیریت پوزیشن‌های باز + قفل سود ۳ پله‌ای (بدون فروش حجم در TP1)
    # ==========================================================================
    def update_open_positions(
        self,
        portfolio: Dict[str, Any],
        market_data_15m: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        open_positions: List[Dict[str, Any]] = portfolio.get("open_positions", [])
        if not open_positions:
            return {"events": [], "closed_trades": [], "total_unrealized_pnl_usdt": 0.0}

        still_open: List[Dict[str, Any]] = []
        closed_this_cycle: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []
        total_unrealized = 0.0

        for pos in open_positions:
            coin = pos["coin"]
            df = market_data_15m.get(coin)
            if df is None or df.empty:
                still_open.append(pos)
                continue

            last_row = df.iloc[-1]
            c_high = float(last_row["high"])
            c_low = float(last_row["low"])
            c_close = float(last_row["close"])
            pos["current_price"] = round(c_close, 6)

            side = pos["side"]
            entry = float(pos["entry_price"])
            sl = float(pos.get("stop_loss", pos.get("current_stop_loss", pos.get("initial_stop_loss", entry))))
            pos["stop_loss"] = sl
            tp1 = float(pos.get("tp1_breakeven", pos.get("tp1_price", entry)))
            pos["tp1_breakeven"] = tp1
            tp2 = float(pos.get("tp2_final", pos.get("tp2_price", entry)))
            pos["tp2_final"] = tp2
            rem_qty = float(pos.get("remaining_qty", pos.get("remaining_quantity", 0.0)))
            pos["remaining_qty"] = rem_qty

            # ۱. بررسی برخورد با حد ضرر (Stop-Loss یا Break-Even یا Trailing Stop)
            sl_hit = (side == "LONG" and c_low <= sl) or (side == "SHORT" and c_high >= sl)
            if sl_hit:
                exit_price = sl
                if pos.get("trailing_active"):
                    reason = "TRAILING_STOP_PROFIT"
                elif pos.get("is_risk_free") or pos.get("risk_free"):
                    reason = "BREAKEVEN_STOP"
                else:
                    reason = "STOP_LOSS"
                closed_record = self._execute_full_close(portfolio, pos, exit_price, reason)
                closed_this_cycle.append(closed_record)
                events.append({"type": reason, "coin": coin, "side": side, "trade": closed_record})
                continue

            # ۲. بررسی برخورد با تارگت اول (پله ۱: حفظ ۱۰۰٪ حجم + انتقال استاپ به Entry + 0.25R)
            if not pos.get("tp1_hit", False):
                tp1_reached = (side == "LONG" and c_high >= tp1) or (
                    side == "SHORT" and c_low <= tp1
                )
                if tp1_reached:
                    partial_info = self._execute_partial_tp1(portfolio, pos, tp1)
                    events.append({
                        "type": "TP1_PARTIAL_AND_BREAKEVEN",
                        "coin": coin,
                        "side": side,
                        "details": partial_info,
                    })
                    rem_qty = float(pos["remaining_qty"])

            # ۳. بررسی تریلینگ استاپ پله ۲ (در 1.60R قفل روی TP1) و پله ۳ (در 80% مسیر TP2 قفل روی 70% سود)
            if (pos.get("is_risk_free", False) or pos.get("risk_free", False)) and len(df) >= 6:
                trail_event = self._apply_structural_trailing_stop(pos, df, c_close, c_high, c_low)
                if trail_event is not None:
                    events.append(trail_event)

            # ۴. بررسی برخورد با تارگت نهایی (TP2)
            tp2_reached = (side == "LONG" and c_high >= tp2) or (
                side == "SHORT" and c_low <= tp2
            )
            if tp2_reached:
                closed_record = self._execute_full_close(portfolio, pos, tp2, "TP2_FINAL_TARGET")
                closed_this_cycle.append(closed_record)
                events.append({
                    "type": "TP2_FINAL_TARGET",
                    "coin": coin,
                    "side": side,
                    "trade": closed_record,
                })
                continue

            # ۵. بروزرسانی سود/زیان شناور (Unrealized PnL)
            if side == "LONG":
                u_pnl = (c_close - entry) * rem_qty
            else:
                u_pnl = (entry - c_close) * rem_qty

            pos["unrealized_pnl_usdt"] = round(u_pnl, 2)
            total_unrealized += u_pnl
            still_open.append(pos)

        portfolio["open_positions"] = still_open
        self._update_peak_and_drawdown(portfolio, total_unrealized)

        return {
            "events": events,
            "closed_trades": closed_this_cycle,
            "total_unrealized_pnl_usdt": round(total_unrealized, 2),
        }

    def _apply_structural_trailing_stop(
        self,
        pos: Dict[str, Any],
        df_15m: pd.DataFrame,
        current_price: float,
        candle_high: Optional[float] = None,
        candle_low: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        تریلینگ استاپ هوشمند دوپله‌ای پس از ریسک‌فری شدن:
        - پله ۲: وقتی قیمت به 1.60R رسید، استاپِ کل ۱۰۰٪ پوزیشن مستقیماً روی خط TP1 (1.15R) یا پشت سوئینگ ۱۵ دقیقه قفل می‌شود.
        - پله ۳: وقتی قیمت به ۸۰٪ فاصله تا TP2 رسید، استاپ روی ۷۰٪ فاصله تا TP2 چسبانده می‌شود تا سود بزرگ از دست نرود.
        """
        side = pos["side"]
        entry = float(pos["entry_price"])
        curr_sl = float(pos.get("stop_loss", entry))
        tp1 = float(pos.get("tp1_breakeven", entry))
        tp2 = float(pos.get("tp2_final", entry))
        stop_dist = max(float(pos.get("stop_distance", abs(entry - float(pos.get("initial_stop_loss", entry))))), 1e-8)
        tp2_dist = max(abs(tp2 - entry), stop_dist)

        recent_5 = df_15m.iloc[-6:-1]
        if recent_5.empty:
            return None

        best_high = max(float(candle_high or current_price), current_price)
        best_low = min(float(candle_low or current_price), current_price)

        if side == "LONG":
            peak_r = (best_high - entry) / stop_dist
            tp2_progress = (best_high - entry) / tp2_dist
            if peak_r >= 1.60:
                swing_low = float(recent_5["low"].min())
                # در پله ۲، کف استاپ دقیقاً روی TP1 (1.15R) قرار می‌گیرد
                min_locked_sl = max(tp1, entry + (1.15 * stop_dist))
                # در پله ۳ (رسیدن به ۸۰٪ مسیر TP2)، کف استاپ به ۷۰٪ مسیر TP2 ارتقا می‌یابد
                if tp2_progress >= 0.80:
                    min_locked_sl = max(min_locked_sl, entry + (0.70 * tp2_dist))
                candidate_sl = max(swing_low, min_locked_sl)
                if candidate_sl >= current_price:
                    candidate_sl = min_locked_sl
                if candidate_sl > curr_sl + (0.05 * stop_dist) and candidate_sl < current_price:
                    old_sl = curr_sl
                    pos["stop_loss"] = round(candidate_sl, 6)
                    pos["trailing_active"] = True
                    return {
                        "type": "STRUCTURAL_TRAILING_UPDATED",
                        "coin": pos["coin"],
                        "side": side,
                        "old_sl": old_sl,
                        "new_sl": pos["stop_loss"],
                    }
        else:
            peak_r = (entry - best_low) / stop_dist
            tp2_progress = (entry - best_low) / tp2_dist
            if peak_r >= 1.60:
                swing_high = float(recent_5["high"].max())
                # در پله ۲، سقف استاپ شورت دقیقاً روی TP1 (1.15R) قرار می‌گیرد
                min_locked_sl = min(tp1, entry - (1.15 * stop_dist))
                # در پله ۳ (رسیدن به ۸۰٪ مسیر TP2)، استاپ به ۷۰٪ مسیر TP2 نزدیک می‌شود
                if tp2_progress >= 0.80:
                    min_locked_sl = min(min_locked_sl, entry - (0.70 * tp2_dist))
                candidate_sl = min(swing_high, min_locked_sl)
                if candidate_sl <= current_price:
                    candidate_sl = min_locked_sl
                if candidate_sl < curr_sl - (0.05 * stop_dist) and candidate_sl > current_price:
                    old_sl = curr_sl
                    pos["stop_loss"] = round(candidate_sl, 6)
                    pos["trailing_active"] = True
                    return {
                        "type": "STRUCTURAL_TRAILING_UPDATED",
                        "coin": pos["coin"],
                        "side": side,
                        "old_sl": old_sl,
                        "new_sl": pos["stop_loss"],
                    }
        return None

    # ==========================================================================
    # ۴. اکشن‌های فوری اتاق فرمان تلگرام (دکمه‌های شیشه‌ای ردیف چهارم)
    # ==========================================================================
    def risk_free_all_in_profit(
        self,
        portfolio: Dict[str, Any],
        live_prices: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        مخصوص دکمه [ 🛡️ ریسک‌فری سریع ]:
        انتقال فوری حد ضرر تمام پوزیشن‌هایی که در سود هستند به نقطه ورود (Break-Even).
        """
        prices = live_prices or {}
        open_positions = portfolio.get("open_positions", [])
        updated_coins: List[str] = []

        for pos in open_positions:
            if pos.get("is_risk_free", False) or pos.get("risk_free", False):
                continue

            coin = pos["coin"]
            side = pos["side"]
            entry = float(pos["entry_price"])
            curr_price = float(prices.get(coin, pos.get("current_price", entry)))
            pos["current_price"] = round(curr_price, 6)

            in_profit = (side == "LONG" and curr_price > entry) or (
                side == "SHORT" and curr_price < entry
            ) or float(pos.get("unrealized_pnl_usdt", 0.0)) > 0.0

            if in_profit:
                pos["stop_loss"] = round(entry, 6)
                pos["is_risk_free"] = True
                updated_coins.append(coin)

        return {
            "updated_count": len(updated_coins),
            "updated_coins": updated_coins,
        }

    def partial_close_all_in_profit(
        self,
        portfolio: Dict[str, Any],
        close_fraction: float = 0.50,
        live_prices: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        مخصوص دکمه دستی [ 💰 سیو سود پله‌ای (۵۰٪) ]:
        نقد کردن فوری ۵۰٪ از حجم تمام پوزیشن‌های در سود روی قیمت فعلی بازار،
        افزودن سود قطعی به موجودی حساب، و ریسک‌فری کردن ۵۰٪ باقی‌مانده.
        """
        prices = live_prices or {}
        open_positions = portfolio.get("open_positions", [])
        fraction = max(0.10, min(0.90, float(close_fraction)))

        closed_coins: List[str] = []
        total_locked_pnl = 0.0

        for pos in open_positions:
            coin = pos["coin"]
            side = pos["side"]
            entry = float(pos["entry_price"])
            rem_qty = float(pos.get("remaining_qty", pos.get("remaining_quantity", 0.0)))
            curr_price = float(prices.get(coin, pos.get("current_price", entry)))
            pos["current_price"] = round(curr_price, 6)

            raw_u_pnl = (curr_price - entry) * rem_qty if side == "LONG" else (entry - curr_price) * rem_qty
            if raw_u_pnl <= 0.05 or rem_qty <= 1e-8:
                continue

            close_qty = rem_qty * fraction
            rem_after = rem_qty - close_qty
            gross_pnl = (curr_price - entry) * close_qty if side == "LONG" else (entry - curr_price) * close_qty
            fee_usdt = (close_qty * curr_price) * self.taker_fee
            net_pnl = gross_pnl - fee_usdt

            portfolio["balance_usdt"] = round(float(portfolio["balance_usdt"]) + net_pnl, 4)
            portfolio["daily_pnl_usdt"] = round(float(portfolio.get("daily_pnl_usdt", 0.0)) + net_pnl, 4)
            portfolio["weekly_pnl_usdt"] = round(float(portfolio.get("weekly_pnl_usdt", 0.0)) + net_pnl, 4)
            portfolio["stats"]["total_fees_paid_usdt"] = round(
                float(portfolio["stats"].get("total_fees_paid_usdt", 0.0)) + fee_usdt, 4
            )

            pos["remaining_qty"] = round(rem_after, 6)
            pos["remaining_notional_usdt"] = round(rem_after * entry, 2)
            pos["margin_used_usdt"] = round(float(pos.get("margin_used_usdt", 0.0)) * (1.0 - fraction), 2)
            pos["realized_pnl_usdt"] = round(float(pos.get("realized_pnl_usdt", pos.get("realized_partial_pnl", 0.0))) + net_pnl, 4)
            pos["fees_paid_usdt"] = round(float(pos.get("fees_paid_usdt", pos.get("entry_fee_usdt", 0.0))) + fee_usdt, 4)
            pos["unrealized_pnl_usdt"] = round(raw_u_pnl * (1.0 - fraction), 2)

            pos["stop_loss"] = round(entry, 6)
            pos["is_risk_free"] = True
            pos["tp1_hit"] = True

            closed_coins.append(coin)
            total_locked_pnl += net_pnl

        return {
            "closed_count": len(closed_coins),
            "closed_coins": closed_coins,
            "total_locked_pnl_usdt": round(total_locked_pnl, 2),
        }

    def close_all_positions(
        self,
        portfolio: Dict[str, Any],
        live_prices: Optional[Dict[str, float]] = None,
        reason: str = "MANUAL_PANIC_CLOSE",
    ) -> List[Dict[str, Any]]:
        open_positions = list(portfolio.get("open_positions", []))
        closed_records: List[Dict[str, Any]] = []
        prices = live_prices or {}

        for pos in open_positions:
            coin = pos["coin"]
            exit_p = float(prices.get(coin, pos.get("current_price", pos["entry_price"])))
            rec = self._execute_full_close(portfolio, pos, exit_p, reason)
            closed_records.append(rec)

        portfolio["open_positions"] = []
        return closed_records

    # ==========================================================================
    # متدهای داخلی تسویه حساب
    # ==========================================================================
    def _execute_partial_tp1(
        self, portfolio: Dict[str, Any], pos: Dict[str, Any], tp1_price: float
    ) -> Dict[str, Any]:
        """
        پله اول قفل سود هنگام لمس TP1 (1.15R):
        بدون فروش هیچ حجمی (نگهداری ۱۰۰٪ حجم برای سود بزرگ تا TP2)،
        استاپ‌لاس به نقطه Entry + 0.25R منتقل می‌شود تا کارمزد صرافی + سود اولیه تضمین گردد.
        """
        side = pos["side"]
        entry = float(pos["entry_price"])
        stop_dist = max(float(pos.get("stop_distance", abs(entry - float(pos.get("initial_stop_loss", entry))))), 1e-8)
        lock_offset = self.tp1_lock_offset_r * stop_dist

        if side == "LONG":
            new_sl = round(entry + lock_offset, 6)
        else:
            new_sl = round(entry - lock_offset, 6)

        pos["tp1_hit"] = True
        pos["is_risk_free"] = True
        pos["stop_loss"] = new_sl

        return {
            "closed_qty": 0.0,
            "net_partial_pnl_usdt": 0.0,
            "new_stop_loss": pos["stop_loss"],
            "locked_r": self.tp1_lock_offset_r,
        }

    def _execute_full_close(
        self,
        portfolio: Dict[str, Any],
        pos: Dict[str, Any],
        exit_price: float,
        exit_reason: str,
    ) -> Dict[str, Any]:
        side = pos["side"]
        entry = float(pos["entry_price"])
        rem_qty = float(pos.get("remaining_qty", pos.get("remaining_quantity", 0.0)))

        if side == "LONG":
            gross_pnl = (exit_price - entry) * rem_qty
        else:
            gross_pnl = (entry - exit_price) * rem_qty

        exit_notional = rem_qty * exit_price
        fee_rate = self.maker_fee if "TP2" in exit_reason else self.taker_fee
        fee_usdt = exit_notional * fee_rate
        net_leg_pnl = gross_pnl - fee_usdt

        portfolio["balance_usdt"] = round(float(portfolio["balance_usdt"]) + net_leg_pnl, 4)
        portfolio["daily_pnl_usdt"] = round(float(portfolio.get("daily_pnl_usdt", 0.0)) + net_leg_pnl, 4)
        portfolio["weekly_pnl_usdt"] = round(float(portfolio.get("weekly_pnl_usdt", 0.0)) + net_leg_pnl, 4)

        total_trade_pnl = float(pos.get("realized_pnl_usdt", pos.get("realized_partial_pnl", 0.0))) + net_leg_pnl
        total_fees = float(pos.get("fees_paid_usdt", pos.get("entry_fee_usdt", 0.0))) + fee_usdt
        init_risk = max(float(pos.get("initial_risk_usdt", pos.get("risk_amount_usdt", 5.0))), 1e-8)
        r_multiple = total_trade_pnl / init_risk

        stats = portfolio["stats"]
        stats["total_trades"] = int(stats.get("total_trades", 0)) + 1
        stats["total_fees_paid_usdt"] = round(float(stats.get("total_fees_paid_usdt", 0.0)) + fee_usdt, 4)

        if total_trade_pnl > 0:
            stats["wins"] = int(stats.get("wins", 0)) + 1
            stats["consecutive_wins"] = int(stats.get("consecutive_wins", 0)) + 1
            stats["consecutive_losses"] = 0
            outcome = "WIN"
        else:
            stats["losses"] = int(stats.get("losses", 0)) + 1
            stats["consecutive_losses"] = int(stats.get("consecutive_losses", 0)) + 1
            stats["consecutive_wins"] = 0
            outcome = "LOSS"

        stats["win_rate_pct"] = round((stats["wins"] / max(stats["total_trades"], 1)) * 100.0, 2)

        now_iso = self._now_utc_iso()
        closed_record = {
            "id": str(pos.get("id", pos.get("position_id", f"POS-{pos['coin']}-CLOSED"))),
            "coin": pos["coin"],
            "side": side,
            "regime": pos.get("regime", "RANGING"),
            "confluence_score": float(pos.get("confluence_score", pos.get("score", 70.0))),
            "entry_price": entry,
            "exit_price": round(exit_price, 6),
            "exit_reason": exit_reason,
            "tp1_hit": bool(pos.get("tp1_hit", False)),
            "trailing_active": bool(pos.get("trailing_active", False)),
            "net_pnl_usdt": round(total_trade_pnl, 2),
            "r_multiple": round(r_multiple, 2),
            "fees_paid_usdt": round(total_fees, 4),
            "outcome": outcome,
            "opened_at": pos.get("opened_at", now_iso),
            "closed_at": now_iso,
        }

        portfolio.setdefault("closed_trades", []).append(closed_record)
        portfolio.setdefault("equity_curve", []).append({
            "timestamp": now_iso,
            "equity": round(float(portfolio["balance_usdt"]), 2),
            "event": f"{pos['coin']}_{exit_reason}",
        })

        self._update_peak_and_drawdown(portfolio, 0.0)
        return closed_record

    @staticmethod
    def _update_peak_and_drawdown(portfolio: Dict[str, Any], unrealized_pnl: float) -> None:
        stats = portfolio["stats"]
        curr_eq = float(portfolio["balance_usdt"]) + float(unrealized_pnl)
        peak = float(stats.get("peak_equity_usdt", curr_eq))
        if curr_eq > peak:
            peak = curr_eq
            stats["peak_equity_usdt"] = round(peak, 2)

        if peak > 0:
            dd_pct = max(0.0, ((peak - curr_eq) / peak) * 100.0)
            stats["max_drawdown_pct"] = round(
                max(float(stats.get("max_drawdown_pct", 0.0)), dd_pct), 2
            )
