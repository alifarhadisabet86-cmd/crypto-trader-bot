"""
اسکریپت اجرای لوکال ۲۴ ساعته با حلقه while True و پولینگ زنده تلگرام (Local 24/7 Runner)
Institutional Trading Bot V2 - Continuous Local Execution Engine
"""

import argparse
import sys
import time
from datetime import datetime, timezone

from cloud_runner import run_institutional_cycle
from core.state_manager import StateManager
from skills.alerts import TelegramAlertsSkill
from skills.broker import BrokerExecutionSkill


def run_continuous_loop(interval_minutes: int = 15, poll_seconds: int = 10) -> None:
    """
    حلقه ۲۴ ساعته اجرای ربات در محیط لوکال یا سرور مجازی (VPS):
    - اجرای چرخه کامل معاملاتی هر ۱۵ دقیقه.
    - بررسی دستورات اتاق فرمان تلگرام هر ۱۰ ثانیه در فواصل بین چرخه‌ها.
    """
    interval_sec = max(60, int(interval_minutes * 60))
    poll_sec = max(5, int(poll_seconds))

    state_mgr = StateManager()
    broker = BrokerExecutionSkill()
    alerts = TelegramAlertsSkill()

    print("=" * 72)
    print("🏛️  Institutional Trading Bot V2 — 24/7 Local Runner Started")
    print(f"⏱️  Cycle Interval: {interval_minutes} min | Telegram Poll: every {poll_sec}s")
    print("💡 Press Ctrl+C at any time to stop gracefully.")
    print("=" * 72)

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"\n🚀 [MainLoop] Starting Cycle #{cycle_count} at {now_str} ...")

            summary = run_institutional_cycle(dry_run=False)
            print(
                f"📊 [MainLoop] Cycle #{cycle_count} Result: {summary.get('status')} | "
                f"Duration: {summary.get('duration_sec')}s | "
                f"Regimes: {summary.get('regimes')}"
            )

            # حلقه انتظار تا چرخه بعدی به همراه پولینگ زنده دستورات تلگرام
            elapsed = 0
            while elapsed < interval_sec:
                sleep_chunk = min(poll_sec, interval_sec - elapsed)
                time.sleep(sleep_chunk)
                elapsed += sleep_chunk

                if alerts.is_configured:
                    try:
                        pf = state_mgr.load_portfolio()
                        cfg = state_mgr.load_bot_config()
                        shd = state_mgr.load_shadow_portfolio()
                        cmds = alerts.process_incoming_commands(
                            state_manager=state_mgr,
                            broker=broker,
                            portfolio=pf,
                            bot_config=cfg,
                            shadow_portfolio=shd,
                        )
                        if cmds:
                            print(f"📲 [MainLoop] Executed live Telegram commands: {cmds}")
                    except Exception as poll_err:
                        print(f"⚠️ [MainLoop] Telegram poll warning: {poll_err}")

    except KeyboardInterrupt:
        print("\n🛑 [MainLoop] Graceful shutdown requested by user (Ctrl+C). Exiting safely.")
        sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Institutional Trading Bot V2 - Local Runner"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="اجرای تنها یک چرخه کامل و خروج (مناسب برای تست سریع)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="اجرای آزمایشی چرخه بدون فراخوانی شبکه خارجی",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="فاصله زمانی بین هر چرخه کامل بر حسب دقیقه (پیش‌فرض: ۱۵ دقیقه)",
    )
    args = parser.parse_args()

    if args.once or args.dry_run:
        res = run_institutional_cycle(dry_run=args.dry_run)
        print(f"✅ Single cycle completed: {res['status']}")
        return

    run_continuous_loop(interval_minutes=args.interval)


if __name__ == "__main__":
    main()