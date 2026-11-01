"""
مدیریت حافظه پایدار، فایل‌های JSON و ریست روزانه مدارشکن (State Manager)
Institutional Trading Bot V2 - Persistent State Management
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.config import (
    STATE_DIR,
    RISK_RULES,
    DEFAULT_REGIME_WEIGHTS,
    DEFAULT_COIN_MULTIPLIERS,
)


class StateManager:
    """
    کلاس مدیریت خواندن و نوشتن اتمیک فایل‌های وضعیت در پوشه state/
    """

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self.state_dir: Path = state_dir if state_dir else STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # مسیر دقیق تمام فایل‌های JSON معماری V2
        self.portfolio_file: Path = self.state_dir / "paper_portfolio.json"
        self.bot_config_file: Path = self.state_dir / "bot_config.json"
        self.strategy_memory_file: Path = self.state_dir / "strategy_memory.json"
        self.shadow_portfolio_file: Path = self.state_dir / "shadow_portfolio.json"
        self.shadow_trades_file: Path = self.state_dir / "shadow_trades.json"
        self.active_setups_file: Path = self.state_dir / "active_setups.json"
        self.market_regime_file: Path = self.state_dir / "market_regime.json"
        self.risk_status_file: Path = self.state_dir / "risk_status.json"

    @staticmethod
    def _utc_now_iso() -> str:
        """برگرداندن زمان فعلی UTC به فرمت استاندارد ISO-8601"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _utc_today_str() -> str:
        """برگرداندن تاریخ روز فعلی UTC به فرمت YYYY-MM-DD"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ==========================================================================
    # متدهای پایه خواندن و نوشتن ایمن (Atomic I/O)
    # ==========================================================================
    def _read_json(self, file_path: Path, default_data: Any) -> Any:
        """خواندن ایمن فایل JSON؛ در صورت عدم وجود یا خرابی، مقدار پیش‌فرض را می‌سازد."""
        if not file_path.exists():
            self._write_json(file_path, default_data)
            return json.loads(json.dumps(default_data))

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    self._write_json(file_path, default_data)
                    return json.loads(json.dumps(default_data))
                return json.loads(content)
        except Exception as e:
            print(f"⚠️ [StateManager] Error reading {file_path.name}: {e}. Restoring default.")
            self._write_json(file_path, default_data)
            return json.loads(json.dumps(default_data))

    def _write_json(self, file_path: Path, data: Any) -> bool:
        """نوشتن اتمیک اطلاعات در فایل JSON برای جلوگیری از ناقص شدن فایل در حین اجرا."""
        temp_path = file_path.with_suffix(".json.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, file_path)
            return True
        except Exception as e:
            print(f"❌ [StateManager] Error writing {file_path.name}: {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return False

    # ==========================================================================
    # ۱. مدیریت پرتفوی اصلی و ریست روزانه مدارشکن (paper_portfolio.json)
    # ==========================================================================
    def get_default_portfolio(self) -> Dict[str, Any]:
        """ساختار پیش‌فرض پرتفوی معاملاتی V2"""
        initial_bal = float(RISK_RULES.get("initial_balance_usdt", 1000.0))
        today_str = self._utc_today_str()
        now_iso = self._utc_now_iso()
        return {
            "version": "2.0",
            "balance_usdt": initial_bal,
            "initial_balance_usdt": initial_bal,
            "day_start_date": today_str,
            "day_start_equity": initial_bal,
            "daily_pnl_usdt": 0.0,
            "daily_circuit_breaker": False,
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            "open_positions": [],
            "trade_history": [],
            "equity_curve": [
                {"timestamp": now_iso, "equity": initial_bal}
            ],
            "stats": {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "total_pnl_usdt": 0.0,
                "max_drawdown_pct": 0.0,
            },
            "last_updated": now_iso,
        }

    def load_portfolio(self) -> Dict[str, Any]:
        """
        بارگذاری پرتفوی و بررسی تغییر تاریخ روز (UTC).
        اگر وارد روز جدید شده باشیم، مدارشکن روزانه و سود/زیان روزانه ریست می‌شوند.
        """
        default_pf = self.get_default_portfolio()
        portfolio = self._read_json(self.portfolio_file, default_pf)

        # ترمیم کلیدهای احتمالی جاافتاده
        for k, v in default_pf.items():
            if k not in portfolio:
                portfolio[k] = v
        if "stats" not in portfolio or not isinstance(portfolio["stats"], dict):
            portfolio["stats"] = default_pf["stats"]
        else:
            for sk, sv in default_pf["stats"].items():
                if sk not in portfolio["stats"]:
                    portfolio["stats"][sk] = sv

        # بررسی تغییر روز به وقت UTC برای ریست مدارشکن روزانه
        today_str = self._utc_today_str()
        if portfolio.get("day_start_date") != today_str:
            current_balance = float(portfolio.get("balance_usdt", default_pf["balance_usdt"]))
            portfolio["day_start_date"] = today_str
            portfolio["day_start_equity"] = round(current_balance, 4)
            portfolio["daily_pnl_usdt"] = 0.0
            portfolio["daily_circuit_breaker"] = False
            portfolio["last_updated"] = self._utc_now_iso()
            self.save_portfolio(portfolio)

        return portfolio

    def save_portfolio(self, portfolio: Dict[str, Any]) -> bool:
        """ذخیره وضعیت پرتفوی و همگام‌سازی خودکار فایل risk_status.json"""
        portfolio["last_updated"] = self._utc_now_iso()
        saved = self._write_json(self.portfolio_file, portfolio)

        # بروزرسانی همزمان خلاصه وضعیت ریسک
        day_eq = float(portfolio.get("day_start_equity", 1000.0))
        daily_pnl = float(portfolio.get("daily_pnl_usdt", 0.0))
        dd_pct = round((abs(min(0.0, daily_pnl)) / day_eq) * 100.0, 2) if day_eq > 0 else 0.0

        risk_summary = {
            "day_start_date": portfolio.get("day_start_date", self._utc_today_str()),
            "day_start_equity": day_eq,
            "daily_pnl_usdt": round(daily_pnl, 4),
            "daily_drawdown_pct": dd_pct,
            "daily_circuit_breaker": bool(portfolio.get("daily_circuit_breaker", False)),
            "consecutive_wins": int(portfolio.get("consecutive_wins", 0)),
            "consecutive_losses": int(portfolio.get("consecutive_losses", 0)),
            "open_positions_count": len(portfolio.get("open_positions", [])),
            "last_updated": portfolio["last_updated"],
        }
        self._write_json(self.risk_status_file, risk_summary)
        return saved

    def reset_portfolio(self) -> Dict[str, Any]:
        """ریست کامل پرتفوی به حالت اولیه ۱۰۰۰ دلاری (دستور /reset تلگرام)"""
        fresh = self.get_default_portfolio()
        self.save_portfolio(fresh)
        return fresh

    # ==========================================================================
    # ۲. مدیریت تنظیمات کنترلی ربات و تلگرام (bot_config.json)
    # ==========================================================================
    def get_default_bot_config(self) -> Dict[str, Any]:
        return {
            "is_paused": False,
            "panic_mode": False,
            "risk_mode": "NORMAL",  # حالت‌ها: NORMAL | CONSERVATIVE | AGGRESSIVE
            "last_update_id": 0,
            "last_daily_report_date": "",
            "last_updated": self._utc_now_iso(),
        }

    def load_bot_config(self) -> Dict[str, Any]:
        default_cfg = self.get_default_bot_config()
        cfg = self._read_json(self.bot_config_file, default_cfg)
        for k, v in default_cfg.items():
            if k not in cfg:
                cfg[k] = v
        return cfg

    def save_bot_config(self, config: Dict[str, Any]) -> bool:
        config["last_updated"] = self._utc_now_iso()
        return self._write_json(self.bot_config_file, config)

    # ==========================================================================
    # ۳. مدیریت حافظه یادگیری ماشین بیزی (strategy_memory.json)
    # ==========================================================================
    def get_default_strategy_memory(self) -> Dict[str, Any]:
        return {
            "regime_weights": dict(DEFAULT_REGIME_WEIGHTS),
            "coin_multipliers": dict(DEFAULT_COIN_MULTIPLIERS),
            "total_feedback_cycles": 0,
            "last_updated": self._utc_now_iso(),
        }

    def load_strategy_memory(self) -> Dict[str, Any]:
        default_mem = self.get_default_strategy_memory()
        mem = self._read_json(self.strategy_memory_file, default_mem)
        if "regime_weights" not in mem or not isinstance(mem["regime_weights"], dict):
            mem["regime_weights"] = dict(DEFAULT_REGIME_WEIGHTS)
        else:
            for rk, rv in DEFAULT_REGIME_WEIGHTS.items():
                if rk not in mem["regime_weights"]:
                    mem["regime_weights"][rk] = rv

        if "coin_multipliers" not in mem or not isinstance(mem["coin_multipliers"], dict):
            mem["coin_multipliers"] = dict(DEFAULT_COIN_MULTIPLIERS)
        else:
            for ck, cv in DEFAULT_COIN_MULTIPLIERS.items():
                if ck not in mem["coin_multipliers"]:
                    mem["coin_multipliers"][ck] = cv
        return mem

    def save_strategy_memory(self, memory: Dict[str, Any]) -> bool:
        memory["last_updated"] = self._utc_now_iso()
        return self._write_json(self.strategy_memory_file, memory)

    # ==========================================================================
    # ۴. مدیریت دیتابیس رادار سایه (shadow_portfolio.json & shadow_trades.json)
    # ==========================================================================
    def get_default_shadow_portfolio(self) -> Dict[str, Any]:
        return {
            "active_shadows": [],
            "resolved_shadows": [],
            "stats": {
                "total_filtered": 0,
                "saved_from_loss": 0,
                "missed_winners": 0,
                "shield_accuracy": 100.0,
            },
            "last_updated": self._utc_now_iso(),
        }

    def load_shadow_portfolio(self) -> Dict[str, Any]:
        default_sh = self.get_default_shadow_portfolio()
        sh = self._read_json(self.shadow_portfolio_file, default_sh)
        for k, v in default_sh.items():
            if k not in sh:
                sh[k] = v
        if "stats" not in sh or not isinstance(sh["stats"], dict):
            sh["stats"] = default_sh["stats"]
        else:
            for sk, sv in default_sh["stats"].items():
                if sk not in sh["stats"]:
                    sh["stats"][sk] = sv
        return sh

    def save_shadow_portfolio(self, shadow_pf: Dict[str, Any]) -> bool:
        shadow_pf["last_updated"] = self._utc_now_iso()
        saved = self._write_json(self.shadow_portfolio_file, shadow_pf)
        # آرشیو ۵۰ معامله حل‌شده آخر در shadow_trades.json برای سازگاری کامل
        resolved = shadow_pf.get("resolved_shadows", [])[-50:]
        self._write_json(self.shadow_trades_file, resolved)
        return saved

    # ==========================================================================
    # ۵. مدیریت وضعیت‌های کمکی (active_setups, market_regime, risk_status)
    # ==========================================================================
    def load_active_setups(self) -> Dict[str, Any]:
        default_data = {"setups": [], "last_scan": self._utc_now_iso()}
        return self._read_json(self.active_setups_file, default_data)

    def save_active_setups(self, setups: List[Dict[str, Any]]) -> bool:
        payload = {"setups": setups, "last_scan": self._utc_now_iso()}
        return self._write_json(self.active_setups_file, payload)

    def load_market_regime(self) -> Dict[str, Any]:
        default_data = {"regimes": {}, "last_updated": self._utc_now_iso()}
        return self._read_json(self.market_regime_file, default_data)

    def save_market_regime(self, regimes: Dict[str, Any]) -> bool:
        payload = {"regimes": regimes, "last_updated": self._utc_now_iso()}
        return self._write_json(self.market_regime_file, payload)

    def load_risk_status(self) -> Dict[str, Any]:
        default_data = {
            "day_start_date": self._utc_today_str(),
            "day_start_equity": float(RISK_RULES.get("initial_balance_usdt", 1000.0)),
            "daily_pnl_usdt": 0.0,
            "daily_drawdown_pct": 0.0,
            "daily_circuit_breaker": False,
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            "open_positions_count": 0,
            "last_updated": self._utc_now_iso(),
        }
        return self._read_json(self.risk_status_file, default_data)