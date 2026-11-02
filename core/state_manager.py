"""
مدیریت حافظه پایدار، دروازه ۵۰ معامله کاغذی و ریست روزانه/هفتگی (State Manager V2.5)
Institutional Trading Bot V2.5 - Atomic JSON State Persistence & V2->V2.5 Schema Migration
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.config import STATE_DIR, RISK_CONFIG, WATCHLIST


class StateManager:
    """
    مدیریت اتمیک و ضدکرش ۸ فایل JSON در پوشه state/ به همراه بررسی
    دروازه ۵۰ معامله کاغذی (Paper Gate)، ریست خودکار مدارشکن روزانه و هفتگی
    و مهاجرت خودکار ساختارهای قدیمی V2.0 به V2.5.
    """

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self.state_dir: Path = state_dir if state_dir else STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.files: Dict[str, Path] = {
            "portfolio": self.state_dir / "paper_portfolio.json",
            "bot_config": self.state_dir / "bot_config.json",
            "strategy_memory": self.state_dir / "strategy_memory.json",
            "shadow_portfolio": self.state_dir / "shadow_portfolio.json",
            "shadow_trades": self.state_dir / "shadow_trades.json",
            "active_setups": self.state_dir / "active_setups.json",
            "market_regime": self.state_dir / "market_regime.json",
            "risk_status": self.state_dir / "risk_status.json",
        }
        self.ensure_all_state_files()

    @staticmethod
    def _now_utc_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _today_utc_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _current_week_str() -> str:
        now = datetime.now(timezone.utc)
        iso_year, iso_week, _ = now.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"

    # ==========================================================================
    # ساختارهای پیش‌فرض (Default Schemas V2.5)
    # ==========================================================================
    def get_default_portfolio(self) -> Dict[str, Any]:
        init_bal = float(RISK_CONFIG["INITIAL_BALANCE_USDT"])
        today = self._today_utc_str()
        curr_week = self._current_week_str()
        now_iso = self._now_utc_iso()

        return {
            "trading_mode": "PAPER",  # تا تکمیل ۵۰ معامله کاغذی روی PAPER قفل است
            "paper_gate_target": int(RISK_CONFIG.get("PAPER_GATE_TARGET_TRADES", 50)),
            "paper_gate_unlocked": False,
            "initial_balance_usdt": init_bal,
            "balance_usdt": init_bal,
            "daily_start_balance_usdt": init_bal,
            "daily_pnl_usdt": 0.0,
            "daily_circuit_breaker": False,
            "last_reset_date": today,
            "weekly_start_balance_usdt": init_bal,
            "weekly_pnl_usdt": 0.0,
            "weekly_circuit_breaker": False,
            "last_reset_week": curr_week,
            "open_positions": [],
            "closed_trades": [],
            "equity_curve": [
                {"timestamp": now_iso, "equity": init_bal, "event": "INITIAL"}
            ],
            "stats": {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "consecutive_wins": 0,
                "consecutive_losses": 0,
                "peak_equity_usdt": init_bal,
                "max_drawdown_pct": 0.0,
                "total_fees_paid_usdt": 0.0,
            },
            "updated_at": now_iso,
        }

    def get_default_bot_config(self) -> Dict[str, Any]:
        return {
            "is_paused": False,
            "panic_mode": False,
            "risk_mode": "NORMAL",
            "execution_mode": "PAPER",
            "last_update_id": 0,
            "last_daily_report_date": "",
            "last_weekly_report_week": "",
            "updated_at": self._now_utc_iso(),
        }

    def get_default_strategy_memory(self) -> Dict[str, Any]:
        return {
            "coin_multipliers": {coin: 1.0 for coin in WATCHLIST.keys()},
            "regime_multipliers": {
                "TRENDING_BULL": 1.0,
                "TRENDING_BEAR": 1.0,
                "RANGING": 1.0,
            },
            "coin_stats": {
                coin: {"trades": 0, "wins": 0, "posterior_wr": 0.50, "avg_r": 0.0}
                for coin in WATCHLIST.keys()
            },
            "updated_at": self._now_utc_iso(),
        }

    def get_default_shadow_portfolio(self) -> Dict[str, Any]:
        return {
            "active_shadows": [],
            "resolved_shadows": [],
            "filter_breakdown": {
                "LOW_CONFLUENCE_SCORE": 0,
                "TIMEMACHINE_REJECTED": 0,
                "RISK_GUARDIAN_BLOCKED": 0,
                "SPREAD_GUARD_5PCT_BLOCKED": 0,
                "ECONOMIC_NEWS_BLOCKED": 0,
            },
            "stats": {
                "total_filtered": 0,
                "evaluated_count": 0,
                "saved_from_loss": 0,
                "missed_winners": 0,
                "shield_accuracy": 0.0,
            },
            "updated_at": self._now_utc_iso(),
        }

    def ensure_all_state_files(self) -> None:
        defaults: Dict[str, Any] = {
            "portfolio": self.get_default_portfolio(),
            "bot_config": self.get_default_bot_config(),
            "strategy_memory": self.get_default_strategy_memory(),
            "shadow_portfolio": self.get_default_shadow_portfolio(),
            "shadow_trades": [],
            "active_setups": [],
            "market_regime": {},
            "risk_status": {
                "circuit_breaker": False,
                "weekly_circuit_breaker": False,
                "daily_drawdown_pct": 0.0,
                "weekly_drawdown_pct": 0.0,
                "active_slots": 0,
                "updated_at": self._now_utc_iso(),
            },
        }
        for key, path in self.files.items():
            if not path.is_file():
                self._atomic_write(path, defaults[key])

    # ==========================================================================
    # خواندن و نوشتن اتمیک
    # ==========================================================================
    def _atomic_write(self, file_path: Path, data: Any) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(file_path.parent), prefix=f".{file_path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=2)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, file_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def _safe_read(self, file_path: Path, default_factory: Any) -> Any:
        if not file_path.is_file():
            default_data = default_factory() if callable(default_factory) else default_factory
            self._atomic_write(file_path, default_data)
            return default_data
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            default_data = default_factory() if callable(default_factory) else default_factory
            self._atomic_write(file_path, default_data)
            return default_data

    # ==========================================================================
    # مهاجرت خودکار ساختار پوزیشن‌ها و معاملات از V2.0 به V2.5
    # ==========================================================================
    @staticmethod
    def _normalize_open_position(pos: Dict[str, Any]) -> bool:
        """تضمین وجود تمام کلیدهای استاندارد V2.5 در آبجکت پوزیشن باز."""
        changed = False
        entry = float(pos.get("entry_price", 0.0))

        if "id" not in pos:
            pos["id"] = str(pos.get("position_id", f"POS-{pos.get('coin', 'BTC')}-LEGACY"))
            changed = True
        if "stop_loss" not in pos:
            pos["stop_loss"] = float(pos.get("current_stop_loss", pos.get("initial_stop_loss", entry)))
            changed = True
        if "initial_stop_loss" not in pos:
            pos["initial_stop_loss"] = float(pos["stop_loss"])
            changed = True
        if "stop_distance" not in pos:
            pos["stop_distance"] = round(max(abs(entry - float(pos["initial_stop_loss"])), 1e-8), 6)
            changed = True
        if "current_price" not in pos:
            pos["current_price"] = entry
            changed = True
        if "tp1_breakeven" not in pos:
            pos["tp1_breakeven"] = float(pos.get("tp1_price", entry))
            changed = True
        if "tp2_final" not in pos:
            pos["tp2_final"] = float(pos.get("tp2_price", entry))
            changed = True
        if "initial_qty" not in pos:
            pos["initial_qty"] = float(pos.get("initial_quantity", pos.get("remaining_quantity", 0.0)))
            changed = True
        if "remaining_qty" not in pos:
            pos["remaining_qty"] = float(pos.get("remaining_quantity", pos.get("initial_qty", 0.0)))
            changed = True
        if "initial_notional_usdt" not in pos:
            pos["initial_notional_usdt"] = round(float(pos.get("notional_usdt", pos["initial_qty"] * entry)), 2)
            changed = True
        if "remaining_notional_usdt" not in pos:
            pos["remaining_notional_usdt"] = round(
                float(pos.get("notional_usdt", pos["remaining_qty"] * entry)), 2
            )
            changed = True
        if "initial_risk_usdt" not in pos:
            pos["initial_risk_usdt"] = round(float(pos.get("risk_amount_usdt", 3.75)), 2)
            changed = True
        if "confluence_score" not in pos:
            pos["confluence_score"] = float(pos.get("score", 70.0))
            changed = True
        if "is_risk_free" not in pos:
            pos["is_risk_free"] = bool(pos.get("risk_free", pos.get("tp1_hit", False)))
            changed = True
        if "trailing_active" not in pos:
            pos["trailing_active"] = False
            changed = True
        if "realized_pnl_usdt" not in pos:
            pos["realized_pnl_usdt"] = round(float(pos.get("realized_partial_pnl", 0.0)), 4)
            changed = True
        if "fees_paid_usdt" not in pos:
            pos["fees_paid_usdt"] = round(float(pos.get("entry_fee_usdt", 0.0)), 4)
            changed = True
        if "unrealized_pnl_usdt" not in pos:
            pos["unrealized_pnl_usdt"] = 0.0
            changed = True
        return changed

    @staticmethod
    def _normalize_closed_trade(tr: Dict[str, Any]) -> bool:
        """تضمین وجود تمام کلیدهای استاندارد V2.5 در آبجکت معاملات بسته‌شده."""
        changed = False
        if "id" not in tr:
            tr["id"] = str(tr.get("position_id", f"POS-{tr.get('coin', 'BTC')}-HIST"))
            changed = True
        if "confluence_score" not in tr:
            tr["confluence_score"] = float(tr.get("score", 70.0))
            changed = True
        if "net_pnl_usdt" not in tr:
            tr["net_pnl_usdt"] = round(float(tr.get("pnl_usdt", 0.0)), 2)
            changed = True
        if "r_multiple" not in tr:
            tr["r_multiple"] = round(float(tr.get("realized_r", 0.0)), 2)
            changed = True
        if "outcome" not in tr:
            tr["outcome"] = str(tr.get("result", "WIN" if float(tr["net_pnl_usdt"]) > 0 else "LOSS"))
            changed = True
        if "exit_reason" not in tr:
            tr["exit_reason"] = str(tr.get("close_reason", "STOP_LOSS"))
            changed = True
        if "trailing_active" not in tr:
            tr["trailing_active"] = False
            changed = True
        if "fees_paid_usdt" not in tr:
            tr["fees_paid_usdt"] = 0.0
            changed = True
        return changed

    # ==========================================================================
    # مدیریت پرتفوی، ریست روزانه/هفتگی و دروازه ۵۰ معامله کاغذی
    # ==========================================================================
    def check_and_reset_periods(self, portfolio: Dict[str, Any]) -> Dict[str, Any]:
        """بررسی و ریست خودکار مدارشکن روزانه (در 00:00 UTC) و هفتگی (دوشنبه 00:00 UTC) + مهاجرت V2.5."""
        today = self._today_utc_str()
        curr_week = self._current_week_str()
        current_bal = float(portfolio.get("balance_usdt", RISK_CONFIG["INITIAL_BALANCE_USDT"]))
        changed = False

        # ۱. بررسی ریست روزانه
        if portfolio.get("last_reset_date") != today:
            portfolio["daily_start_balance_usdt"] = current_bal
            portfolio["daily_pnl_usdt"] = 0.0
            portfolio["daily_circuit_breaker"] = False
            portfolio["last_reset_date"] = today
            changed = True

        # ۲. بررسی ریست هفتگی
        if portfolio.get("last_reset_week") != curr_week:
            portfolio["weekly_start_balance_usdt"] = current_bal
            portfolio["weekly_pnl_usdt"] = 0.0
            portfolio["weekly_circuit_breaker"] = False
            portfolio["last_reset_week"] = curr_week
            changed = True

        # ۳. مهاجرت خودکار فیلدهای جدید V2.5 برای فایل‌های قدیمی
        if "trading_mode" not in portfolio:
            portfolio["trading_mode"] = "PAPER"
            changed = True
        if "paper_gate_target" not in portfolio:
            portfolio["paper_gate_target"] = int(RISK_CONFIG.get("PAPER_GATE_TARGET_TRADES", 50))
            changed = True
        if "weekly_start_balance_usdt" not in portfolio:
            portfolio["weekly_start_balance_usdt"] = current_bal
            portfolio["weekly_pnl_usdt"] = 0.0
            portfolio["weekly_circuit_breaker"] = False
            portfolio["last_reset_week"] = curr_week
            changed = True

        # مهاجرت trade_history به closed_trades
        if "closed_trades" not in portfolio:
            portfolio["closed_trades"] = list(portfolio.get("trade_history", []))
            changed = True
        for tr in portfolio.get("closed_trades", []):
            if self._normalize_closed_trade(tr):
                changed = True

        # مهاجرت پوزیشن‌های باز
        for pos in portfolio.get("open_positions", []):
            if self._normalize_open_position(pos):
                changed = True

        # مهاجرت فیلدهای stats
        stats = portfolio.setdefault("stats", {})
        if "consecutive_wins" not in stats:
            stats["consecutive_wins"] = int(portfolio.get("consecutive_wins", 0))
            changed = True
        if "consecutive_losses" not in stats:
            stats["consecutive_losses"] = int(portfolio.get("consecutive_losses", 0))
            changed = True
        if "peak_equity_usdt" not in stats:
            stats["peak_equity_usdt"] = max(float(portfolio.get("initial_balance_usdt", 1000.0)), current_bal)
            changed = True
        if "total_fees_paid_usdt" not in stats:
            stats["total_fees_paid_usdt"] = 0.0
            changed = True

        # ۴. بررسی وضعیت باز شدن دروازه ۵۰ معامله
        total_tr = int(stats.get("total_trades", len(portfolio.get("closed_trades", []))))
        stats["total_trades"] = total_tr
        target_tr = int(portfolio.get("paper_gate_target", 50))
        is_unlocked = total_tr >= target_tr
        if portfolio.get("paper_gate_unlocked") != is_unlocked:
            portfolio["paper_gate_unlocked"] = is_unlocked
            changed = True

        if changed:
            portfolio["updated_at"] = self._now_utc_iso()
            self._atomic_write(self.files["portfolio"], portfolio)

        return portfolio

    @staticmethod
    def get_paper_gate_progress(portfolio: Dict[str, Any]) -> Dict[str, Any]:
        """محاسبه وضعیت پیشرفت دروازه ۵۰ معامله کاغذی برای نمایش در تلگرام."""
        stats = portfolio.get("stats", {})
        total_trades = int(stats.get("total_trades", 0))
        target_trades = int(portfolio.get("paper_gate_target", RISK_CONFIG.get("PAPER_GATE_TARGET_TRADES", 50)))
        win_rate = float(stats.get("win_rate_pct", 0.0))
        remaining = max(0, target_trades - total_trades)
        progress_pct = min(100.0, round((total_trades / max(target_trades, 1)) * 100.0, 1))
        unlocked = total_trades >= target_trades

        # ساخت نوار پیشرفت ۱۰ تایی
        filled = int(round(progress_pct / 10.0))
        bar = "🟦" * filled + "⬜" * (10 - filled)

        return {
            "completed_trades": total_trades,
            "target_trades": target_trades,
            "remaining_trades": remaining,
            "progress_pct": progress_pct,
            "win_rate_pct": win_rate,
            "unlocked": unlocked,
            "bar": bar,
            "mode": str(portfolio.get("trading_mode", "PAPER")),
        }

    def load_portfolio(self) -> Dict[str, Any]:
        pf = self._safe_read(self.files["portfolio"], self.get_default_portfolio)
        return self.check_and_reset_periods(pf)

    def save_portfolio(self, portfolio: Dict[str, Any]) -> None:
        portfolio["updated_at"] = self._now_utc_iso()
        total_tr = int(portfolio.get("stats", {}).get("total_trades", 0))
        target_tr = int(portfolio.get("paper_gate_target", 50))
        portfolio["paper_gate_unlocked"] = total_tr >= target_tr
        self._atomic_write(self.files["portfolio"], portfolio)

    def reset_portfolio(self) -> Dict[str, Any]:
        fresh = self.get_default_portfolio()
        self._atomic_write(self.files["portfolio"], fresh)
        return fresh

    def load_bot_config(self) -> Dict[str, Any]:
        cfg = self._safe_read(self.files["bot_config"], self.get_default_bot_config)
        defaults = self.get_default_bot_config()
        for k, v in defaults.items():
            if k not in cfg:
                cfg[k] = v
        return cfg

    def save_bot_config(self, config: Dict[str, Any]) -> None:
        config["updated_at"] = self._now_utc_iso()
        self._atomic_write(self.files["bot_config"], config)

    def load_strategy_memory(self) -> Dict[str, Any]:
        mem = self._safe_read(self.files["strategy_memory"], self.get_default_strategy_memory)
        defaults = self.get_default_strategy_memory()
        changed = False
        if "regime_multipliers" not in mem:
            mem["regime_multipliers"] = dict(mem.get("regime_weights", defaults["regime_multipliers"]))
            changed = True
        if "coin_multipliers" not in mem:
            mem["coin_multipliers"] = dict(defaults["coin_multipliers"])
            changed = True
        if "coin_stats" not in mem:
            mem["coin_stats"] = dict(defaults["coin_stats"])
            changed = True
        if changed:
            self.save_strategy_memory(mem)
        return mem

    def save_strategy_memory(self, memory: Dict[str, Any]) -> None:
        memory["updated_at"] = self._now_utc_iso()
        self._atomic_write(self.files["strategy_memory"], memory)

    def load_shadow_portfolio(self) -> Dict[str, Any]:
        shd = self._safe_read(self.files["shadow_portfolio"], self.get_default_shadow_portfolio)
        changed = False
        if "filter_breakdown" not in shd:
            shd["filter_breakdown"] = self.get_default_shadow_portfolio()["filter_breakdown"]
            changed = True

        for item in shd.get("active_shadows", []):
            if "id" not in item:
                item["id"] = str(item.get("shadow_id", f"SHD-{item.get('coin', 'BTC')}-ACT"))
                changed = True
            if "tp_price" not in item:
                item["tp_price"] = float(item.get("tp2_price", item.get("tp1_price", 0.0)))
                changed = True
            if "confluence_score" not in item:
                item["confluence_score"] = float(item.get("score", 0.0))
                changed = True
            if "status" not in item:
                item["status"] = "ACTIVE"
                changed = True

        for item in shd.get("resolved_shadows", []):
            if "id" not in item:
                item["id"] = str(item.get("shadow_id", f"SHD-{item.get('coin', 'BTC')}-RES"))
                changed = True
            if "tp_price" not in item:
                item["tp_price"] = float(item.get("tp2_price", item.get("tp1_price", 0.0)))
                changed = True
            if "confluence_score" not in item:
                item["confluence_score"] = float(item.get("score", 0.0))
                changed = True
            if "status" not in item:
                old_out = str(item.get("outcome", ""))
                item["status"] = "SAVED_FROM_LOSS" if "SAVED" in old_out else "MISSED_WINNER"
                changed = True

        stats = shd.setdefault("stats", {})
        if "evaluated_count" not in stats:
            stats["evaluated_count"] = int(stats.get("saved_from_loss", 0)) + int(stats.get("missed_winners", 0))
            changed = True

        if changed:
            self.save_shadow_portfolio(shd)
        return shd

    def save_shadow_portfolio(self, shadow_pf: Dict[str, Any]) -> None:
        shadow_pf["updated_at"] = self._now_utc_iso()
        self._atomic_write(self.files["shadow_portfolio"], shadow_pf)
        resolved = shadow_pf.get("resolved_shadows", [])
        self._atomic_write(self.files["shadow_trades"], resolved[-200:])

    def load_active_setups(self) -> List[Dict[str, Any]]:
        data = self._safe_read(self.files["active_setups"], list)
        return data if isinstance(data, list) else []

    def save_active_setups(self, setups: List[Dict[str, Any]]) -> None:
        self._atomic_write(self.files["active_setups"], setups)

    def load_market_regime(self) -> Dict[str, Any]:
        data = self._safe_read(self.files["market_regime"], dict)
        if not isinstance(data, dict):
            return {}
        if "regimes" in data and isinstance(data["regimes"], dict):
            return data["regimes"]
        return data

    def save_market_regime(self, regimes: Dict[str, Any]) -> None:
        self._atomic_write(self.files["market_regime"], regimes)

    def save_risk_status(self, risk_status: Dict[str, Any]) -> None:
        risk_status["updated_at"] = self._now_utc_iso()
        self._atomic_write(self.files["risk_status"], risk_status)
