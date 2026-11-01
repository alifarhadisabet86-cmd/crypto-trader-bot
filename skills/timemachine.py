"""
مهارت هفتم: شبیه‌ساز مونت‌کارلو (۱۰۰۰ مسیر آینده در افق ۱۶ کندل) (TimeMachine Skill)
Institutional Trading Bot V2 - Monte Carlo & Ornstein-Uhlenbeck Path Simulator
"""

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

from core.config import SCORING_RULES


class TimeMachineSkill:
    """
    کلاس شبیه‌سازی ۱,۰۰۰ مسیر آینده قیمت در افق ۱۶ کندل با ترکیب حرکت براونی هندسی (GBM)،
    شیب فازی (Drift) و فرآیند بازگشت به میانگین Ornstein-Uhlenbeck در بازارهای رنج.
    """

    def __init__(self) -> None:
        self.num_simulations: int = 1000
        self.horizon_candles: int = 16
        self.theta_reversion: float = 0.12
        self.min_winrate_pct: float = float(SCORING_RULES.get("min_timemachine_winrate", 42.0))
        self.min_ev_r: float = float(SCORING_RULES.get("min_timemachine_ev_r", 0.05))

    def run_simulation(
        self,
        df_15m: pd.DataFrame,
        exit_plan: Dict[str, Any],
        confluence_score: float,
        regime_data: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        اجرای ۱,۰۰۰ شبیه‌سازی مونت‌کارلو برای ارزیابی احتمال برد و امید ریاضی (EV) ستاپ.
        """
        side = str(exit_plan.get("side", "LONG")).strip().upper()
        entry = float(exit_plan.get("entry_price", 0.0))
        stop_loss = float(exit_plan.get("stop_loss", 0.0))
        tp1 = float(exit_plan.get("tp1_breakeven", 0.0))
        tp2 = float(exit_plan.get("tp2_final", 0.0))
        rr_tp1 = float(exit_plan.get("rr_tp1", 1.15))
        rr_tp2 = float(exit_plan.get("rr_tp2", 2.0))

        sl_dist = abs(entry - stop_loss)
        if entry <= 0.0 or sl_dist <= 1e-12:
            return {
                "approved": False,
                "win_rate_pct": 0.0,
                "expected_value_r": -1.0,
                "tp1_hit_rate_pct": 0.0,
                "tp2_hit_rate_pct": 0.0,
                "sl_hit_rate_pct": 100.0,
                "simulations": self.num_simulations,
                "horizon_candles": self.horizon_candles,
                "details": "Invalid entry or stop_loss distance for simulation",
            }

        # ۱. محاسبه نوسان تاریخی (sigma) از کندل‌های ۱۵ دقیقه
        sigma = 0.0045
        mean_equilibrium = entry
        if df_15m is not None and len(df_15m) >= 10:
            closes = df_15m["close"].astype(float)
            returns = closes.pct_change().dropna()
            if len(returns) >= 5:
                calc_std = float(returns.tail(40).std())
                if not np.isnan(calc_std) and calc_std > 0:
                    sigma = float(np.clip(calc_std, 0.0015, 0.035))
            mean_equilibrium = float(closes.tail(40).mean())

        # تنظیم مقیاس گام نوسان متناسب با فاصله استاپ تا شبیه‌سازی واقع‌گرایانه باشد
        step_vol = max(sigma * entry, sl_dist * 0.28)

        # ۲. محاسبه شیب حرکتی (drift) بر اساس امتیاز فازی و رژیم بازار
        regime_name = str((regime_data or {}).get("regime", "RANGING")).upper()
        direction = 1.0 if side == "LONG" else -1.0
        score_edge = max(0.0, (float(confluence_score) - 50.0) / 50.0)
        base_drift_per_step = direction * (0.085 * score_edge) * sl_dist

        # در بازار RANGING هدف بازگشت قیمت در جهت معامله به سمت تارگت اول/میانگین است
        is_ranging = regime_name == "RANGING"
        reversion_anchor = tp1 if is_ranging else mean_equilibrium

        rng = np.random.default_rng(seed)
        shocks = rng.normal(loc=0.0, scale=step_vol, size=(self.num_simulations, self.horizon_candles))

        r_outcomes = np.zeros(self.num_simulations, dtype=float)
        tp1_hits = 0
        tp2_hits = 0
        sl_hits = 0

        # ۳. اجرای شبیه‌سازی ۱,۰۰۰ مسیر در افق ۱۶ کندل
        for sim_idx in range(self.num_simulations):
            price = entry
            hit_tp1 = False
            resolved = False
            realized_r = 0.0

            for step in range(self.horizon_candles):
                ou_pull = 0.0
                if is_ranging:
                    ou_pull = self.theta_reversion * (reversion_anchor - price) * 0.25

                price = price + base_drift_per_step + ou_pull + shocks[sim_idx, step]

                if side == "LONG":
                    if not hit_tp1:
                        if price <= stop_loss:
                            realized_r = -1.0
                            sl_hits += 1
                            resolved = True
                            break
                        if price >= tp1:
                            hit_tp1 = True
                            tp1_hits += 1
                            if price >= tp2:
                                realized_r = (0.5 * rr_tp1) + (0.5 * rr_tp2)
                                tp2_hits += 1
                                resolved = True
                                break
                    else:
                        # پس از رسیدن به TP1، استاپ در نقطه ورود (Risk-Free) قرار دارد
                        if price <= entry:
                            realized_r = 0.5 * rr_tp1
                            resolved = True
                            break
                        if price >= tp2:
                            realized_r = (0.5 * rr_tp1) + (0.5 * rr_tp2)
                            tp2_hits += 1
                            resolved = True
                            break
                else:  # SHORT
                    if not hit_tp1:
                        if price >= stop_loss:
                            realized_r = -1.0
                            sl_hits += 1
                            resolved = True
                            break
                        if price <= tp1:
                            hit_tp1 = True
                            tp1_hits += 1
                            if price <= tp2:
                                realized_r = (0.5 * rr_tp1) + (0.5 * rr_tp2)
                                tp2_hits += 1
                                resolved = True
                                break
                    else:
                        if price >= entry:
                            realized_r = 0.5 * rr_tp1
                            resolved = True
                            break
                        if price <= tp2:
                            realized_r = (0.5 * rr_tp1) + (0.5 * rr_tp2)
                            tp2_hits += 1
                            resolved = True
                            break

            # اگر در پایان ۱۶ کندل هنوز بسته نشده باشد، محاسبه ارزش لحظه‌ای (Mark-to-Market)
            if not resolved:
                floating_r = ((price - entry) / sl_dist) if side == "LONG" else ((entry - price) / sl_dist)
                floating_r = float(np.clip(floating_r, -1.0, rr_tp2))
                if hit_tp1:
                    realized_r = (0.5 * rr_tp1) + (0.5 * max(0.0, floating_r))
                else:
                    realized_r = floating_r

            r_outcomes[sim_idx] = realized_r

        # ۴. استخراج آمار نهایی و بررسی شرط تایید
        wins_count = int(np.sum(r_outcomes > 0.0))
        win_rate_pct = round((wins_count / self.num_simulations) * 100.0, 2)
        expected_value_r = round(float(np.mean(r_outcomes)), 3)
        tp1_rate = round((tp1_hits / self.num_simulations) * 100.0, 2)
        tp2_rate = round((tp2_hits / self.num_simulations) * 100.0, 2)
        sl_rate = round((sl_hits / self.num_simulations) * 100.0, 2)

        approved = (win_rate_pct >= self.min_winrate_pct) and (expected_value_r > self.min_ev_r)

        return {
            "approved": bool(approved),
            "win_rate_pct": win_rate_pct,
            "expected_value_r": expected_value_r,
            "tp1_hit_rate_pct": tp1_rate,
            "tp2_hit_rate_pct": tp2_rate,
            "sl_hit_rate_pct": sl_rate,
            "simulations": self.num_simulations,
            "horizon_candles": self.horizon_candles,
            "details": (
                f"MC 1000 Paths: WinRate {win_rate_pct:.1f}% (Min {self.min_winrate_pct}%), "
                f"EV {expected_value_r:+.2f}R (Min +{self.min_ev_r}R)"
            ),
        }