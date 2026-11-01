"""
ارکستراتور اصلی ابری نسخه V2.5 Pro (Cloud Runner - 15m Institutional Execution Pipeline)
Institutional Trading Bot V2.5 - Full End-to-End Orchestrator
"""

import argparse
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

from core.config import WATCHLIST, TIMEFRAMES, format_price
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


def _generate_synthetic_ohlcv(base_price: float, bars: int = 80) -> pd.DataFrame:
    """تولید دیتای استاندارد آفلاین برای حالت تست (Dry-Run)."""
    rng = np.random.default_rng(42)
    closes = base_price + np.cumsum(rng.normal(0, base_price * 0.002, bars))
    opens = np.roll(closes, 1)
    opens[0] = base_price
    highs = np.maximum(opens, closes) + abs(rng.normal(0, base_price * 0.0015, bars))
    lows = np.minimum(opens, closes) - abs(rng.normal(0, base_price * 0.0015, bars))
    vols = rng.uniform(100, 500, bars)
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    })
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    return df


def run_institutional_cycle(
    dry_run: bool = False,
    target_analyze_coin: Optional[str] = None,
) -> Dict[str, Any]:
    """
    اجرای یک چرخه کامل ۱۵ دقیقه‌ای ربات سازمانی V2.5 Pro:
    1. بارگذاری ۸ فایل وضعیت و بررسی ریست روزانه/هفتگی و دروازه ۵۰ معامله
    2. دریافت دیتا از KuCoin (یا دیتای شبیه‌سازی در حالت dry_run)
    3. پردازش دستورات و دکمه‌های شیشه‌ای تلگرام (چارت ۵ ارز، ریسک‌فری سریع، سیو سود ۵۰٪)
    4. مدیریت پوزیشن‌های باز (TP1، تریلینگ استاپ ساختاری، TP2، SL) و ارسال کارت PnL
    5. بررسی سپر تقویم اقتصادی فارکس (اخبار قرمز USD) و مدارشکن روزانه/هفتگی
    6. اسکن ساختار ۱۵ دقیقه، رنج سشن آسیا، امتیاز فازی، ماشین زمان و ثبت شکار جدید
    7. ارسال بیلان شبانه جمع‌وجور در آغاز روز جدید UTC و ذخیره اتمیک وضعیت‌ها
    """
    t0 = time.time()
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    # ۱. نمونه‌سازی هسته و هر ۱۲ مهارت تخصصی
    state_mgr = StateManager()
    data_engine = DataEngine()
    regime_skill = RegimeDetectorSkill()
    scanner_skill = MarketScannerSkill()
    intel_skill = MarketIntelSkill()
    scorer_skill = ConfluenceScorerSkill()
    entry_skill = EntryTriggerSkill()
    exit_skill = ExitPlannerSkill()
    tm_skill = TimeMachineSkill()
    risk_skill = RiskGuardianSkill()
    budget_skill = BudgetAllocationSkill()
    broker_skill = BrokerExecutionSkill()
    ml_skill = MLFeedbackSkill()
    alerts_skill = TelegramAlertsSkill()

    # ۲. بارگذاری حافظه پایدار
    portfolio = state_mgr.load_portfolio()
    bot_config = state_mgr.load_bot_config()
    strategy_memory = state_mgr.load_strategy_memory()
    shadow_portfolio = state_mgr.load_shadow_portfolio()

    # اگر فراخوانی صرفاً برای ارسال فوری چارت تحلیلی یک ارز خاص باشد (از سمت وب‌هوک یا اکشن)
    env_target_coin = (target_analyze_coin or os.getenv("TARGET_ANALYZE_COIN", "")).strip().upper()
    if env_target_coin and env_target_coin in WATCHLIST and not dry_run:
        alerts_skill._send_cached_or_live_asset_analysis(env_target_coin, state_mgr, bot_config)
        return {
            "status": f"ON_DEMAND_ANALYSIS_SENT_{env_target_coin}",
            "duration_sec": round(time.time() - t0, 2),
        }

    # ۳. دریافت دیتای چندتایم‌فریمی برای ۵ دارایی
    data_4h: Dict[str, pd.DataFrame] = {}
    data_1h: Dict[str, pd.DataFrame] = {}
    data_15m: Dict[str, pd.DataFrame] = {}
    data_5m: Dict[str, pd.DataFrame] = {}
    spreads: Dict[str, Dict[str, Any]] = {}
    orderbooks: Dict[str, Dict[str, Any]] = {}
    live_prices: Dict[str, float] = {}

    base_map = {"BTC": 80000.0, "ETH": 2200.0, "SOL": 110.0, "XRP": 1.30, "XAU": 3980.0}

    for coin in WATCHLIST.keys():
        if dry_run:
            b_price = base_map.get(coin, 100.0)
            data_4h[coin] = _generate_synthetic_ohlcv(b_price, 60)
            data_1h[coin] = _generate_synthetic_ohlcv(b_price, 80)
            data_15m[coin] = _generate_synthetic_ohlcv(b_price, 80)
            data_5m[coin] = _generate_synthetic_ohlcv(b_price, 80)
            spreads[coin] = {"valid": True, "spread_abs": b_price * 0.0001}
            orderbooks[coin] = {"valid": True, "buy_pressure_pct": 56.0}
            live_prices[coin] = float(data_15m[coin]["close"].iloc[-1])
        else:
            data_4h[coin] = data_engine.fetch_ohlcv(coin, TIMEFRAMES["HTF_STRUCTURE"], limit=60)
            data_1h[coin] = data_engine.fetch_ohlcv(coin, TIMEFRAMES["MTF_REGIME"], limit=80)
            data_15m[coin] = data_engine.fetch_ohlcv(coin, TIMEFRAMES["LTF_SETUP"], limit=80)
            data_5m[coin] = data_engine.fetch_ohlcv(coin, TIMEFRAMES["MICRO_TRIGGER"], limit=60)
            spreads[coin] = data_engine.fetch_live_spread(coin)
            orderbooks[coin] = data_engine.fetch_order_book_imbalance(coin)
            if not data_15m[coin].empty:
                live_prices[coin] = float(data_15m[coin]["close"].iloc[-1])

    # ۴. دریافت اطلاعات کلان بازار (سنتیمنت، سشن Killzone، تقویم اقتصادی فارکس و واگرایی SMT)
    if dry_run:
        sentiment = {"value": 48, "classification": "Neutral", "bar": "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜"}
        news_status = {
            "news_shield_active": False,
            "active_event": None,
            "upcoming_events": [],
            "summary_fa": "🟢 بدون خبر قرمز قریب‌الوقوع (ایمن برای ترید)",
        }
    else:
        sentiment = intel_skill.fetch_sentiment()
        news_status = intel_skill.check_economic_news_shield(now_utc)

    killzone = intel_skill.check_killzone_session(now_utc.hour)
    smt_data = intel_skill.analyze_correlation_and_smt(data_15m.get("BTC"), data_15m.get("ETH"))

    # ۵. پردازش دستورات و کالبک‌های شیشه‌ای تلگرام
    def _handle_on_demand_chart(req_coin: str) -> None:
        df_c = data_15m.get(req_coin)
        if df_c is None or df_c.empty:
            alerts_skill._send_cached_or_live_asset_analysis(req_coin, state_mgr, bot_config)
            return
        reg_c = regime_skill.detect_regime(data_1h.get(req_coin), data_4h.get(req_coin))
        scan_c = scanner_skill.scan_structure(df_c, reg_c)
        side_c = scan_c.get("candidate_side", "LONG")
        if side_c == "NONE":
            side_c = "LONG" if reg_c.get("htf_bias") != "BEARISH" else "SHORT"
        conf_c = scorer_skill.evaluate_confluence(
            req_coin, side_c, reg_c, scan_c, orderbooks.get(req_coin), killzone, smt_data, strategy_memory
        )
        c_path = alerts_skill.generate_asset_analysis_chart(req_coin, df_c, scan_c, reg_c)
        cap = alerts_skill.build_asset_analysis_caption(req_coin, reg_c, scan_c, conf_c, orderbooks.get(req_coin))
        alerts_skill.send_photo(
            c_path, caption=cap, bot_config=bot_config, custom_keyboard=alerts_skill.build_hunt_inline_keyboard(req_coin)
        )

    executed_commands: List[str] = []
    if not dry_run and alerts_skill.is_configured:
        executed_commands = alerts_skill.process_incoming_commands(
            state_manager=state_mgr,
            broker=broker_skill,
            portfolio=portfolio,
            bot_config=bot_config,
            shadow_portfolio=shadow_portfolio,
            live_prices=live_prices,
            on_demand_callback=_handle_on_demand_chart,
        )

    # ۶. بروزرسانی پوزیشن‌های باز (TP1، تریلینگ استاپ ساختاری، TP2، SL)
    pos_update = broker_skill.update_open_positions(portfolio, data_15m)
    unrealized_pnl = float(pos_update["total_unrealized_pnl_usdt"])

    # ارسال اعلان رویدادهای پوزیشن و کارت تصویری PnL به تلگرام
    if not dry_run and alerts_skill.is_configured:
        for ev in pos_update["events"]:
            ev_type = ev.get("type", "")
            c_name = ev.get("coin", "")
            s_name = ev.get("side", "")

            if ev_type == "TP1_PARTIAL_AND_BREAKEVEN":
                det = ev.get("details", {})
                msg = (
                    f"🛡️ <b>تارگت اول (TP1) و ریسک‌فری فعال شد | {c_name} ({s_name})</b>\n"
                    f"• ۵۰٪ حجم پوزیشن با سود خالص <code>+${det.get('net_partial_pnl_usdt', 0.0):.2f}</code> نقد شد.\n"
                    f"• حد ضرر ۵۰٪ باقی‌مانده به نقطه ورود (<code>{format_price(det.get('new_stop_loss'), c_name)}</code>) منتقل گردید."
                )
                alerts_skill.send_message(msg, bot_config=bot_config)

            elif ev_type == "STRUCTURAL_TRAILING_UPDATED":
                msg = (
                    f"🚀 <b>تریلینگ استاپ ساختاری ارتقا یافت | {c_name} ({s_name})</b>\n"
                    f"• استاپ از <code>{format_price(ev.get('old_sl'), c_name)}</code> به پشت سوئینگ جدید در <code>{format_price(ev.get('new_sl'), c_name)}</code> قفل شد."
                )
                alerts_skill.send_message(msg, bot_config=bot_config)

            elif "trade" in ev:
                tr_rec = ev["trade"]
                pnl_card_path = alerts_skill.generate_pnl_card(tr_rec, portfolio)
                gate = state_mgr.get_paper_gate_progress(portfolio)
                pnl_val = float(tr_rec.get("net_pnl_usdt", 0.0))
                r_val = float(tr_rec.get("r_multiple", 0.0))
                badge = "✅ سود نهایی" if pnl_val >= 0 else "🛑 حد ضرر"
                cap = (
                    f"{badge} | <b>{c_name} ({s_name})</b> بسته شد\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>علت خروج:</b> <code>{ev_type}</code>\n"
                    f"• <b>نتیجه مالی:</b> <code>{pnl_val:+.2f}$ ({r_val:+.2f}R)</code>\n"
                    f"• <b>موجودی جدید:</b> <code>${float(portfolio['balance_usdt']):,.2f}</code>\n"
                    f"• <b>دروازه ۵۰ معامله کاغذی:</b> <code>{gate['completed_trades']}/{gate['target_trades']}</code> ({gate['progress_pct']:.0f}%)"
                )
                alerts_skill.send_photo(pnl_card_path, caption=cap, bot_config=bot_config)

    # ۷. ارزیابی رادار سایه و یادگیری ماشین بیزی در صورت بسته شدن معامله
    ml_skill.evaluate_active_shadows(shadow_portfolio, data_15m)
    if pos_update["closed_trades"]:
        strategy_memory = ml_skill.update_strategy_memory(
            strategy_memory, portfolio.get("closed_trades", [])
        )

    # ۸. بررسی مدارشکن روزانه (۲٪) و هفتگی (۵٪)
    cb_info = risk_skill.check_circuit_breaker(portfolio, unrealized_pnl)
    state_mgr.save_risk_status({
        "circuit_breaker": cb_info["daily_locked"],
        "weekly_circuit_breaker": cb_info["weekly_locked"],
        "daily_drawdown_pct": cb_info["daily_drawdown_pct"],
        "weekly_drawdown_pct": cb_info["weekly_drawdown_pct"],
        "active_slots": len(portfolio.get("open_positions", [])),
    })

    # ۹. حلقه اسکن، تحلیل و شکار روی ۵ دارایی واچ‌لیست
    regimes_snapshot: Dict[str, Any] = {}
    active_setups_snapshot: List[Dict[str, Any]] = []
    opened_positions_count = 0

    for coin in WATCHLIST.keys():
        df_15 = data_15m.get(coin)
        df_1 = data_1h.get(coin)
        df_4 = data_4h.get(coin)
        df_5 = data_5m.get(coin)

        if df_15 is None or df_15.empty or df_1 is None or df_1.empty:
            regimes_snapshot[coin] = {"regime": "NO_DATA", "tradable": False}
            continue

        reg_res = regime_skill.detect_regime(df_1, df_4)
        scan_res = scanner_skill.scan_structure(df_15, reg_res)
        cand_side = scan_res.get("candidate_side", "NONE")

        eval_side = cand_side if cand_side in ("LONG", "SHORT") else (
            "LONG" if reg_res.get("htf_bias") != "BEARISH" else "SHORT"
        )
        conf_preview = scorer_skill.evaluate_confluence(
            coin=coin,
            candidate_side=eval_side,
            regime_data=reg_res,
            scan_data=scan_res,
            orderbook_data=orderbooks.get(coin),
            killzone_data=killzone,
            smt_data=smt_data,
            strategy_memory=strategy_memory,
        )

        # ذخیره اسنپ‌شات غنی رادار برای نمایش در /status و دکمه‌های شیشه‌ای
        regimes_snapshot[coin] = {
            "regime": reg_res.get("regime", "RANGING"),
            "strategy": reg_res.get("strategy", "NONE"),
            "htf_bias": reg_res.get("htf_bias", "NEUTRAL"),
            "adx": reg_res.get("adx", 0.0),
            "tradable": reg_res.get("tradable", False),
            "current_price": scan_res.get("current_price", 0.0),
            "candidate_side": cand_side,
            "confluence_score": conf_preview.get("final_score", 0.0),
            "zone": scan_res.get("zone", "EQUILIBRIUM"),
            "asian_range": scan_res.get("asian_range", {}),
            "xray_summary_fa": conf_preview.get("xray_summary_fa", ""),
        }

        if not reg_res.get("tradable", False) or cand_side not in ("LONG", "SHORT"):
            continue

        # طراحی نقشه خروج اولیه برای ثبت در رادار سایه در صورت فیلتر شدن
        prelim_exit = exit_skill.plan_exit(
            entry_price=float(scan_res["current_price"]),
            side=cand_side,
            atr_15m=float(scan_res["atr_15m"]),
            scan_data=scan_res,
            regime_data=reg_res,
        )

        # الف) فیلتر پیشگیرانه تقویم اقتصادی فارکس (اخبار قرمز USD)
        if news_status.get("news_shield_active", False):
            ml_skill.record_filtered_signal(
                shadow_portfolio, coin, cand_side,
                prelim_exit["entry_price"], prelim_exit["stop_loss"], prelim_exit["tp2_final"],
                filter_reason="ECONOMIC_NEWS_BLOCKED",
                confluence_score=conf_preview["final_score"],
            )
            continue

        # ب) فیلتر امتیاز هم‌گرایی فازی (حداقل ۶۵)
        if not conf_preview["passed"]:
            ml_skill.record_filtered_signal(
                shadow_portfolio, coin, cand_side,
                prelim_exit["entry_price"], prelim_exit["stop_loss"], prelim_exit["tp2_final"],
                filter_reason="LOW_CONFLUENCE_SCORE",
                confluence_score=conf_preview["final_score"],
            )
            continue

        # ج) فیلتر ماشه کندلی ۵ دقیقه یا Limit Sniper
        trig_res = entry_skill.evaluate_entry_trigger(
            df_5m=df_5,
            candidate_side=cand_side,
            confluence_score=conf_preview["final_score"],
            active_fvg=scan_res.get("active_fvg"),
        )
        if not trig_res["triggered"]:
            continue

        # د) طراحی دقیق نقشه خروج بر اساس قیمت ورود Maker
        exit_plan = exit_skill.plan_exit(
            entry_price=float(trig_res["limit_entry_price"]),
            side=cand_side,
            atr_15m=float(scan_res["atr_15m"]),
            scan_data=scan_res,
            regime_data=reg_res,
        )
        if not exit_plan["valid"]:
            continue

        # هـ) فیلتر شبیه‌ساز مونت‌کارلو (ماشین زمان ۱۰۰۰ مسیر)
        tm_res = tm_skill.run_simulation(
            df_15m=df_15,
            exit_plan=exit_plan,
            confluence_score=conf_preview["final_score"],
            regime_data=reg_res,
        )
        if not tm_res["approved"]:
            ml_skill.record_filtered_signal(
                shadow_portfolio, coin, cand_side,
                exit_plan["entry_price"], exit_plan["stop_loss"], exit_plan["tp2_final"],
                filter_reason="TIMEMACHINE_REJECTED",
                confluence_score=conf_preview["final_score"],
            )
            continue

        # و) فیلتر بودجه، ۵ اسلات، سپر همبستگی و مدارشکن‌ها
        alloc_res = budget_skill.allocate_budget(
            portfolio=portfolio,
            coin=coin,
            side=cand_side,
            confluence_data=conf_preview,
            exit_plan=exit_plan,
            bot_config=bot_config,
            unrealized_pnl_usdt=unrealized_pnl,
        )
        if not alloc_res["approved"]:
            ml_skill.record_filtered_signal(
                shadow_portfolio, coin, cand_side,
                exit_plan["entry_price"], exit_plan["stop_loss"], exit_plan["tp2_final"],
                filter_reason="RISK_GUARDIAN_BLOCKED",
                confluence_score=conf_preview["final_score"],
            )
            continue

        # ز) اجرای نهایی و گارد اسپرد ۵٪
        open_res = broker_skill.open_paper_position(
            portfolio=portfolio,
            coin=coin,
            side=cand_side,
            entry_plan=trig_res,
            exit_plan=exit_plan,
            allocation=alloc_res,
            regime_data=reg_res,
            confluence_data=conf_preview,
            spread_data=spreads.get(coin),
        )
        if not open_res["opened"]:
            ml_skill.record_filtered_signal(
                shadow_portfolio, coin, cand_side,
                exit_plan["entry_price"], exit_plan["stop_loss"], exit_plan["tp2_final"],
                filter_reason="SPREAD_GUARD_5PCT_BLOCKED",
                confluence_score=conf_preview["final_score"],
            )
            continue

        opened_positions_count += 1
        active_setups_snapshot.append(open_res["position"])

        # ح) رندر چارت دوطبقه (کندل + حجم + سشن آسیا) و ارسال شکار جدید به تلگرام
        if not dry_run and alerts_skill.is_configured:
            chart_path = alerts_skill.generate_setup_chart(
                coin=coin,
                df_15m=df_15,
                side=cand_side,
                entry_price=exit_plan["entry_price"],
                stop_loss=exit_plan["stop_loss"],
                tp1_price=exit_plan["tp1_breakeven"],
                tp2_price=exit_plan["tp2_final"],
                active_fvg=scan_res.get("active_fvg"),
                regime=reg_res.get("regime", "RANGING"),
                asian_range=scan_res.get("asian_range"),
            )
            hunt_caption = alerts_skill.build_hunt_caption(
                coin=coin,
                side=cand_side,
                regime_data=reg_res,
                confluence_data=conf_preview,
                entry_plan=trig_res,
                exit_plan=exit_plan,
                tm_data=tm_res,
                allocation=alloc_res,
                sentiment_data=sentiment,
            )
            alerts_skill.send_photo(
                chart_path,
                caption=hunt_caption,
                bot_config=bot_config,
                custom_keyboard=alerts_skill.build_hunt_inline_keyboard(coin),
            )

    # ۱۰. ارسال خودکار «بیلان شبانه جمع‌وجور» یک بار در آغاز هر روز UTC
    if not dry_run and alerts_skill.is_configured:
        if bot_config.get("last_daily_report_date") != today_str:
            eq_chart = alerts_skill.generate_equity_chart(portfolio)
            nightly_text = alerts_skill.build_nightly_pulse_report(
                portfolio=portfolio,
                bot_config=bot_config,
                shadow_portfolio=shadow_portfolio,
                sentiment_data=sentiment,
            )
            if alerts_skill.send_photo(eq_chart, caption=nightly_text, bot_config=bot_config):
                bot_config["last_daily_report_date"] = today_str

    # ۱۱. ذخیره اتمیک تمام فایل‌های وضعیت
    state_mgr.save_portfolio(portfolio)
    state_mgr.save_bot_config(bot_config)
    state_mgr.save_strategy_memory(strategy_memory)
    state_mgr.save_shadow_portfolio(shadow_portfolio)
    state_mgr.save_market_regime(regimes_snapshot)
    state_mgr.save_active_setups(portfolio.get("open_positions", []))

    gate_info = state_mgr.get_paper_gate_progress(portfolio)
    duration = round(time.time() - t0, 2)

    return {
        "status": "CYCLE_COMPLETED_V2_5",
        "duration_sec": duration,
        "opened_positions": opened_positions_count,
        "active_positions": len(portfolio.get("open_positions", [])),
        "paper_gate": f"{gate_info['completed_trades']}/{gate_info['target_trades']}",
        "news_shield_active": news_status.get("news_shield_active", False),
        "executed_telegram_commands": executed_commands,
        "regimes": {k: v.get("regime") for k, v in regimes_snapshot.items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Institutional Trading Bot V2.5 - Cloud Orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="اجرای آزمایشی آفلاین بدون شبکه")
    parser.add_argument("--analyze-coin", type=str, default="", help="ارسال فوری چارت و رادار یک ارز خاص")
    args = parser.parse_args()

    result = run_institutional_cycle(
        dry_run=args.dry_run,
        target_analyze_coin=args.analyze_coin if args.analyze_coin else None,
    )
    print(f"✅ [CloudRunner V2.5] Summary: {result}")