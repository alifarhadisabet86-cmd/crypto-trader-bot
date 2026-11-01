"""
مهارت یازدهم (نسخه V2.5): یادگیری ماشین بیزی (Soft Bayesian Tuning) و ارزیابی رادار سایه
Institutional Trading Bot V2.5 - Bayesian ML Feedback & Shadow Shield Evaluator
"""

from datetime import datetime, timezone
from typing import Dict, Any, List
import uuid

import numpy as np
import pandas as pd

from core.config import WATCHLIST, DEFAULT_REGIME_WEIGHTS, DEFAULT_COIN_MULTIPLIERS


class MLFeedbackSkill:
    """
    کلاس یادگیری ماشین سبک (Bayesian Beta-Binomial Updating) و مدیریت پورتفوی سایه:
    1. ثبت سیگنال‌های فیلترشده در رادار سایه (record_filtered_signal)
    2. ارزیابی کندل‌به‌کندل سیگنال‌های ردشده برای سنجش دقت سپر محافظتی (evaluate_active_shadows)
    3. تنظیم خودکار ضرایب ۵ دارایی [0.80, 1.15] و ضرایب رژیم‌ها [0.85, 1.12]
    """

    def __init__(self, prior_alpha: float = 4.0, prior_beta: float = 4.0) -> None:
        self.prior_alpha: float = prior_alpha
        self.prior_beta: float = prior_beta

    @staticmethod
    def _now_utc_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ==========================================================================
    # ۱. ثبت سیگنال فیلترشده در رادار سایه (Shadow Shield Recorder)
    # ==========================================================================
    def record_filtered_signal(
        self,
        shadow_portfolio: Dict[str, Any],
        coin: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        tp_price: float,
        filter_reason: str = "LOW_CONFLUENCE_SCORE",
        confluence_score: float = 0.0,
    ) -> Dict[str, Any]:
        """
        وقتی سیگنالی توسط فیلتر اخبار اقتصادی، امتیاز فازی، ماشین زمان، نگهبان ریسک
        یا گارد اسپرد رد می‌شود، در رادار سایه ثبت می‌گردد تا نتیجه واقعی آن رصد شود.
        """
        shadow_id = f"SHD-{coin.upper()}-{uuid.uuid4().hex[:6].upper()}"
        record = {
            "id": shadow_id,
            "coin": str(coin).upper(),
            "side": str(side).upper(),
            "entry_price": round(float(entry_price), 6),
            "stop_loss": round(float(stop_loss), 6),
            "tp_price": round(float(tp_price), 6),
            "filter_reason": str(filter_reason),
            "confluence_score": round(float(confluence_score), 2),
            "status": "ACTIVE",
            "created_at": self._now_utc_iso(),
        }

        active_list: List[Dict[str, Any]] = shadow_portfolio.setdefault("active_shadows", [])
        active_list.append(record)
        # نگهداری حداکثر ۱۰۰ سیگنال فعال اخیر در حافظه
        if len(active_list) > 100:
            shadow_portfolio["active_shadows"] = active_list[-100:]

        # بروزرسانی شمارنده‌های تفکیکی دلایل فیلتر
        breakdown = shadow_portfolio.setdefault("filter_breakdown", {})
        breakdown[filter_reason] = int(breakdown.get(filter_reason, 0)) + 1

        stats = shadow_portfolio.setdefault("stats", {})
        stats["total_filtered"] = int(stats.get("total_filtered", 0)) + 1

        return record

    # Alias برای سازگاری با نام‌های قدیمی در صورت فراخوانی
    def add_shadow_signal(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.record_filtered_signal(*args, **kwargs)

    # ==========================================================================
    # ۲. ارزیابی سیگنال‌های فعال در رادار سایه با کندل‌های جدید ۱۵ دقیقه
    # ==========================================================================
    def evaluate_active_shadows(
        self,
        shadow_portfolio: Dict[str, Any],
        market_data_15m: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        """
        بررسی اینکه سیگنال‌های فیلترشده به استاپ خورده‌اند (نجات از ضرر توسط سپر)
        یا به تارگت رسیده‌اند (فرصت ازدست‌رفته).
        """
        active_list: List[Dict[str, Any]] = shadow_portfolio.get("active_shadows", [])
        if not active_list:
            return {"resolved_now": 0}

        still_active: List[Dict[str, Any]] = []
        resolved_list: List[Dict[str, Any]] = shadow_portfolio.setdefault("resolved_shadows", [])
        stats = shadow_portfolio.setdefault("stats", {})
        resolved_now = 0

        for shd in active_list:
            coin = shd.get("coin", "BTC")
            df = market_data_15m.get(coin)
            if df is None or df.empty:
                still_active.append(shd)
                continue

            last_row = df.iloc[-1]
            c_high = float(last_row["high"])
            c_low = float(last_row["low"])
            side = shd.get("side", "LONG")
            sl = float(shd.get("stop_loss", 0.0))
            tp = float(shd.get("tp_price", 0.0))

            sl_hit = (side == "LONG" and c_low <= sl) or (side == "SHORT" and c_high >= sl)
            tp_hit = (side == "LONG" and c_high >= tp) or (side == "SHORT" and c_low <= tp)

            if sl_hit:
                shd["status"] = "SAVED_FROM_LOSS"
                shd["resolved_at"] = self._now_utc_iso()
                resolved_list.append(shd)
                stats["evaluated_count"] = int(stats.get("evaluated_count", 0)) + 1
                stats["saved_from_loss"] = int(stats.get("saved_from_loss", 0)) + 1
                resolved_now += 1
            elif tp_hit:
                shd["status"] = "MISSED_WINNER"
                shd["resolved_at"] = self._now_utc_iso()
                resolved_list.append(shd)
                stats["evaluated_count"] = int(stats.get("evaluated_count", 0)) + 1
                stats["missed_winners"] = int(stats.get("missed_winners", 0)) + 1
                resolved_now += 1
            else:
                still_active.append(shd)

        shadow_portfolio["active_shadows"] = still_active
        if len(resolved_list) > 200:
            shadow_portfolio["resolved_shadows"] = resolved_list[-200:]

        eval_cnt = int(stats.get("evaluated_count", 0))
        saved_cnt = int(stats.get("saved_from_loss", 0))
        if eval_cnt > 0:
            stats["shield_accuracy"] = round((saved_cnt / eval_cnt) * 100.0, 2)

        return {"resolved_now": resolved_now, "shield_accuracy": stats.get("shield_accuracy", 0.0)}

    # ==========================================================================
    # ۳. بروزرسانی نرم بیزی ضرایب دارایی‌ها و رژیم‌ها (Bayesian Soft Updating)
    # ==========================================================================
    def update_strategy_memory(
        self,
        strategy_memory: Dict[str, Any],
        closed_trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        تحلیل ۲۰ معامله آخر هر ارز و ۲۵ معامله آخر هر رژیم برای تنظیم ضرایب:
        - coin_multipliers در بازه [0.80, 1.15]
        - regime_multipliers در بازه [0.85, 1.12]
        """
        coin_mults = strategy_memory.setdefault("coin_multipliers", dict(DEFAULT_COIN_MULTIPLIERS))
        regime_mults = strategy_memory.setdefault("regime_multipliers", dict(DEFAULT_REGIME_WEIGHTS))
        coin_stats = strategy_memory.setdefault("coin_stats", {})

        for coin in WATCHLIST.keys():
            c_trades = [t for t in closed_trades if str(t.get("coin", "")).upper() == coin][-20:]
            n_tr = len(c_trades)
            if n_tr == 0:
                coin_mults[coin] = 1.0
                continue

            wins = sum(1 for t in c_trades if float(t.get("net_pnl_usdt", 0.0)) > 0)
            avg_r = float(np.mean([float(t.get("r_multiple", 0.0)) for t in c_trades]))
            post_wr = (wins + self.prior_alpha) / (n_tr + self.prior_alpha + self.prior_beta)

            raw_mult = 1.0 + ((post_wr - 0.50) * 0.50) + (avg_r * 0.05)
            coin_mults[coin] = round(float(np.clip(raw_mult, 0.80, 1.15)), 4)
            coin_stats[coin] = {
                "trades": n_tr,
                "wins": wins,
                "posterior_wr": round(post_wr, 4),
                "avg_r": round(avg_r, 3),
            }

        for reg in ("TRENDING_BULL", "TRENDING_BEAR", "RANGING"):
            r_trades = [t for t in closed_trades if str(t.get("regime", "")) == reg][-25:]
            n_rt = len(r_trades)
            if n_rt == 0:
                regime_mults[reg] = 1.0
                continue

            r_wins = sum(1 for t in r_trades if float(t.get("net_pnl_usdt", 0.0)) > 0)
            post_r_wr = (r_wins + self.prior_alpha) / (n_rt + self.prior_alpha + self.prior_beta)
            raw_r_mult = 1.0 + ((post_r_wr - 0.50) * 0.40)
            regime_mults[reg] = round(float(np.clip(raw_r_mult, 0.85, 1.12)), 4)

        return strategy_memory