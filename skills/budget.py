"""
مهارت نهم: پل سازگاری تخصیص بودجه (ارث‌بری مستقیم از RiskGuardianSkill) (Budget Allocation Skill V2.6 Pro)
Institutional Trading Bot V2.6 Pro - Budget Allocation Compatibility Bridge
"""

from typing import Dict, Any, Optional
from skills.risk_guardian import RiskGuardianSkill


class BudgetAllocationSkill(RiskGuardianSkill):
    """
    کلاس تخصیص بودجه و سایزینگ که مستقیماً از RiskGuardianSkill ارث‌بری می‌کند
    تا سازگاری کامل بین تمام ماژول‌ها و تست‌ها حفظ شود.
    """

    def __init__(self) -> None:
        super().__init__()

    def allocate_budget(
        self,
        portfolio: Dict[str, Any],
        candidate_coin: Optional[str] = None,
        candidate_side: Optional[str] = None,
        confluence_data: Optional[Dict[str, Any]] = None,
        exit_plan: Optional[Dict[str, Any]] = None,
        bot_config: Optional[Dict[str, Any]] = None,
        *,
        coin: Optional[str] = None,
        side: Optional[str] = None,
        unrealized_pnl_usdt: float = 0.0,
    ) -> Dict[str, Any]:
        """متد یکپارچه تخصیص بودجه و بررسی ریسک با پشتیبانی از پارامترهای V2 و V2.6."""
        target_coin = str(coin or candidate_coin or "BTC").upper()
        target_side = str(side or candidate_side or "LONG").upper()
        conf = confluence_data or {}
        ex = exit_plan or {}

        confluence_score = float(conf.get("final_score", conf.get("score", 70.0)))
        size_multiplier = float(conf.get("size_multiplier", 1.0))
        coin_multiplier = float(conf.get("coin_multiplier", 1.0))
        entry_price = float(ex.get("entry_price", 0.0))
        stop_loss = float(ex.get("stop_loss", 0.0))

        return self.evaluate_trade_risk(
            portfolio=portfolio,
            coin=target_coin,
            side=target_side,
            confluence_score=confluence_score,
            entry_price=entry_price,
            stop_loss=stop_loss,
            size_multiplier=size_multiplier,
            bot_config=bot_config,
            unrealized_pnl_usdt=unrealized_pnl_usdt,
            coin_multiplier=coin_multiplier,
        )
