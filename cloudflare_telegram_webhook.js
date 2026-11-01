/**
 * وب‌هوک سرورلس کلودفلر برای پاسخگویی آنی (زیر ۱ ثانیه) به دکمه‌های شیشه‌ای تلگرام
 * Institutional Trading Bot V2.5 - Cloudflare Worker Instant Telegram Bridge
 *
 * متغیرهای محیطی (Environment Variables) مورد نیاز در پنل Cloudflare Worker:
 * - TELEGRAM_BOT_TOKEN : توکن ربات تلگرام
 * - TELEGRAM_CHAT_ID   : شناسه عددی چت شما
 * - GITHUB_OWNER       : نام کاربری گیت‌هاب (مثلاً alifarhadisabet86-cmd)
 * - GITHUB_REPO        : نام مخزن (مثلاً crypto-trader-bot)
 * - GITHUB_PAT         : (اختیاری) توکن Personal Access Token گیت‌هاب برای استارت فوری رندر چارت
 */

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Institutional Bot V2.5 Webhook Active ✅", { status: 200 });
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
            text: `⚡ پردازش آنی فرمان: ${rawCmd}`,
          }),
        })
      );
    }

    const cmdUpper = rawCmd.split("@")[0].toUpperCase();

    // ۱. پاسخ آنی به دکمه‌های چارت و تحلیل ۵ ارز (ANLZ_BTC, ANLZ_ETH, ...)
    if (cmdUpper.startsWith("ANLZ_")) {
      const coin = cmdUpper.replace("ANLZ_", "").trim();
      const regimes = await fetchGitHubJson(ghOwner, ghRepo, "state/market_regime.json", env.GITHUB_PAT);
      const rInfo = (regimes && regimes[coin]) || {};

      const text = [
        `⚡ <b>رادار آنی کلودفلر | ${coin}/USDT (تایم‌فریم ۱۵m)</b>`,
        `━━━━━━━━━━━━━━━━━━`,
        `💵 <b>آخرین قیمت ثبت‌شده:</b> <code>${rInfo.current_price ?? "—"}</code>`,
        `🧭 <b>رژیم ۱ ساعته:</b> <code>${rInfo.regime ?? "RANGING"}</code> | <b>بایاس ۴H:</b> <code>${rInfo.htf_bias ?? "NEUTRAL"}</code>`,
        `📐 <b>ناحیه قیمتی:</b> <code>${rInfo.zone ?? "EQUILIBRIUM"}</code>`,
        `🎯 <b>جهت کاندید:</b> <b>${rInfo.candidate_side ?? "NONE"}</b> | <b>امتیاز فازی:</b> <code>${rInfo.confluence_score ?? 0}/100</code>`,
        `🔬 <b>دلایل X-Ray:</b> ${rInfo.xray_summary_fa || "در حال رصد ساختار"}`,
        ``,
        `🖼 <i>درخواست رندر چارت گرافیکی زنده به سرور ارسال شد...</i>`,
      ].join("\n");

      await sendTelegramMessage(botToken, chatId, text);
      if (env.GITHUB_PAT) {
        ctx.waitUntil(triggerGitHubWorkflow(ghOwner, ghRepo, env.GITHUB_PAT, coin));
      }
      return new Response("OK", { status: 200 });
    }

    // ۲. پاسخ آنی به گزارش وضعیت (/status) یا بیلان (/nightly)
    if (cmdUpper === "/STATUS" || cmdUpper === "/START" || cmdUpper === "/NIGHTLY") {
      const pf = await fetchGitHubJson(ghOwner, ghRepo, "state/paper_portfolio.json", env.GITHUB_PAT);
      if (pf) {
        const bal = Number(pf.balance_usdt || 1000).toFixed(2);
        const dPnl = Number(pf.daily_pnl_usdt || 0).toFixed(2);
        const totalTr = (pf.stats && pf.stats.total_trades) || 0;
        const targetTr = pf.paper_gate_target || 50;
        const wr = Number((pf.stats && pf.stats.win_rate_pct) || 0).toFixed(1);
        const openPos = pf.open_positions || [];

        const posLines = openPos.length
          ? openPos.map(
              (p, i) =>
                `  ${i + 1}. <b>${p.coin}</b> (${p.side}) | ورود: <code>${p.entry_price}</code> | PnL: <code>${Number(p.unrealized_pnl_usdt || 0).toFixed(2)}$</code>`
            )
          : ["  └ <i>هیچ پوزیشن بازی وجود ندارد (0/5)</i>"];

        const msg = [
          `⚡ <b>پاسخ آنی اتاق فرمان V2.5 (Cloudflare Edge)</b>`,
          `━━━━━━━━━━━━━━━━━━`,
          `💰 <b>موجودی نقد:</b> <code>$${bal}</code> | <b>سود امروز:</b> <code>${dPnl}$</code>`,
          `🎯 <b>دروازه ۵۰ معامله کاغذی:</b> <code>${totalTr}/${targetTr}</code> (برد: <code>${wr}%</code>)`,
          `📂 <b>پوزیشن‌های باز (${openPos.length}/5):</b>`,
          ...posLines,
        ].join("\n");

        await sendTelegramMessage(botToken, chatId, msg);
      }
      return new Response("OK", { status: 200 });
    }

    // ۳. اکشن‌های ریسک‌فری و سیو سود پله‌ای
    if (cmdUpper === "ACT_RISK_FREE" || cmdUpper === "ACT_SAVE_50") {
      await sendTelegramMessage(
        botToken,
        chatId,
        `⏳ فرمان <code>${cmdUpper}</code> ثبت شد و در اجرای جاری پایپ‌لاین اعمال می‌گردد.`
      );
      if (env.GITHUB_PAT) {
        ctx.waitUntil(triggerGitHubWorkflow(ghOwner, ghRepo, env.GITHUB_PAT, ""));
      }
      return new Response("OK", { status: 200 });
    }

    return new Response("OK", { status: 200 });
  },
};

async function fetchGitHubJson(owner, repo, path, pat) {
  const url = `https://raw.githubusercontent.com/${owner}/${repo}/main/${path}`;
  const headers = { "User-Agent": "Cloudflare-Worker-Bot-V2.5" };
  if (pat) headers["Authorization"] = `Bearer ${pat}`;
  try {
    const r = await fetch(url, { headers });
    if (r.ok) return await r.json();
  } catch {}
  return null;
}

async function triggerGitHubWorkflow(owner, repo, pat, analyzeCoin) {
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/bot_cron.yml/dispatches`;
  try {
    await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${pat}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "Cloudflare-Worker-Bot-V2.5",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: { analyze_coin: analyzeCoin || "" },
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