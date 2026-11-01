"""
مهارت هشتم: نگهبان ریسک، ماتریس ۵ اسلات، سپر همبستگی و سایزینگ پویا (Risk Guardian Skill)
Institutional Trading Bot V2 - Portfolio Risk Guardian & Position Sizing Engine
"""

from typing import Dict, Any, Optional

from core.config import RISK_RULES
from core.slot_manager import can_open_new_position


class RiskGuardianSkill:
    """
    کلاس کنترل مدارشکن روزانه (۲٪)، ماتریس ۵ اسلات هوشمند، سپر همبستگی
    و محاسبه حجم دقیق پوزیشن بر اساس دور برد/باخت و سقف مارجین ۲۵٪.
    """

    def __init__(self) -> None:
        self.base_risk_pct: float = float(RISK_RULES.get("base_risk_per_trade_pct", 0.5))
        self.win_streak_risk_pct: float = float(RISK_RULES.get("winning_streak_risk_pct", 0.8))
        self.loss_streak_risk_pct: float = float(RISK_RULES.get("losing_streak_risk_pct", 0.25))
        self.max_daily_dd_pct: float = float(RISK_RULES.get("max_daily_drawdown_pct", 2.0))
        self.max_leverage: int = int(RISK_RULES.get("max_leverage", 10))
        self.max_margin_pct: float = float(RISK_RULES.get("max_margin_per_trade_pct", 25.0))

    def check_circuit_breaker(self, portfolio: Dict[str, Any]) -> Dict[str, Any]:
        """
        بررسی وضعیت مدارشکن روزانه (Daily Circuit Breaker) بر اساس ۲٪ افت از موجودی اول روز.
        """
        day_start_eq = float(portfolio.get("day_start_equity", 1000.0))
        daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        already_tripped = bool(portfolio.get("daily_circuit_breaker", False))

        dd_pct = 0.0
        if day_start_eq > 0 and daily_pnl < 0:
            dd_pct = round((abs(daily_pnl) / day_start_eq) * 100.0, 2)

        tripped = already_tripped or (dd_pct >= self.max_daily_dd_pct)
        if tripped:
            portfolio["daily_circuit_breaker"] = True

        return {
            "tripped": tripped,
            "daily_drawdown_pct": dd_pct,
            "max_allowed_dd_pct": self.max_daily_dd_pct,
            "daily_pnl_usdt": round(daily_pnl, 4),
            "day_start_equity": round(day_start_eq, 4),
        }

    def _determine_base_risk_pct(
        self,
        portfolio: Dict[str, Any],
        bot_config: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        تعیین درصد ریسک پایه بین 0.25%، 0.50% و 0.80% بر اساس حالت ریسک تلگرام
        و تعداد برد/باخت‌های متوالی پرتفوی.
        """
        cfg = bot_config or {}
        risk_mode = str(cfg.get("risk_mode", "NORMAL")).strip().upper()

        if risk_mode == "CONSERVATIVE":
            return self.loss_streak_risk_pct
        if risk_mode == "AGGRESSIVE":
            return self.win_streak_risk_pct

        cons_wins = int(portfolio.get("consecutive_wins", 0))
        cons_losses = int(portfolio.get("consecutive_losses", 0))

        if cons_losses >= 2:
            return self.loss_streak_risk_pct
        if cons_wins >= 2:
            return self.win_streak_risk_pct
        return self.base_risk_pct

    def evaluate_risk_and_size(
        self,
        portfolio: Dict[str, Any],
        candidate_coin: str,
        candidate_side: str,
        confluence_data: Dict[str, Any],
        exit_plan: Dict[str, Any],
        bot_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        بررسی تمام قوانین نگهبان ریسک (توقف ربات، مدارشکن روزانه، ماتریس ۵ اسلات و سپر همبستگی)
        و محاسبه حجم دقیق پوزیشن، ریسک دلاری و مارجین مورد نیاز.
        """
        cfg = bot_config or {}

        # ۱. بررسی وضعیت Panic یا Pause از سمت اتاق فرمان تلگرام
        if bool(cfg.get("panic_mode", False)):
            return {
                "approved": False,
                "reason": "PANIC_MODE_ACTIVE",
                "details": "Bot is locked in PANIC MODE. Use /resume in Telegram to unlock.",
            }
        if bool(cfg.get("is_paused", False)):
            return {
                "approved": False,
                "reason": "BOT_PAUSED",
                "details": "Trading is paused via Telegram command (/pause).",
            }

        # ۲. بررسی مدارشکن روزانه (Daily Circuit Breaker)
        cb_status = self.check_circuit_breaker(portfolio)
        if cb_status["tripped"]:
            return {
                "approved": False,
                "reason": "DAILY_CIRCUIT_BREAKER",
                "details": (
                    f"Daily circuit breaker tripped: Drawdown {cb_status['daily_drawdown_pct']:.2f}% "
                    f">= {self.max_daily_dd_pct:.2f}% limit."
                ),
            }

        # ۳. بررسی ماتریس ۵ اسلات هوشمند و سپر همبستگی (Correlation Shield)
        open_positions = portfolio.get("open_positions", [])
        final_score = float(confluence_data.get("final_score", 0.0))
        size_multiplier = float(confluence_data.get("size_multiplier", 0.0))

        if size_multiplier <= 0.0 or final_score < 65.0:
            return {
                "approved": False,
                "reason": "LOW_CONFLUENCE_SCORE",
                "details": f"Confluence score {final_score:.1f} below minimum threshold (65.0).",
            }

        slot_check = can_open_new_position(
            open_positions=open_positions,
            candidate_coin=candidate_coin,
            candidate_side=candidate_side,
            candidate_score=final_score,
        )
        if not slot_check["allowed"]:
            return {
                "approved": False,
                "reason": slot_check["reason"],
                "details": slot_check["details"],
                "slot_metrics": slot_check.get("slot_metrics", {}),
            }

        # ۴. محاسبه سایز پوزیشن، ارزش اسمی (Notional) و کنترل سقف مارجین ۲۵٪
        balance = float(portfolio.get("balance_usdt", 1000.0))
        entry_price = float(exit_plan.get("entry_price", 0.0))
        stop_loss = float(exit_plan.get("stop_loss", 0.0))
        sl_dist = abs(entry_price - stop_loss)

        if balance <= 10.0 or entry_price <= 0.0 or sl_dist <= 1e-12:
            return {
                "approved": False,
                "reason": "INVALID_PRICING_OR_BALANCE",
                "details": "Insufficient balance or invalid stop-loss distance.",
            }

        base_risk_pct = self._determine_base_risk_pct(portfolio, cfg)
        effective_risk_pct = round(base_risk_pct * size_multiplier, 4)
        risk_amount_usdt = (balance * effective_risk_pct) / 100.0

        # حجم اولیه بر اساس فاصله استاپ
        raw_quantity = risk_amount_usdt / sl_dist
        notional_usdt = raw_quantity * entry_price
        margin_required_usdt = notional_usdt / float(self.max_leverage)

        # محدود کردن مارجین هر معامله به حداکثر ۲۵٪ کل موجودی حساب
        max_margin_allowed = balance * (self.max_margin_pct / 100.0)
        margin_capped = False
        if margin_required_usdt > max_margin_allowed:
            margin_required_usdt = max_margin_allowed
            notional_usdt = margin_required_usdt * float(self.max_leverage)
            raw_quantity = notional_usdt / entry_price
            risk_amount_usdt = raw_quantity * sl_dist
            effective_risk_pct = round((risk_amount_usdt / balance) * 100.0, 4)
            margin_capped = True

        return {
            "approved": True,
            "reason": "RISK_APPROVED",
            "slot_type": slot_check.get("slot_type", "STANDARD_SLOT"),
            "slot_metrics": slot_check.get("slot_metrics", {}),
            "base_risk_pct": base_risk_pct,
            "size_multiplier": size_multiplier,
            "effective_risk_pct": effective_risk_pct,
            "risk_amount_usdt": round(risk_amount_usdt, 4),
            "quantity": round(raw_quantity, 6),
            "notional_usdt": round(notional_usdt, 4),
            "margin_used_usdt": round(margin_required_usdt, 4),
            "leverage": self.max_leverage,
            "margin_capped": margin_capped,
            "details": (
                f"Risk Approved: {effective_risk_pct:.3f}% (${risk_amount_usdt:.2f}) | "
                f"Margin: ${margin_required_usdt:.2f} ({self.max_leverage}x)"
            ),
        }