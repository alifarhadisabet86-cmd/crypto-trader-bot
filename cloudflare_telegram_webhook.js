/**
 * وب‌هوک سرورلس کلودفلر برای اتصال آنی تلگرام + کرون‌جاب دقیق ۱۵ دقیقه‌ای به موتور پایتون گیت‌هاب اکشنز
 * Institutional Trading Bot V2.5 Pro - Cloudflare Worker Instant Telegram Bridge & 15m Precision Cron
 *
 * متغیرهای محیطی (Environment Variables / Secrets) تعریف‌شده در پنل Cloudflare Worker:
 * - TELEGRAM_BOT_TOKEN : توکن ربات تلگرام
 * - TELEGRAM_CHAT_ID   : شناسه عددی چت ادمین
 * - GITHUB_OWNER       : نام کاربری گیت‌هاب (alifarhadisabet86-cmd)
 * - GITHUB_REPO        : نام مخزن (crypto-trader-bot)
 * - GITHUB_PAT         : توکن دسترسی شخصی گیت‌هاب (دارای دسترسی repo و workflow)
 */

export default {
  async scheduled(event, env, ctx) {
    const ghOwner = (env.GITHUB_OWNER || "alifarhadisabet86-cmd").trim();
    const ghRepo = (env.GITHUB_REPO || "crypto-trader-bot").trim();
    if (env.GITHUB_PAT) {
      ctx.waitUntil(triggerGitHubWorkflow(ghOwner, ghRepo, env.GITHUB_PAT, "", ""));
    }
  },

  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Institutional Bot V2.5 Pro Webhook + 15m Cron Active ✅", { status: 200 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    const botToken = (env.TELEGRAM_BOT_TOKEN || "").trim();
    const allowedChatId = String(env.TELEGRAM_CHAT_ID || "").trim();
    const ghOwner = (env.GITHUB_OWNER || "alifarhadisabet86-cmd").trim();
    const ghRepo = (env.GITHUB_REPO || "crypto-trader-bot").trim();

    if (!botToken) {
      return new Response("Missing TELEGRAM_BOT_TOKEN", { status: 200 });
    }

    let chatId = "";
    let rawCmd = "";
    let callbackId = null;

    if (update.message && update.message.text) {
      chatId = String(update.message.chat.id);
      rawCmd = update.message.text.trim();
    } else if (update.callback_query) {
      chatId = String(update.callback_query.message.chat.id);
      rawCmd = (update.callback_query.data || "").trim();
      callbackId = update.callback_query.id;
    }

    if (!rawCmd || (allowedChatId && chatId !== allowedChatId)) {
      return new Response("OK", { status: 200 });
    }

    if (callbackId) {
      ctx.waitUntil(
        fetch(`https://api.telegram.org/bot${botToken}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            callback_query_id: callbackId,
            text: `⚡ فرمان دریافت شد: ${rawCmd}`,
          }),
        })
      );
    }

    const cmdUpper = rawCmd.split("@")[0].trim().toUpperCase();

    // ۱. دکمه‌های شیشه‌ای چارت و تحلیل ۵ ارز (ANLZ_BTC, ANLZ_ETH, ANLZ_SOL, ANLZ_XRP, ANLZ_XAU)
    if (cmdUpper.startsWith("ANLZ_")) {
      const coin = cmdUpper.replace("ANLZ_", "").trim();
      await sendTelegramMessage(
        botToken,
        chatId,
        `⏳ <b>درخواست تحلیل و رندر چارت دوطبقه <code>${coin}/USDT</code> به موتور پایتون ارسال شد...</b>\n<i>در حال دریافت کندل‌های زنده صرافی و رسم گرافیک...</i>`
      );
      if (env.GITHUB_PAT) {
        ctx.waitUntil(triggerGitHubWorkflow(ghOwner, ghRepo, env.GITHUB_PAT, coin, ""));
      }
      return new Response("OK", { status: 200 });
    }

    // ۲. گزارش جامع وضعیت (/status, /start) و بیلان شبانه (/nightly) با عکس منحنی سرمایه و PnL زنده
    if (cmdUpper === "/STATUS" || cmdUpper === "/START" || cmdUpper === "/NIGHTLY") {
      await sendTelegramMessage(
        botToken,
        chatId,
        `⏳ <b>درخواست گزارش <code>${cmdUpper}</code> به موتور پایتون ارسال شد...</b>\n<i>در حال بروزرسانی قیمت‌های لحظه‌ای، محاسبه PnL شناور و رندر چارت منحنی سرمایه...</i>`
      );
      if (env.GITHUB_PAT) {
        ctx.waitUntil(triggerGitHubWorkflow(ghOwner, ghRepo, env.GITHUB_PAT, "", cmdUpper.toLowerCase()));
      }
      return new Response("OK", { status: 200 });
    }

    // ۳. اکشن‌های مدیریتی فوری (ACT_RISK_FREE, ACT_SAVE_50) و دستورات کنترلی (/pause, /resume, /panic, /reset, /risk)
    if (
      cmdUpper === "ACT_RISK_FREE" ||
      cmdUpper === "ACT_SAVE_50" ||
      cmdUpper === "/RISKFREE" ||
      cmdUpper === "/SAVE50" ||
      cmdUpper === "/PAUSE" ||
      cmdUpper === "/RESUME" ||
      cmdUpper === "/UNPAUSE" ||
      cmdUpper === "/PANIC" ||
      cmdUpper === "/CLOSE_ALL" ||
      cmdUpper === "/RESET" ||
      cmdUpper.startsWith("/RISK")
    ) {
      await sendTelegramMessage(
        botToken,
        chatId,
        `⏳ فرمان <code>${rawCmd}</code> به موتور پایتون ارسال شد و در حال اجرا روی پوزیشن‌های باز است...`
      );
      if (env.GITHUB_PAT) {
        ctx.waitUntil(triggerGitHubWorkflow(ghOwner, ghRepo, env.GITHUB_PAT, "", rawCmd));
      }
      return new Response("OK", { status: 200 });
    }

    return new Response("OK", { status: 200 });
  },
};

async function triggerGitHubWorkflow(owner, repo, pat, analyzeCoin, telegramCommand = "") {
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/bot_cron.yml/dispatches`;
  try {
    await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${pat}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "Cloudflare-Worker-Bot-V2.5-Pro",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          analyze_coin: analyzeCoin || "",
          telegram_command: telegramCommand || "",
        },
      }),
    });
  } catch {}
}

async function sendTelegramMessage(botToken, chatId, text) {
  await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    }),
  });
}
