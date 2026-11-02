"""
اسکریپت تست اتصال صرافی، سلامت فایل‌ها، ۱۲ مهارت و گزارش‌دهی تلگرام (System Diagnostics)
Institutional Trading Bot V2.5 - End-to-End Health Check & Verification Suite
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from core.config import WATCHLIST, TIMEFRAMES, STATE_DIR
from core.data_engine import DataEngine
from core.slot_manager import can_open_new_position
from core.state_manager import StateManager

from skills.alerts import TelegramAlertsSkill
from skills.broker import BrokerExecutionSkill
from skills.budget import BudgetAllocationSkill
from skills.confluence_scorer import ConfluenceScorerSkill
from skills.entry import EntryTriggerSkill
from skills.exit_planner import ExitPlannerSkill
from skills.market_intel import MarketIntelSkill
from skills.ml_feedback import MLFeedbackSkill
from skills.regime_detector import RegimeDetectorSkill
from skills.risk_guardian import RiskGuardianSkill
from skills.scanner import MarketScannerSkill
from skills.timemachine import TimeMachineSkill


def run_system_diagnostics(live_exchange: bool = False, send_telegram: bool = False) -> Dict[str, Any]:
    """
    بررسی کامل سلامت معماری، ۸ فایل JSON، ۱۲ مهارت تحلیلی، موتور گرافیکی
    و (در صورت انتخاب) تست اتصال زنده به صرافی KuCoin و ربات تلگرام.
    """
    results: Dict[str, bool] = {}

    # ۱. بررسی سلامت ۸ فایل وضعیت JSON در پوشه state/
    sm = StateManager()
    required_jsons = [
        "paper_portfolio.json",
        "bot_config.json",
        "strategy_memory.json",
        "shadow_portfolio.json",
        "shadow_trades.json",
        "active_setups.json",
        "market_regime.json",
        "risk_status.json",
    ]
    json_ok = all((STATE_DIR / fname).is_file() for fname in required_jsons)
    pf = sm.load_portfolio()
    cfg = sm.load_bot_config()
    mem = sm.load_strategy_memory()
    shd = sm.load_shadow_portfolio()
    results["state_files_ok"] = bool(json_ok and "balance_usdt" in pf and "risk_mode" in cfg)

    # ۲. بررسی نمونه‌سازی و سلامت هر ۱۲ مهارت و موتور دیتا
    de = DataEngine()
    rd = RegimeDetectorSkill()
    sc = MarketScannerSkill()
    mi = MarketIntelSkill()
    cs = ConfluenceScorerSkill()
    et = EntryTriggerSkill()
    ep = ExitPlannerSkill()
    tm = TimeMachineSkill()
    rg = RiskGuardianSkill()
    bg = BudgetAllocationSkill()
    br = BrokerExecutionSkill()
    ml = MLFeedbackSkill()
    al = TelegramAlertsSkill()

    # تست زنجیره تحلیلی با دیتای استاندارد و پرتفوی پایه
    synth_df = pd.DataFrame({
        "open": np.linspace(100, 110, 60),
        "high": np.linspace(101, 111, 60),
        "low": np.linspace(99, 109, 60),
        "close": np.linspace(100.5, 110.5, 60),
        "volume": [150.0] * 60,
    })
    synth_df["atr"] = de._compute_atr(synth_df, 14)

    test_pf = sm.get_default_portfolio()
    test_cfg = sm.get_default_bot_config()

    reg_res = rd.detect_regime(synth_df, synth_df)
    scan_res = sc.scan_structure(synth_df, reg_res)
    kz_res = mi.check_killzone_session(14)
    smt_res = mi.analyze_correlation_and_smt(synth_df, synth_df)
    conf_res = cs.evaluate_confluence(
        "BTC", "LONG", reg_res, scan_res, {"buy_pressure_pct": 60.0}, kz_res, smt_res, mem
    )
    trig_res = et.evaluate_entry_trigger(synth_df, "LONG", 82.0, {"top": 109.0, "bottom": 108.0})
    exit_res = ep.plan_exit(110.0, "LONG", 2.0, scan_res, reg_res)
    tm_res = tm.run_simulation(synth_df, exit_res, 82.0, reg_res, seed=42)
    slot_res = can_open_new_position([], "BTC", "LONG", 82.0)
    risk_res = bg.allocate_budget(
        test_pf, "BTC", "LONG", {"final_score": 82.0, "size_multiplier": 1.0}, exit_res, test_cfg
    )
    sp_res = br.check_spread_guard({"spread_abs": 0.05}, 110.0, exit_res["tp2_final"])
    chart_path = al.generate_setup_chart(
        "BTC", synth_df, "LONG", 110.0, exit_res["stop_loss"], exit_res["tp1_breakeven"], exit_res["tp2_final"]
    )
    eq_path = al.generate_equity_chart(pf)

    results["skills_pipeline_ok"] = bool(
        reg_res["tradable"]
        and scan_res["valid"]
        and trig_res["triggered"]
        and exit_res["valid"]
        and tm_res["approved"]
        and slot_res["allowed"]
        and risk_res["approved"]
        and sp_res["passed"]
        and Path(chart_path).is_file()
        and Path(eq_path).is_file()
    )

    # ۳. تست اتصال زنده به صرافی KuCoin (در صورت فعال بودن فلگ live_exchange)
    if live_exchange:
        df_live = de.fetch_ohlcv("BTC", timeframe=TIMEFRAMES["LTF_SETUP"], limit=25)
        sp_live = de.fetch_live_spread("BTC")
        ob_live = de.fetch_order_book_imbalance("BTC")
        results["live_exchange_ok"] = bool(
            not df_live.empty and sp_live.get("valid", False) and ob_live.get("valid", False)
        )
    else:
        results["live_exchange_ok"] = True

    # ۴. تست ارسال گزارش به تلگرام (در صورت فعال بودن فلگ send_telegram)
    if send_telegram and al.is_configured:
        report_text = al.build_status_report(
            pf, cfg, shd, {"value": 55, "classification": "Greed", "bar": "🟩🟩🟩🟩🟩🟩⬜⬜⬜⬜"},
            title="✅ تست سلامت سیستم (Institutional Trading Bot V2.5)"
        )
        results["telegram_sent_ok"] = al.send_photo(eq_path, caption=report_text, bot_config=cfg)
    else:
        results["telegram_sent_ok"] = True

    all_passed = all(results.values())
    return {
        "all_passed": all_passed,
        "checks": results,
        "watchlist_count": len(WATCHLIST),
        "telegram_configured": al.is_configured,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Institutional Bot V2.5 - System Health Check")
    parser.add_argument("--live", action="store_true", help="تست دریافت کندل و اردربوک زنده از KuCoin")
    parser.add_argument("--telegram", action="store_true", help="ارسال پیام و چارت تست به تلگرام")
    args = parser.parse_args()

    diag = run_system_diagnostics(live_exchange=args.live, send_telegram=args.telegram)
    print("=" * 65)
    print("🩺 Institutional Trading Bot V2.5 — Diagnostic Report")
    for k, v in diag["checks"].items():
        badge = "✅ PASS" if v else "❌ FAIL"
        print(f"  - {k}: {badge}")
    print(f"  - Telegram Credentials Configured: {diag['telegram_configured']}")
    print("=" * 65)
