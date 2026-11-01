"""
مهارت یازدهم: یادگیری ماشین تطبیقی بیزی و ارزیابی معاملات فیلترشده سایه (ML Feedback Skill)
Institutional Trading Bot V2 - Adaptive Bayesian Weighting & Shadow Shield Evaluator
"""

from datetime import datetime, timezone
from typing import Dict, Any, List
import numpy as np
import pandas as pd

from core.config import WATCHLIST, DEFAULT_REGIME_WEIGHTS, DEFAULT_COIN_MULTIPLIERS


class MLFeedbackSkill:
    """
    کلاس یادگیری ماشین تطبیقی بیزی برای تنظیم خودکار ضرایب ارزها در بازه [0.80, 1.15]
    و وزن رژیم‌های بازار در بازه [0.85, 1.12]، به همراه ارزیابی دقت سپر در رادار سایه.
    """

    def __init__(self) -> None:
        self.coin_lookback: int = 20
        self.regime_lookback: int = 25
        self.coin_bounds: tuple[float, float] = (0.80, 1.15)
        self.regime_bounds: tuple[float, float] = (0.85, 1.12)
        self.prior_strength: float = 6.0  # قدرت پیشین بیزی برای جلوگیری از نوسان شدید در تعداد معاملات کم
        self.baseline_winrate: float = 0.50

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _compute_bayesian_multiplier(
        self,
        trades: List[Dict[str, Any]],
        current_weight: float,
        min_bound: float,
        max_bound: float,
    ) -> float:
        """
        محاسبه ضریب بیزی نرم بر اساس وین‌ریت پسین (Posterior Win-Rate) و میانگین R کسب‌شده.
        """
        if not trades:
            return float(np.clip(current_weight, min_bound, max_bound))

        n = len(trades)
        wins = sum(
            1
            for t in trades
            if str(t.get("result", "")).upper() == "WIN" or float(t.get("pnl_usdt", 0.0)) > 0.0
        )
        r_values = [float(t.get("realized_r", 0.0)) for t in trades]
        avg_r = float(np.mean(r_values)) if r_values else 0.0

        # به‌روزرسانی بیزی (Beta-Binomial Posterior)
        alpha_prior = self.prior_strength * self.baseline_winrate
        beta_prior = self.prior_strength * (1.0 - self.baseline_winrate)
        posterior_wr = (wins + alpha_prior) / (n + alpha_prior + beta_prior)

        # ترکیب انحراف وین‌ریت از ۵۰٪ و میانگین R کسب‌شده
        wr_delta = (posterior_wr - self.baseline_winrate) * 0.55
        r_delta = np.clip(avg_r, -1.0, 1.5) * 0.06
        target_mult = 1.0 + wr_delta + r_delta

        # میانگین متحرک نمایی نرم (Soft Update) با وزن قبلی
        blended = (0.35 * current_weight) + (0.65 * target_mult)
        return float(round(np.clip(blended, min_bound, max_bound), 4))

    def update_strategy_weights(
        self,
        portfolio: Dict[str, Any],
        strategy_memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        بررسی ۲۰ معامله آخر هر ارز و ۲۵ معامله آخر هر رژیم از trade_history پرتفوی
        و به‌روزرسانی ضرایب در strategy_memory.json.
        """
        history: List[Dict[str, Any]] = portfolio.get("trade_history", [])

        coin_mults = dict(DEFAULT_COIN_MULTIPLIERS)
        coin_mults.update(strategy_memory.get("coin_multipliers", {}))

        regime_weights = dict(DEFAULT_REGIME_WEIGHTS)
        regime_weights.update(strategy_memory.get("regime_weights", {}))

        # ۱. به‌روزرسانی ضریب هر ارز (۲۰ معامله آخر آن ارز) در بازه [0.80, 1.15]
        for coin_key in WATCHLIST.keys():
            coin_trades = [
                t for t in history if str(t.get("coin", "")).upper() == coin_key
            ][-self.coin_lookback :]

            if coin_trades:
                curr_w = float(coin_mults.get(coin_key, 1.0))
                coin_mults[coin_key] = self._compute_bayesian_multiplier(
                    trades=coin_trades,
                    current_weight=curr_w,
                    min_bound=self.coin_bounds[0],
                    max_bound=self.coin_bounds[1],
                )
            else:
                coin_mults[coin_key] = float(
                    np.clip(float(coin_mults.get(coin_key, 1.0)), *self.coin_bounds)
                )

        # ۲. به‌روزرسانی وزن هر رژیم بازار (۲۵ معامله آخر آن رژیم) در بازه [0.85, 1.12]
        for reg_key in DEFAULT_REGIME_WEIGHTS.keys():
            reg_trades = [
                t for t in history if str(t.get("regime", "")).upper() == reg_key
            ][-self.regime_lookback :]

            if reg_trades:
                curr_rw = float(regime_weights.get(reg_key, 1.0))
                regime_weights[reg_key] = self._compute_bayesian_multiplier(
                    trades=reg_trades,
                    current_weight=curr_rw,
                    min_bound=self.regime_bounds[0],
                    max_bound=self.regime_bounds[1],
                )
            else:
                regime_weights[reg_key] = float(
                    np.clip(float(regime_weights.get(reg_key, 1.0)), *self.regime_bounds)
                )

        strategy_memory["coin_multipliers"] = coin_mults
        strategy_memory["regime_weights"] = regime_weights
        strategy_memory["total_feedback_cycles"] = (
            int(strategy_memory.get("total_feedback_cycles", 0)) + 1
        )
        strategy_memory["last_updated"] = self._utc_now_iso()

        return strategy_memory

    def evaluate_active_shadows(
        self,
        shadow_portfolio: Dict[str, Any],
        market_data_5m: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        """
        بررسی سیگنال‌های ردشده در shadow_portfolio.json با کندل‌های ۵ دقیقه بازار:
        - اگر سیگنال ردشده به استاپ‌لاس برسد -> saved_from_loss += 1
        - اگر سیگنال ردشده به تارگت برسد -> missed_winners += 1
        - محاسبه درصدی shield_accuracy.
        """
        active_shadows: List[Dict[str, Any]] = shadow_portfolio.get("active_shadows", [])
        if "resolved_shadows" not in shadow_portfolio or not isinstance(
            shadow_portfolio["resolved_shadows"], list
        ):
            shadow_portfolio["resolved_shadows"] = []

        if "stats" not in shadow_portfolio or not isinstance(shadow_portfolio["stats"], dict):
            shadow_portfolio["stats"] = {
                "total_filtered": len(active_shadows),
                "saved_from_loss": 0,
                "missed_winners": 0,
                "shield_accuracy": 100.0,
            }

        still_active: List[Dict[str, Any]] = []
        newly_resolved: List[Dict[str, Any]] = []
        now_iso = self._utc_now_iso()

        for shd in active_shadows:
            coin = str(shd.get("coin", ""))
            df_5m = market_data_5m.get(coin)
            if df_5m is None or (isinstance(df_5m, pd.DataFrame) and df_5m.empty):
                still_active.append(shd)
                continue

            recent_bars = df_5m.tail(3)
            bar_high = float(recent_bars["high"].astype(float).max())
            bar_low = float(recent_bars["low"].astype(float).min())

            side = str(shd.get("side", "LONG")).upper()
            sl = float(shd.get("stop_loss", 0.0))
            tp1 = float(shd.get("tp1_price", 0.0))
            tp2 = float(shd.get("tp2_price", 0.0))
            target_level = tp1 if tp1 > 0.0 else tp2

            sl_hit = (side == "LONG" and bar_low <= sl) or (side == "SHORT" and bar_high >= sl)
            tp_hit = (side == "LONG" and bar_high >= target_level) or (
                side == "SHORT" and bar_low <= target_level
            )

            if sl_hit:
                shd["outcome"] = "SHIELD_SAVED_LOSS"
                shd["resolved_at"] = now_iso
                shadow_portfolio["resolved_shadows"].append(shd)
                newly_resolved.append(shd)
                shadow_portfolio["stats"]["saved_from_loss"] = (
                    int(shadow_portfolio["stats"].get("saved_from_loss", 0)) + 1
                )
            elif tp_hit:
                shd["outcome"] = "MISSED_OPPORTUNITY"
                shd["resolved_at"] = now_iso
                shadow_portfolio["resolved_shadows"].append(shd)
                newly_resolved.append(shd)
                shadow_portfolio["stats"]["missed_winners"] = (
                    int(shadow_portfolio["stats"].get("missed_winners", 0)) + 1
                )
            else:
                still_active.append(shd)

        # نگه داشتن حداکثر ۱۰۰ رکورد آخر در resolved_shadows برای سبک ماندن فایل JSON
        shadow_portfolio["active_shadows"] = still_active
        shadow_portfolio["resolved_shadows"] = shadow_portfolio["resolved_shadows"][-100:]

        saved = int(shadow_portfolio["stats"].get("saved_from_loss", 0))
        missed = int(shadow_portfolio["stats"].get("missed_winners", 0))
        total_eval = saved + missed

        if total_eval > 0:
            accuracy = round((saved / total_eval) * 100.0, 2)
        else:
            accuracy = 100.0

        shadow_portfolio["stats"]["shield_accuracy"] = accuracy
        shadow_portfolio["last_updated"] = now_iso

        return {
            "resolved_count": len(newly_resolved),
            "active_count": len(still_active),
            "saved_from_loss": saved,
            "missed_winners": missed,
            "shield_accuracy": accuracy,
        }