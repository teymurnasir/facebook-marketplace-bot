/**
 * Telegram webhook → instant /scan → GitHub Actions marketplace.yml
 *
 * Env vars (Cloudflare Worker secrets):
 *   TELEGRAM_BOT_TOKEN
 *   TELEGRAM_CHAT_IDS   comma-separated authorized chat ids
 *   GITHUB_TOKEN        PAT with "actions:write" (or classic repo+workflow)
 *   GITHUB_REPO         e.g. teymurnasir/facebook-marketplace-bot
 */

const COMMANDS = new Set(["/scan", "/search", "/run"]);
const HELP = new Set(["/start", "/help"]);
const ID = new Set(["/id", "/chatid"]);

function authorized(chatId, env) {
  const allowed = String(env.TELEGRAM_CHAT_IDS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return allowed.includes(String(chatId));
}

async function tg(env, method, body) {
  const res = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  return res.json();
}

async function dispatchScan(env) {
  const [owner, repo] = String(env.GITHUB_REPO).split("/");
  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/marketplace.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "marketplace-telegram-webhook",
      },
      body: JSON.stringify({ ref: "main" }),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub dispatch ${res.status}: ${text}`);
  }
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    const msg = update.message;
    if (!msg || !msg.text) {
      return new Response("ok");
    }

    const chatId = msg.chat.id;
    const cmd = msg.text.trim().split(/\s+/)[0].split("@")[0].toLowerCase();

    try {
      if (ID.has(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text:
            `Chat id: ${chatId}\n` +
            `Type: ${msg.chat.type}\n` +
            `Title: ${msg.chat.title || msg.chat.first_name || "n/a"}`,
        });
        return new Response("ok");
      }

      if (HELP.has(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text:
            "🇨🇦 Canada Marketplace car alerts\n\n" +
            "/scan — start search now (instant)\n" +
            "/id — show this chat id\n" +
            "/help — this message\n\n" +
            "Also runs automatically every 30 minutes.",
        });
        return new Response("ok");
      }

      if (COMMANDS.has(cmd)) {
        if (!authorized(chatId, env)) {
          await tg(env, "sendMessage", {
            chat_id: chatId,
            text:
              "⚠️ This chat is not authorized.\n" +
              `Chat id: ${chatId}\n` +
              "Add it to TELEGRAM_CHAT_IDS on the webhook.",
          });
          return new Response("ok");
        }

        await tg(env, "sendMessage", {
          chat_id: chatId,
          text:
            "🔎 Scan request received!\n" +
            "⏳ Starting Marketplace search on GitHub now…\n" +
            "⏱ Usually 3–15 minutes.\n" +
            "📬 Only NEW cars will be posted (no duplicates).",
        });

        try {
          await dispatchScan(env);
          await tg(env, "sendMessage", {
            chat_id: chatId,
            text: "🚀 Marketplace scan started immediately.",
          });
        } catch (err) {
          await tg(env, "sendMessage", {
            chat_id: chatId,
            text: `❌ Failed to start GitHub scan:\n${String(err.message || err)}`,
          });
        }
        return new Response("ok");
      }
    } catch (err) {
      return new Response(String(err), { status: 500 });
    }

    return new Response("ok");
  },
};
