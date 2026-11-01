"""
ارکستراتور اصلی ابری V2 (Cloud Orchestrator - Institutional Trading Cycle)
Institutional Trading Bot V2 - Main Execution Pipeline
"""

import time
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import pandas as pd

from core.config import WATCHLIST, TIMEFRAMES
from core.data_engine import DataEngine
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


def run_institutional_cycle(dry_run: bool = False) -> Dict[str, Any]:
    """
    اجرای یک چرخه کامل ۱۵ دقیقه‌ای ربات معامله‌گر سازمانی V2.
    اگر dry_run=True باشد، چرخه بدون فراخوانی شبکه خارجی (برای تست سلامت معماری) اجرا می‌شود.
    """
    start_ts = time.time()
    now_utc = datetime.now(timezone.utc)
    cycle_summary: Dict[str, Any] = {
        "timestamp": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "STARTED",
        "commands_executed": [],
        "position_events": [],
        "opened_trades": [],
        "shadow_recorded": [],
        "regimes": {},
        "active_setups": [],
        "duration_sec": 0.0,
    }

    # ۱. مقداردهی اولیه هسته و ۱۲ مهارت
    state_mgr = StateManager()
    data_engine = DataEngine()
    regime_skill = RegimeDetectorSkill()
    scanner_skill = MarketScannerSkill()
    intel_skill = MarketIntelSkill()
    scorer_skill = ConfluenceScorerSkill()
    entry_skill = EntryTriggerSkill()
    exit_skill = ExitPlannerSkill()
    timemachine_skill = TimeMachineSkill()
    risk_skill = RiskGuardianSkill()
    budget_skill = BudgetAllocationSkill()
    broker_skill = BrokerExecutionSkill()
    ml_skill = MLFeedbackSkill()
    alerts_skill = TelegramAlertsSkill()

    # ۲. بارگذاری وضعیت‌های پایدار از پوشه state/
    portfolio = state_mgr.load_portfolio()
    bot_config = state_mgr.load_bot_config()
    strategy_memory = state_mgr.load_strategy_memory()
    shadow_portfolio = state_mgr.load_shadow_portfolio()

    if dry_run:
        cycle_summary["status"] = "DRY_RUN_COMPLETED"
        cycle_summary["duration_sec"] = round(time.time() - start_ts, 3)
        return cycle_summary

    try:
        # ۳. دریافت سنتیمنت بازار (Fear & Greed) و تشخیص سشن Killzone
        sentiment_data = intel_skill.fetch_sentiment()
        killzone_data = intel_skill.check_killzone_session(now_utc.hour)

        # ۴. دریافت کندل‌های ۵ دقیقه و ۱۵ دقیقه برای ارزهای واچ‌لیست
        market_5m: Dict[str, pd.DataFrame] = {}
        market_15m: Dict[str, pd.DataFrame] = {}
        live_prices: Dict[str, float] = {}

        for coin_key in WATCHLIST.keys():
            df_5m = data_engine.fetch_ohlcv(
                coin_key, timeframe=TIMEFRAMES["MICRO_TRIGGER"], limit=60
            )
            df_15m = data_engine.fetch_ohlcv(
                coin_key, timeframe=TIMEFRAMES["LTF_SETUP"], limit=85
            )
            if not df_5m.empty:
                market_5m[coin_key] = df_5m
                live_prices[coin_key] = float(df_5m["close"].iloc[-1])
            if not df_15m.empty:
                market_15m[coin_key] = df_15m
                if coin_key not in live_prices:
                    live_prices[coin_key] = float(df_15m["close"].iloc[-1])

        # ۵. پردازش دستورات از راه دور تلگرام (/status, /panic, /pause, /resume, ...)
        cmds = alerts_skill.process_incoming_commands(
            state_manager=state_mgr,
            broker=broker_skill,
            portfolio=portfolio,
            bot_config=bot_config,
            shadow_portfolio=shadow_portfolio,
            sentiment_data=sentiment_data,
            live_prices=live_prices,
        )
        cycle_summary["commands_executed"] = cmds

        # ۶. مدیریت پوزیشن‌های باز (بررسی برخورد به TP1 / TP2 / SL)
        pos_events = broker_skill.manage_open_positions(portfolio, market_5m)
        cycle_summary["position_events"] = pos_events

        for ev in pos_events:
            ev_type = ev.get("event_type", "")
            c_name = ev.get("coin", "")
            c_side = ev.get("side", "")
            if ev_type == "TP1_PARTIAL_AND_RISK_FREE":
                p_pnl = float(ev.get("partial_pnl_usdt", 0.0))
                new_sl = float(ev.get("new_sl", 0.0))
                alerts_skill.send_message(
                    f"🛡️ <b>تارگت اول (TP1) شکار شد و پوزیشن Risk-Free گردید!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 <b>دارایی:</b> <code>{c_name} ({c_side})</code>\n"
                    f"💵 <b>سود سیوشده (50% حجم):</b> <code>{p_pnl:+.2f}$</code>\n"
                    f"🔒 <b>استاپ جدید (نقطه ورود):</b> <code>{new_sl:.4f}</code>",
                    bot_config=bot_config,
                )
            elif ev_type == "POSITION_CLOSED":
                tot_pnl = float(ev.get("pnl_usdt", 0.0))
                reason_str = ev.get("reason", "")
                icon = "✅" if tot_pnl >= 0 else "❌"
                alerts_skill.send_message(
                    f"{icon} <b>پوزیشن بسته شد | {c_name} ({c_side})</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>دلیل خروج:</b> <code>{reason_str}</code>\n"
                    f"💰 <b>برآیند خالص معامله:</b> <code>{tot_pnl:+.2f}$</code>\n"
                    f"🏦 <b>موجودی جدید حساب:</b> <code>${float(portfolio.get('balance_usdt', 1000.0)):,.2f}</code>",
                    bot_config=bot_config,
                )

        # ۷. ارزیابی رادار سایه و به‌روزرسانی وزن‌های بیزی یادگیری ماشین
        ml_skill.evaluate_active_shadows(shadow_portfolio, market_5m)
        strategy_memory = ml_skill.update_strategy_weights(portfolio, strategy_memory)

        # ۸. تحلیل همبستگی پیرسون و واگرایی SMT بین BTC و ETH
        smt_global = intel_skill.analyze_correlation_and_smt(
            market_15m.get("BTC"), market_15m.get("ETH")
        )

        # ۹. اسکن ۵ دارایی واچ‌لیست برای شکار ستاپ‌های جدید
        regimes_map: Dict[str, Any] = {}
        active_setups_list: List[Dict[str, Any]] = []

        for coin_key, coin_meta in WATCHLIST.items():
            symbol = str(coin_meta["symbol"])
            df_4h = data_engine.fetch_ohlcv(
                coin_key, timeframe=TIMEFRAMES["HTF_STRUCTURE"], limit=75
            )
            df_1h = data_engine.fetch_ohlcv(
                coin_key, timeframe=TIMEFRAMES["MTF_REGIME"], limit=75
            )
            df_15m = market_15m.get(coin_key)
            df_5m = market_5m.get(coin_key)

            if df_1h.empty or df_15m is None or df_15m.empty or df_5m is None or df_5m.empty:
                continue

            # الف) تشخیص رژیم بازار در ۴ ساعته و ۱ ساعته
            reg_info = regime_skill.detect_regime(df_4h, df_1h)
            regimes_map[coin_key] = reg_info

            if not bool(reg_info.get("tradable", False)):
                continue

            # ب) اسکن ساختار ۱۵ دقیقه (FVG, Liquidity Sweep, Premium/Discount)
            scan_info = scanner_skill.scan_structure(df_15m, reg_info)
            if not bool(scan_info.get("valid", False)):
                continue

            cand_side = str(scan_info.get("candidate_side", "NONE"))
            if cand_side not in ("LONG", "SHORT"):
                continue

            # ج) دریافت جریان سفارشات (OrderBook Imbalance)
            ob_info = data_engine.fetch_order_book_imbalance(coin_key)

            # د) محاسبه امتیاز هم‌گرایی فازی + ضرایب یادگیری ماشین
            conf_info = scorer_skill.evaluate_confluence(
                coin=coin_key,
                candidate_side=cand_side,
                regime_data=reg_info,
                scan_data=scan_info,
                orderbook_data=ob_info,
                killzone_data=killzone_data,
                smt_data=smt_global,
                strategy_memory=strategy_memory,
            )

            final_score = float(conf_info.get("final_score", 0.0))

            # هـ) بررسی ماشه شلیک ۵ دقیقه و محاسبه قیمت ورود Limit Maker
            trig_info = entry_skill.evaluate_entry_trigger(
                df_5m=df_5m,
                candidate_side=cand_side,
                confluence_score=final_score,
                active_fvg=scan_info.get("active_fvg"),
            )

            entry_price = float(
                trig_info.get("limit_entry_price") or scan_info.get("current_price", 0.0)
            )
            exit_plan = exit_skill.plan_exit(
                entry_price=entry_price,
                side=cand_side,
                atr_15m=float(scan_info.get("atr_15m", 0.0)),
                scan_data=scan_info,
                regime_data=reg_info,
            )

            setup_snapshot = {
                "coin": coin_key,
                "symbol": symbol,
                "side": cand_side,
                "regime": reg_info.get("regime"),
                "score": final_score,
                "tier": conf_info.get("tier"),
                "triggered_5m": bool(trig_info.get("triggered", False)),
                "trigger_type": trig_info.get("trigger_type", "NONE"),
                "entry_price": entry_price,
                "stop_loss": exit_plan.get("stop_loss"),
                "tp1_price": exit_plan.get("tp1_breakeven"),
                "tp2_price": exit_plan.get("tp2_final"),
            }
            active_setups_list.append(setup_snapshot)

            # اگر امتیاز فازی زیر ۶۵ بود، در صورتی که بالای ۵۲ بود در رادار سایه ثبت شود تا دقت فیلتر سنجیده شود
            if not bool(conf_info.get("passed", False)):
                if final_score >= 52.0 and bool(trig_info.get("triggered", False)):
                    shd = broker_skill.record_shadow_trade(
                        shadow_portfolio=shadow_portfolio,
                        coin=coin_key,
                        side=cand_side,
                        entry_price=entry_price,
                        stop_loss=float(exit_plan["stop_loss"]),
                        tp1_price=float(exit_plan["tp1_breakeven"]),
                        tp2_price=float(exit_plan["tp2_final"]),
                        filter_reason="LOW_CONFLUENCE_SCORE",
                        score=final_score,
                        regime=str(reg_info.get("regime", "RANGING")),
                    )
                    cycle_summary["shadow_recorded"].append(shd["shadow_id"])
                continue

            # اگر امتیاز >= 65 است اما هنوز ماشه ۵ دقیقه شلیک نشده، منتظر چرخه بعدی می‌ماند
            if not bool(trig_info.get("triggered", False)):
                continue

            # و) شبیه‌سازی مونت‌کارلو در ماشین زمان (۱,۰۰۰ مسیر آینده)
            tm_info = timemachine_skill.run_simulation(
                df_15m=df_15m,
                exit_plan=exit_plan,
                confluence_score=final_score,
                regime_data=reg_info,
            )
            if not bool(tm_info.get("approved", False)):
                shd = broker_skill.record_shadow_trade(
                    shadow_portfolio=shadow_portfolio,
                    coin=coin_key,
                    side=cand_side,
                    entry_price=entry_price,
                    stop_loss=float(exit_plan["stop_loss"]),
                    tp1_price=float(exit_plan["tp1_breakeven"]),
                    tp2_price=float(exit_plan["tp2_final"]),
                    filter_reason="TIMEMACHINE_REJECTED",
                    score=final_score,
                    regime=str(reg_info.get("regime", "RANGING")),
                )
                cycle_summary["shadow_recorded"].append(shd["shadow_id"])
                continue

            # ز) بررسی نگهبان ریسک، ماتریس ۵ اسلات هوشمند و سپر همبستگی
            risk_info = budget_skill.allocate_budget(
                portfolio=portfolio,
                candidate_coin=coin_key,
                candidate_side=cand_side,
                confluence_data=conf_info,
                exit_plan=exit_plan,
                bot_config=bot_config,
            )
            if not bool(risk_info.get("approved", False)):
                shd = broker_skill.record_shadow_trade(
                    shadow_portfolio=shadow_portfolio,
                    coin=coin_key,
                    side=cand_side,
                    entry_price=entry_price,
                    stop_loss=float(exit_plan["stop_loss"]),
                    tp1_price=float(exit_plan["tp1_breakeven"]),
                    tp2_price=float(exit_plan["tp2_final"]),
                    filter_reason=str(risk_info.get("reason", "RISK_GUARDIAN_BLOCKED")),
                    score=final_score,
                    regime=str(reg_info.get("regime", "RANGING")),
                )
                cycle_summary["shadow_recorded"].append(shd["shadow_id"])
                continue

            # ح) بررسی گارد اسپرد ۵٪ (Spread Guard)
            spread_live = data_engine.fetch_live_spread(coin_key)
            spread_check = broker_skill.check_spread_guard(
                spread_data=spread_live,
                entry_price=entry_price,
                tp2_price=float(exit_plan["tp2_final"]),
            )
            if not bool(spread_check.get("passed", False)):
                shd = broker_skill.record_shadow_trade(
                    shadow_portfolio=shadow_portfolio,
                    coin=coin_key,
                    side=cand_side,
                    entry_price=entry_price,
                    stop_loss=float(exit_plan["stop_loss"]),
                    tp1_price=float(exit_plan["tp1_breakeven"]),
                    tp2_price=float(exit_plan["tp2_final"]),
                    filter_reason="SPREAD_GUARD_5PCT_BLOCKED",
                    score=final_score,
                    regime=str(reg_info.get("regime", "RANGING")),
                )
                cycle_summary["shadow_recorded"].append(shd["shadow_id"])
                continue

            # ط) شلیک نهایی سفارش، ثبت در پرتفوی، رسم چارت ۱۵ دقیقه و ارسال به تلگرام
            opened_pos = broker_skill.open_position(
                portfolio=portfolio,
                coin=coin_key,
                symbol=symbol,
                side=cand_side,
                entry_price=entry_price,
                exit_plan=exit_plan,
                risk_info=risk_info,
                confluence_info=conf_info,
                regime_info=reg_info,
                trigger_info=trig_info,
            )
            cycle_summary["opened_trades"].append(opened_pos["position_id"])

            chart_path = alerts_skill.generate_setup_chart(
                coin=coin_key,
                df_15m=df_15m,
                side=cand_side,
                entry_price=entry_price,
                stop_loss=float(exit_plan["stop_loss"]),
                tp1_price=float(exit_plan["tp1_breakeven"]),
                tp2_price=float(exit_plan["tp2_final"]),
                active_fvg=scan_info.get("active_fvg"),
                score=final_score,
                regime=str(reg_info.get("regime", "RANGING")),
            )
            caption = alerts_skill.build_trade_opened_caption(
                pos=opened_pos,
                timemachine_data=tm_info,
                spread_data=spread_check,
            )
            alerts_skill.send_photo(chart_path, caption=caption, bot_config=bot_config)

        # ۱۰. بررسی ارسال بیلان شبانه خودکار (ساعت ۲۱ تا ۲۳ UTC — یک بار در هر روز)
        today_str = now_utc.strftime("%Y-%m-%d")
        if 21 <= now_utc.hour <= 23 and bot_config.get("last_daily_report_date") != today_str:
            nightly_report = alerts_skill.build_status_report(
                portfolio=portfolio,
                bot_config=bot_config,
                shadow_portfolio=shadow_portfolio,
                sentiment_data=sentiment_data,
                title="🌙 بیلان شبانه و وضعیت پوزیشن‌های باز (Institutional Bot V2)",
            )
            eq_chart = alerts_skill.generate_equity_chart(portfolio)
            alerts_skill.send_photo(eq_chart, caption=nightly_report, bot_config=bot_config)
            bot_config["last_daily_report_date"] = today_str

        # ۱۱. ذخیره اتمیک تمام فایل‌های وضعیت در پوشه state/
        state_mgr.save_portfolio(portfolio)
        state_mgr.save_bot_config(bot_config)
        state_mgr.save_strategy_memory(strategy_memory)
        state_mgr.save_shadow_portfolio(shadow_portfolio)
        state_mgr.save_market_regime(regimes_map)
        state_mgr.save_active_setups(active_setups_list)

        cycle_summary["regimes"] = {k: v.get("regime") for k, v in regimes_map.items()}
        cycle_summary["active_setups"] = active_setups_list
        cycle_summary["status"] = "COMPLETED_SUCCESS"

    except Exception as e:
        cycle_summary["status"] = "ERROR"
        cycle_summary["error"] = str(e)
        print(f"❌ [CloudRunner] Critical error during institutional cycle: {e}")
        traceback.print_exc()
        # ذخیره وضعیت‌های فعلی حتی در صورت بروز خطا
        state_mgr.save_portfolio(portfolio)
        state_mgr.save_bot_config(bot_config)
        state_mgr.save_shadow_portfolio(shadow_portfolio)

    cycle_summary["duration_sec"] = round(time.time() - start_ts, 2)
    print(
        f"✅ [CloudRunner] Cycle finished in {cycle_summary['duration_sec']}s | "
        f"Status: {cycle_summary['status']} | Opened: {len(cycle_summary['opened_trades'])} | "
        f"Shadows: {len(cycle_summary['shadow_recorded'])}"
    )
    return cycle_summary


if __name__ == "__main__":
    run_institutional_cycle()