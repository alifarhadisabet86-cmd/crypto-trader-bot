"""
مهارت نهم: پل سازگاری تخصیص بودجه (ارث‌بری مستقیم از RiskGuardianSkill) (Budget Allocation Skill)
Institutional Trading Bot V2 - Budget Allocation Compatibility Bridge
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
        candidate_coin: str,
        candidate_side: str,
        confluence_data: Dict[str, Any],
        exit_plan: Dict[str, Any],
        bot_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """متد معادل evaluate_risk_and_size برای سازگاری کامل فراخوانی‌ها."""
        return self.evaluate_risk_and_size(
            portfolio=portfolio,
            candidate_coin=candidate_coin,
            candidate_side=candidate_side,
            confluence_data=confluence_data,
            exit_plan=exit_plan,
            bot_config=bot_config,
        )