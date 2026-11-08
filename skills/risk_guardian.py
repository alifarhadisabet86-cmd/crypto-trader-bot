"""
مهارت هشتم (نسخه V2.6 Pro): نگهبان ریسک، مدارشکن ۲٪/۵٪، کول‌داون ۶۰ دقیقه، سایزینگ با احتساب کارمزد و تخصیص Hot-Hand
Institutional Trading Bot V2.6 Pro - Risk Guardian, Post-Trade Cooldown, Fee-Aware Sizing & Hot-Hand ML Allocation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import numpy as np

from core.config import RISK_CONFIG
from core.slot_manager import can_open_new_position


class RiskGuardianSkill:
    """
    کلاس نگهبان ریسک پرتفوی شامل:
    - مدارشکن روزانه (Daily Circuit Breaker 2.0%) و هفتگی (Weekly Circuit Breaker 5.0%)
    - کول‌داون ۶۰ دقیقه‌ای پس از بسته شدن معامله هر ارز (جلوگیری از ورود مجدد در انتهای موج)
    - تخصیص سرمایه هوشمند Hot-Hand / Cold-Coin بر اساس ضریب یادگیری ماشین هر ارز
    - محاسبه حجم پوزیشن با کسر کارمزد رفت‌وبرگشت از بودجه ریسک (Fee-Aware Sizing)
    """

    def __init__(self) -> None:
        self.max_daily_dd_pct: float = float(RISK_CONFIG["MAX_DAILY_DRAWDOWN_PCT"])
        self.max_weekly_dd_pct: float = float(RISK_CONFIG.get("MAX_WEEKLY_DRAWDOWN_PCT", 5.0))
        self.base_risk_pct: float = float(RISK_CONFIG["BASE_RISK_PCT"])
        self.win_streak_risk_pct: float = float(RISK_CONFIG["WIN_STREAK_RISK_PCT"])
        self.loss_streak_risk_pct: float = float(RISK_CONFIG["LOSS_STREAK_RISK_PCT"])
        self.max_margin_per_trade_pct: float = float(RISK_CONFIG["MAX_MARGIN_USAGE_PER_TRADE_PCT"])
        self.default_leverage: int = int(RISK_CONFIG["DEFAULT_LEVERAGE"])
        self.cooldown_minutes: int = int(RISK_CONFIG.get("TRADE_COOLDOWN_MINUTES", 60))
        self.round_trip_fee_rate: float = float(
            RISK_CONFIG.get("MAKER_FEE_RATE", 0.0002) + RISK_CONFIG.get("TAKER_FEE_RATE", 0.0006)
        )

    # ==========================================================================
    # ۱. بررسی مدارشکن روزانه ۲٪ و مدارشکن هفتگی ۵٪
    # ==========================================================================
    def check_circuit_breaker(
        self,
        portfolio: Dict[str, Any],
        unrealized_pnl_usdt: float = 0.0,
    ) -> Dict[str, Any]:
        """
        بررسی همزمان افت سرمایه روزانه (سقف ۲٪) و هفتگی (سقف ۵٪).
        """
        daily_start = float(
            portfolio.get(
                "daily_start_balance_usdt",
                portfolio.get("balance_usdt", RISK_CONFIG["INITIAL_BALANCE_USDT"]),
            )
        )
        daily_start = max(daily_start, 1e-8)
        realized_daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        total_daily_pnl = realized_daily_pnl + float(unrealized_pnl_usdt)

        daily_dd_pct = 0.0
        if total_daily_pnl < 0:
            daily_dd_pct = abs(total_daily_pnl) / daily_start * 100.0

        already_daily_locked = bool(portfolio.get("daily_circuit_breaker", False))
        daily_triggered = already_daily_locked or (daily_dd_pct >= self.max_daily_dd_pct - 1e-6)
        if daily_triggered:
            portfolio["daily_circuit_breaker"] = True

        weekly_start = float(
            portfolio.get(
                "weekly_start_balance_usdt",
                portfolio.get("balance_usdt", RISK_CONFIG["INITIAL_BALANCE_USDT"]),
            )
        )
        weekly_start = max(weekly_start, 1e-8)
        realized_weekly_pnl = float(portfolio.get("weekly_pnl_usdt", 0.0))
        total_weekly_pnl = realized_weekly_pnl + float(unrealized_pnl_usdt)

        weekly_dd_pct = 0.0
        if total_weekly_pnl < 0:
            weekly_dd_pct = abs(total_weekly_pnl) / weekly_start * 100.0

        already_weekly_locked = bool(portfolio.get("weekly_circuit_breaker", False))
        weekly_triggered = already_weekly_locked or (weekly_dd_pct >= self.max_weekly_dd_pct - 1e-6)
        if weekly_triggered:
            portfolio["weekly_circuit_breaker"] = True

        any_locked = bool(daily_triggered or weekly_triggered)
        reason = "OK"
        if daily_triggered:
            reason = "DAILY_CIRCUIT_BREAKER_2PCT_LOCKED"
        elif weekly_triggered:
            reason = "WEEKLY_CIRCUIT_BREAKER_5PCT_LOCKED"

        return {
            "locked": any_locked,
            "daily_locked": bool(daily_triggered),
            "weekly_locked": bool(weekly_triggered),
            "daily_drawdown_pct": round(daily_dd_pct, 3),
            "weekly_drawdown_pct": round(weekly_dd_pct, 3),
            "total_daily_pnl_usdt": round(total_daily_pnl, 2),
            "total_weekly_pnl_usdt": round(total_weekly_pnl, 2),
            "max_allowed_dd_pct": self.max_daily_dd_pct,
            "max_weekly_allowed_dd_pct": self.max_weekly_dd_pct,
            "reason": reason,
        }

    # ==========================================================================
    # ۲. بررسی کول‌داون ۶۰ دقیقه‌ای پس از بسته شدن معامله هر ارز
    # ==========================================================================
    def check_coin_cooldown(
        self,
        portfolio: Dict[str, Any],
        coin: str,
        now_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        جلوگیری از ورود مجدد بلافاصله پس از بسته شدن معامله روی همان ارز (حداقل ۶۰ دقیقه تنفس).
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        target_coin = str(coin).upper().strip()
        closed_list = portfolio.get("closed_trades", portfolio.get("trade_history", []))
        if not closed_list:
            return {"in_cooldown": False, "minutes_since_close": 999.0}

        for tr in reversed(closed_list):
            if str(tr.get("coin", "")).upper().strip() != target_coin:
                continue
            closed_str = str(tr.get("closed_at", "")).strip()
            if not closed_str:
                continue
            try:
                closed_dt = datetime.fromisoformat(closed_str.replace("Z", "+00:00")).astimezone(timezone.utc)
                elapsed_min = (now_utc - closed_dt).total_seconds() / 60.0
                if 0.0 <= elapsed_min < float(self.cooldown_minutes):
                    return {
                        "in_cooldown": True,
                        "minutes_since_close": round(elapsed_min, 1),
                        "remaining_minutes": round(float(self.cooldown_minutes) - elapsed_min, 1),
                    }
                break
            except Exception:
                continue

        return {"in_cooldown": False, "minutes_since_close": 999.0}

    # ==========================================================================
    # ۳. محاسبه درصد ریسک پویا + ضریب Hot-Hand / Cold-Coin یادگیری ماشین
    # ==========================================================================
    def compute_dynamic_risk_pct(
        self,
        portfolio: Dict[str, Any],
        bot_config: Optional[Dict[str, Any]] = None,
        size_multiplier: float = 1.0,
        coin_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        stats = portfolio.get("stats", {})
        c_wins = int(stats.get("consecutive_wins", portfolio.get("consecutive_wins", 0)))
        c_losses = int(stats.get("consecutive_losses", portfolio.get("consecutive_losses", 0)))

        if c_losses >= 2:
            streak_state = "LOSS_STREAK_DEFENSIVE"
            base_pct = self.loss_streak_risk_pct
        elif c_wins >= 2:
            streak_state = "WIN_STREAK_AGGRESSIVE"
            base_pct = self.win_streak_risk_pct
        else:
            streak_state = "NORMAL_BASELINE"
            base_pct = self.base_risk_pct

        risk_mode = str((bot_config or {}).get("risk_mode", "NORMAL")).upper().strip()
        mode_mult = 1.0
        if risk_mode == "LOW":
            mode_mult = 0.50
        elif risk_mode == "HIGH":
            mode_mult = 1.25

        # ضریب تخصیص سرمایه ستاره میدان (Hot-Hand) یا محافظت ارز سرد (Cold-Coin)
        c_mult = float(coin_multiplier)
        if c_mult < 0.90:
            hot_hand_mult = 0.60
        elif c_mult >= 1.03:
            hot_hand_mult = 1.20
        else:
            hot_hand_mult = 1.00

        effective_risk_pct = float(
            np.clip(base_pct * mode_mult * float(size_multiplier) * hot_hand_mult, 0.10, 1.20)
        )

        return {
            "streak_state": streak_state,
            "base_risk_pct": round(base_pct, 3),
            "risk_mode": risk_mode,
            "mode_multiplier": mode_mult,
            "size_multiplier": round(float(size_multiplier), 2),
            "hot_hand_multiplier": hot_hand_mult,
            "effective_risk_pct": round(effective_risk_pct, 4),
        }

    # ==========================================================================
    # ۴. ارزیابی کامل مجوز ریسک و محاسبه حجم پوزیشن با احتساب کارمزد صرافی
    # ==========================================================================
    def evaluate_trade_risk(
        self,
        portfolio: Dict[str, Any],
        coin: str,
        side: str,
        confluence_score: float,
        entry_price: float,
        stop_loss: float,
        size_multiplier: float = 1.0,
        bot_config: Optional[Dict[str, Any]] = None,
        unrealized_pnl_usdt: float = 0.0,
        coin_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        cfg = bot_config or {}

        if cfg.get("panic_mode", False):
            return self._reject("PANIC_MODE_ACTIVE")
        if cfg.get("is_paused", False):
            return self._reject("BOT_PAUSED_BY_USER")

        cb_status = self.check_circuit_breaker(portfolio, unrealized_pnl_usdt)
        if cb_status["locked"]:
            return self._reject(cb_status["reason"], cb_status)

        cooldown_status = self.check_coin_cooldown(portfolio, coin)
        if cooldown_status["in_cooldown"]:
            return self._reject("COIN_COOLDOWN_ACTIVE_60M", cooldown_status)

        open_positions = portfolio.get("open_positions", [])
        slot_check = can_open_new_position(
            open_positions=open_positions,
            candidate_coin=coin,
            candidate_side=side,
            candidate_score=confluence_score,
        )
        if not slot_check["allowed"]:
            return self._reject(slot_check["reason"], slot_check)

        entry = float(entry_price)
        sl = float(stop_loss)
        stop_dist = abs(entry - sl)
        if entry <= 0 or stop_dist <= 1e-8:
            return self._reject("INVALID_STOP_DISTANCE")

        balance = float(portfolio.get("balance_usdt", 0.0))
        if balance <= 10.0:
            return self._reject("INSUFFICIENT_BALANCE")

        risk_info = self.compute_dynamic_risk_pct(portfolio, cfg, size_multiplier, coin_multiplier)
        effective_risk_pct = risk_info["effective_risk_pct"]
        risk_amount_usdt = balance * (effective_risk_pct / 100.0)

        # لحاظ کردن کارمزد رفت‌وبرگشت در فاصله استاپ تا کل ضرر (قیمت + کارمزد) از 1.0R تجاوز نکند
        stop_dist_pct = stop_dist / entry
        effective_loss_pct = stop_dist_pct + self.round_trip_fee_rate
        raw_notional_usdt = risk_amount_usdt / effective_loss_pct

        leverage = self.default_leverage
        max_margin_usdt = balance * (self.max_margin_per_trade_pct / 100.0)
        max_notional_usdt = max_margin_usdt * leverage

        capped_by_margin = False
        if raw_notional_usdt > max_notional_usdt:
            notional_usdt = max_notional_usdt
            risk_amount_usdt = notional_usdt * effective_loss_pct
            capped_by_margin = True
        else:
            notional_usdt = raw_notional_usdt

        margin_used_usdt = notional_usdt / leverage
        qty = notional_usdt / entry

        return {
            "approved": True,
            "coin": str(coin).upper(),
            "side": str(side).upper(),
            "slot_type": slot_check["slot_type"],
            "leverage": leverage,
            "balance_usdt": round(balance, 2),
            "effective_risk_pct": round(effective_risk_pct, 4),
            "risk_amount_usdt": round(risk_amount_usdt, 2),
            "notional_usdt": round(notional_usdt, 2),
            "margin_used_usdt": round(margin_used_usdt, 2),
            "qty": round(qty, 6),
            "capped_by_margin": capped_by_margin,
            "streak_state": risk_info["streak_state"],
            "hot_hand_multiplier": risk_info["hot_hand_multiplier"],
            "daily_drawdown_pct": cb_status["daily_drawdown_pct"],
            "weekly_drawdown_pct": cb_status["weekly_drawdown_pct"],
            "reason": "APPROVED",
        }

    def evaluate_risk_and_size(
        self,
        portfolio: Dict[str, Any],
        candidate_coin: str,
        candidate_side: str,
        confluence_data: Dict[str, Any],
        exit_plan: Dict[str, Any],
        bot_config: Optional[Dict[str, Any]] = None,
        unrealized_pnl_usdt: float = 0.0,
    ) -> Dict[str, Any]:
        """پل سازگاری با نسخه V2.0 برای فراخوانی مستقیم از BudgetAllocationSkill یا تست‌ها."""
        conf = confluence_data or {}
        ex = exit_plan or {}
        return self.evaluate_trade_risk(
            portfolio=portfolio,
            coin=candidate_coin,
            side=candidate_side,
            confluence_score=float(conf.get("final_score", conf.get("score", 70.0))),
            entry_price=float(ex.get("entry_price", 0.0)),
            stop_loss=float(ex.get("stop_loss", 0.0)),
            size_multiplier=float(conf.get("size_multiplier", 1.0)),
            bot_config=bot_config,
            unrealized_pnl_usdt=unrealized_pnl_usdt,
            coin_multiplier=float(conf.get("coin_multiplier", 1.0)),
        )

    @staticmethod
    def _reject(reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "approved": False,
            "reason": reason,
            "details": details or {},
            "risk_amount_usdt": 0.0,
            "notional_usdt": 0.0,
            "margin_used_usdt": 0.0,
            "qty": 0.0,
        }
