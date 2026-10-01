/**
 * Telegram webhook:
 *  - instant /scan → GitHub Actions
 *  - shared /settings wizard (group-wide filters in Cloudflare KV)
 *
 * Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, GITHUB_TOKEN, GITHUB_REPO, CONFIG_TOKEN
 * KV binding: SETTINGS
 */

import defaultConfig from "./default-config.json";

const SCAN = new Set(["/scan", "/search", "/run"]);
const HELP = new Set(["/start", "/help"]);
const ID = new Set(["/id", "/chatid"]);
const SETTINGS = new Set(["/settings", "/filters", "/config"]);

/** Fixed city catalog — buttons avoid misspelling */
const CITIES = [
  { slug: "toronto", label: "Toronto" },
  { slug: "richmond-hill", label: "Richmond Hill" },
  { slug: "brampton", label: "Brampton" },
  { slug: "north-york", label: "North York" },
  { slug: "vaughan", label: "Vaughan" },
  { slug: "markham", label: "Markham" },
  { slug: "east-york", label: "East York" },
  { slug: "mississauga", label: "Mississauga" },
  { slug: "scarborough", label: "Scarborough" },
  { slug: "hamilton", label: "Hamilton" },
];

function authorized(chatId, env) {
  return String(env.TELEGRAM_CHAT_IDS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .includes(String(chatId));
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

async function getConfig(env) {
  const raw = await env.SETTINGS.get("config");
  if (!raw) {
    await env.SETTINGS.put("config", JSON.stringify(defaultConfig));
    return structuredClone(defaultConfig);
  }
  return JSON.parse(raw);
}

async function saveConfig(env, cfg) {
  await env.SETTINGS.put("config", JSON.stringify(cfg));
}

async function getWizard(env, chatId) {
  const raw = await env.SETTINGS.get(`wizard:${chatId}`);
  return raw ? JSON.parse(raw) : null;
}

async function setWizard(env, chatId, state) {
  if (!state) {
    await env.SETTINGS.delete(`wizard:${chatId}`);
    return;
  }
  await env.SETTINGS.put(`wizard:${chatId}`, JSON.stringify(state), {
    expirationTtl: 60 * 60,
  });
}

function formatSettings(cfg) {
  const lines = ["⚙️ <b>Current shared settings</b>", ""];
  lines.push(`⏱ Max mileage: <b>${cfg.max_mileage_km?.toLocaleString() || "n/a"} km</b>`);
  lines.push("");
  lines.push("<b>Cities</b>");
  lines.push((cfg.location_keywords || []).map((c) => `• ${c}`).join("\n") || "• (none)");
  lines.push("");
  (cfg.searches || []).forEach((s, i) => {
    lines.push(`<b>${i + 1}. ${escapeHtml(s.name)}</b>`);
    lines.push(`   Query: <code>${escapeHtml(s.query)}</code>`);
    lines.push(`   Years: ${s.min_year}–${s.max_year}`);
    lines.push(`   Price: $${s.min_price}–$${s.max_price}`);
    if (s.powertrain_any?.length) {
      lines.push(`   Powertrain: ${s.powertrain_any.join(", ")}`);
    }
    lines.push("");
  });
  lines.push("Use buttons below, or /settings anytime.");
  return lines.join("\n");
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function mainKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "👀 View settings", callback_data: "set:view" },
        { text: "🚗 Edit / add car", callback_data: "set:cars" },
      ],
      [
        { text: "📍 Cities", callback_data: "set:cities" },
        { text: "⏱ Max km", callback_data: "set:mileage" },
      ],
      [{ text: "❌ Close", callback_data: "set:close" }],
    ],
  };
}

function carsKeyboard(cfg) {
  const rows = (cfg.searches || []).map((s, i) => [
    { text: `✏️ ${s.name}`, callback_data: `car:edit:${i}` },
    { text: "🗑 Delete", callback_data: `car:delask:${i}` },
  ]);
  rows.push([{ text: "➕ Add new car search", callback_data: "car:add" }]);
  rows.push([{ text: "⬅️ Back to menu", callback_data: "set:menu" }]);
  return { inline_keyboard: rows };
}

/** Cancel (+ optional Keep / quick picks) under every wizard prompt */
function wizardKeyboard({ keepLabel, keepData, extras } = {}) {
  const rows = [];
  if (extras?.length) rows.push(...extras);
  if (keepLabel && keepData) {
    rows.push([{ text: keepLabel, callback_data: keepData }]);
  }
  rows.push([
    { text: "❌ Cancel", callback_data: "wiz:cancel" },
    { text: "⬅️ Cars list", callback_data: "wiz:tocars" },
  ]);
  return { inline_keyboard: rows };
}

function hybridKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "Yes — prefer hybrid", callback_data: "car:hybrid:yes" },
        { text: "No", callback_data: "car:hybrid:no" },
      ],
      [
        { text: "❌ Cancel", callback_data: "wiz:cancel" },
        { text: "⬅️ Cars list", callback_data: "wiz:tocars" },
      ],
    ],
  };
}

async function cancelWizard(env, chatId, { editMessageId } = {}) {
  await setWizard(env, chatId, null);
  const cfg = await getConfig(env);
  const payload = {
    chat_id: chatId,
    text: "❌ Cancelled — nothing saved.\n\n" + formatSettings(cfg),
    parse_mode: "HTML",
    reply_markup: mainKeyboard(),
  };
  if (editMessageId) {
    await tg(env, "editMessageText", { ...payload, message_id: editMessageId });
  } else {
    await tg(env, "sendMessage", payload);
  }
}

async function promptCarName(env, chatId, wizard, { editing } = {}) {
  const draft = wizard.draft || {};
  const extras = editing
    ? []
    : [
        [
          { text: "Mazda 3", callback_data: "wiz:pick:Mazda 3" },
          { text: "Kia Optima Hybrid", callback_data: "wiz:pick:Kia Optima Hybrid" },
        ],
      ];
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text: editing
      ? `✏️ Editing <b>${escapeHtml(draft.name || "car")}</b>\n\n` +
        "🚗 <b>Step 1/5 — Car name</b>\n" +
        `Current: <code>${escapeHtml(draft.name || "")}</code>\n` +
        "Type a new name, or tap Keep."
      : "🚗 <b>Step 1/5 — Car name</b>\n" +
        "What car should we search?\n\n" +
        "Tap an example, or type your own:\n" +
        "• <code>Mazda 3</code>\n" +
        "• <code>Kia Optima Hybrid</code>\n" +
        "• <code>Honda Civic</code>",
    parse_mode: "HTML",
    reply_markup: wizardKeyboard({
      keepLabel: editing && draft.name ? `✅ Keep “${draft.name}”` : null,
      keepData: editing && draft.name ? "wiz:keep" : null,
      extras,
    }),
  });
}

async function promptCarQuery(env, chatId, wizard) {
  const draft = wizard.draft || {};
  const suggestion = draft.query || draft.name || "";
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "🔎 <b>Step 2/5 — Facebook search text</b>\n" +
      "What should we type into Marketplace?\n\n" +
      "Examples: <code>mazda 3</code> · <code>kia optima hybrid</code>\n" +
      (suggestion
        ? `\nSuggested: <code>${escapeHtml(suggestion.toLowerCase())}</code>`
        : ""),
    parse_mode: "HTML",
    reply_markup: wizardKeyboard({
      keepLabel: suggestion ? `✅ Use “${suggestion.toLowerCase()}”` : null,
      keepData: suggestion ? "wiz:keep" : null,
    }),
  });
}

async function promptCarYears(env, chatId, wizard) {
  const draft = wizard.draft || {};
  const has =
    draft.min_year != null && draft.max_year != null
      ? `${draft.min_year}-${draft.max_year}`
      : "";
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "📅 <b>Step 3/5 — Years</b>\n" +
      "Type a range like <code>2010-2014</code>\n" +
      "Example (Optima): <code>2011-2017</code>" +
      (has ? `\n\nCurrent: <code>${has}</code>` : ""),
    parse_mode: "HTML",
    reply_markup: wizardKeyboard({
      keepLabel: has ? `✅ Keep ${has}` : null,
      keepData: has ? "wiz:keep" : null,
      extras: [
        [
          { text: "2010–2014", callback_data: "wiz:years:2010-2014" },
          { text: "2011–2017", callback_data: "wiz:years:2011-2017" },
        ],
        [
          { text: "2012–2018", callback_data: "wiz:years:2012-2018" },
          { text: "2015–2020", callback_data: "wiz:years:2015-2020" },
        ],
      ],
    }),
  });
}

async function promptCarPrice(env, chatId, wizard) {
  const draft = wizard.draft || {};
  const has =
    draft.min_price != null && draft.max_price != null
      ? `${draft.min_price}-${draft.max_price}`
      : "";
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "💰 <b>Step 4/5 — Price (CAD)</b>\n" +
      "Type a range like <code>300-2300</code>\n" +
      "Example: <code>1000-3000</code>" +
      (has ? `\n\nCurrent: <code>$${has}</code>` : ""),
    parse_mode: "HTML",
    reply_markup: wizardKeyboard({
      keepLabel: has ? `✅ Keep $${has}` : null,
      keepData: has ? "wiz:keep" : null,
      extras: [
        [
          { text: "$300–2300", callback_data: "wiz:price:300-2300" },
          { text: "$1000–3000", callback_data: "wiz:price:1000-3000" },
        ],
        [
          { text: "$500–5000", callback_data: "wiz:price:500-5000" },
          { text: "$1000–8000", callback_data: "wiz:price:1000-8000" },
        ],
      ],
    }),
  });
}

async function promptCarHybrid(env, chatId) {
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "🔋 <b>Step 5/5 — Hybrid preference</b>\n" +
      "Optional note for the search name. Marketplace still searches your query text.\n" +
      "Optima Hybrid → Yes · Mazda 3 → No",
    parse_mode: "HTML",
    reply_markup: hybridKeyboard(),
  });
}

/** Advance wizard after a value for the current step is chosen */
async function advanceCarWizard(env, chatId, wizard) {
  const draft = wizard.draft || {};
  if (wizard.step === "car_name") {
    if (!draft.name) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Please choose or type a car name.",
        reply_markup: wizardKeyboard(),
      });
      return;
    }
    if (!draft.query) draft.query = draft.name.toLowerCase();
    wizard.draft = draft;
    wizard.step = "car_query";
    await setWizard(env, chatId, wizard);
    await promptCarQuery(env, chatId, wizard);
    return;
  }
  if (wizard.step === "car_query") {
    if (!draft.query) draft.query = draft.name;
    wizard.draft = draft;
    wizard.step = "car_years";
    await setWizard(env, chatId, wizard);
    await promptCarYears(env, chatId, wizard);
    return;
  }
  if (wizard.step === "car_years") {
    if (draft.min_year == null || draft.max_year == null) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Pick a year range or type <code>2010-2014</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return;
    }
    wizard.step = "car_price";
    await setWizard(env, chatId, wizard);
    await promptCarPrice(env, chatId, wizard);
    return;
  }
  if (wizard.step === "car_price") {
    if (draft.min_price == null || draft.max_price == null) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Pick a price range or type <code>300-2300</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return;
    }
    wizard.step = "car_hybrid";
    await setWizard(env, chatId, wizard);
    await promptCarHybrid(env, chatId);
  }
}

function citiesKeyboard(selectedSlugs) {
  const selected = new Set(selectedSlugs || []);
  const rows = [];
  for (let i = 0; i < CITIES.length; i += 2) {
    const row = [];
    for (let j = i; j < i + 2 && j < CITIES.length; j++) {
      const c = CITIES[j];
      const on = selected.has(c.slug);
      row.push({
        text: `${on ? "✅" : "⬜"} ${c.label}`,
        callback_data: `city:toggle:${c.slug}`,
      });
    }
    rows.push(row);
  }
  rows.push([
    { text: "✅ All", callback_data: "city:all" },
    { text: "⬜ None", callback_data: "city:none" },
  ]);
  rows.push([
    { text: "💾 Save cities", callback_data: "city:save" },
    { text: "⬅️ Back", callback_data: "set:menu" },
  ]);
  return { inline_keyboard: rows };
}

function mileageKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "150,000", callback_data: "km:150000" },
        { text: "200,000", callback_data: "km:200000" },
      ],
      [
        { text: "250,000", callback_data: "km:250000" },
        { text: "300,000", callback_data: "km:300000" },
      ],
      [{ text: "⌨️ Type custom km", callback_data: "km:custom" }],
      [
        { text: "❌ Cancel", callback_data: "set:menu" },
        { text: "⬅️ Back", callback_data: "set:menu" },
      ],
    ],
  };
}

function syncLocationsFromKeywords(cfg) {
  const labels = new Set(cfg.location_keywords || []);
  cfg.locations = CITIES.filter((c) => labels.has(c.label)).map((c) => c.slug);
  if (!cfg.locations.length) {
    cfg.locations = CITIES.map((c) => c.slug);
  }
}

function buildSearchFromWizard(draft) {
  const query = (draft.query || draft.name || "").trim();
  const qLower = query.toLowerCase();
  const name = (draft.name || query).trim();
  const hybrid = !!draft.hybrid;
  const searches = {
    name,
    query: qLower,
    queries: [qLower],
    min_year: draft.min_year,
    max_year: draft.max_year,
    min_price: draft.min_price ?? 0,
    max_price: draft.max_price ?? 999999,
    must_include_any: qLower.split(/\s+/).filter(Boolean).slice(0, 3),
    must_include_all: [],
    powertrain_any: hybrid
      ? ["hybrid", "hev", "phev", "plug-in", "plugin", "plug in"]
      : [],
    body_styles: [],
    require_body_style: false,
    require_mileage: false,
  };
  // Extra query variants for mazda3-style
  if (!searches.queries.includes(qLower.replace(/\s+/g, ""))) {
    searches.queries.push(qLower.replace(/\s+/g, ""));
  }
  if (!searches.must_include_any.length) {
    searches.must_include_any = [qLower];
  }
  return searches;
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
    throw new Error(`GitHub dispatch ${res.status}: ${await res.text()}`);
  }
}

async function handleCallback(env, cq) {
  const chatId = cq.message.chat.id;
  const data = cq.data || "";

  if (!authorized(chatId, env)) {
    await tg(env, "answerCallbackQuery", {
      callback_query_id: cq.id,
      text: "Not authorized",
      show_alert: true,
    });
    return;
  }

  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id });

  const cfg = await getConfig(env);
  let wizard = (await getWizard(env, chatId)) || {};

  if (data === "set:close") {
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: "Settings closed.",
    });
    return;
  }

  if (data === "set:menu" || data === "set:view") {
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: mainKeyboard(),
    });
    return;
  }

  if (data === "set:cars") {
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: "🚗 Choose a search to edit, or add a new one:",
      reply_markup: carsKeyboard(cfg),
    });
    return;
  }

  if (data === "set:cities") {
    const selected = CITIES.filter((c) =>
      (cfg.location_keywords || []).includes(c.label)
    ).map((c) => c.slug);
    wizard = { step: "cities", selected };
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        "📍 Tap cities to turn ✅ on / ⬜ off.\n" +
        "No typing needed (avoids misspellings like Vaugan/Margham).",
      reply_markup: citiesKeyboard(selected),
    });
    return;
  }

  if (data.startsWith("city:")) {
    const selected = new Set(wizard.selected || []);
    if (data.startsWith("city:toggle:")) {
      const slug = data.split(":")[2];
      if (selected.has(slug)) selected.delete(slug);
      else selected.add(slug);
    } else if (data === "city:all") {
      CITIES.forEach((c) => selected.add(c.slug));
    } else if (data === "city:none") {
      selected.clear();
    } else if (data === "city:save") {
      cfg.location_keywords = CITIES.filter((c) => selected.has(c.slug)).map(
        (c) => c.label
      );
      syncLocationsFromKeywords(cfg);
      await saveConfig(env, cfg);
      await setWizard(env, chatId, null);
      await tg(env, "editMessageText", {
        chat_id: chatId,
        message_id: cq.message.message_id,
        text: formatSettings(cfg),
        parse_mode: "HTML",
        reply_markup: mainKeyboard(),
      });
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "✅ Cities saved for everyone in this group.",
      });
      return;
    }
    wizard.selected = [...selected];
    wizard.step = "cities";
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        "📍 Tap cities to turn ✅ on / ⬜ off.\n" +
        "No typing needed (avoids misspellings).",
      reply_markup: citiesKeyboard([...selected]),
    });
    return;
  }

  if (data === "set:mileage") {
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `⏱ Current max mileage: ${cfg.max_mileage_km} km\nChoose a value:`,
      reply_markup: mileageKeyboard(),
    });
    return;
  }

  if (data.startsWith("km:")) {
    if (data === "km:custom") {
      await setWizard(env, chatId, { step: "mileage_custom" });
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Type max mileage in km.\nExample: <code>250000</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return;
    }
    const km = Number(data.split(":")[1]);
    cfg.max_mileage_km = km;
    await saveConfig(env, cfg);
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: mainKeyboard(),
    });
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `✅ Max mileage set to ${km.toLocaleString()} km`,
    });
    return;
  }

  if (data === "wiz:cancel") {
    await cancelWizard(env, chatId, { editMessageId: cq.message.message_id });
    return;
  }

  if (data === "wiz:tocars") {
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: "🚗 Choose a search to edit, or add a new one:",
      reply_markup: carsKeyboard(cfg),
    });
    return;
  }

  if (data === "wiz:keep") {
    if (!wizard.step) return;
    await advanceCarWizard(env, chatId, wizard);
    return;
  }

  if (data.startsWith("wiz:pick:")) {
    if (wizard.step !== "car_name") return;
    const name = data.slice("wiz:pick:".length);
    wizard.draft = wizard.draft || {};
    wizard.draft.name = name;
    wizard.draft.query = name.toLowerCase();
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return;
  }

  if (data.startsWith("wiz:years:")) {
    if (wizard.step !== "car_years") return;
    const [a, b] = data.slice("wiz:years:".length).split("-").map(Number);
    wizard.draft = wizard.draft || {};
    wizard.draft.min_year = a;
    wizard.draft.max_year = b;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return;
  }

  if (data.startsWith("wiz:price:")) {
    if (wizard.step !== "car_price") return;
    const [a, b] = data.slice("wiz:price:".length).split("-").map(Number);
    wizard.draft = wizard.draft || {};
    wizard.draft.min_price = a;
    wizard.draft.max_price = b;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return;
  }

  if (data === "car:add") {
    const w = { step: "car_name", draft: {}, index: -1 };
    await setWizard(env, chatId, w);
    await promptCarName(env, chatId, w, { editing: false });
    return;
  }

  if (data.startsWith("car:edit:")) {
    const index = Number(data.split(":")[2]);
    const s = cfg.searches[index];
    if (!s) return;
    const w = {
      step: "car_name",
      index,
      draft: {
        name: s.name,
        query: s.query,
        min_year: s.min_year,
        max_year: s.max_year,
        min_price: s.min_price,
        max_price: s.max_price,
        hybrid: !!(s.powertrain_any && s.powertrain_any.length),
      },
    };
    await setWizard(env, chatId, w);
    await promptCarName(env, chatId, w, { editing: true });
    return;
  }

  if (data.startsWith("car:delask:")) {
    const index = Number(data.split(":")[2]);
    const s = cfg.searches[index];
    if (!s) return;
    if ((cfg.searches || []).length <= 1) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "⚠️ Keep at least one car search.",
      });
      return;
    }
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `🗑 Delete <b>${escapeHtml(s.name)}</b>?\nThis affects the whole group.`,
      parse_mode: "HTML",
      reply_markup: {
        inline_keyboard: [
          [
            { text: "Yes, delete", callback_data: `car:del:${index}` },
            { text: "❌ Cancel", callback_data: "set:cars" },
          ],
        ],
      },
    });
    return;
  }

  if (data.startsWith("car:del:")) {
    const index = Number(data.split(":")[2]);
    if ((cfg.searches || []).length <= 1) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "⚠️ Keep at least one car search.",
      });
      return;
    }
    const removed = cfg.searches.splice(index, 1)[0];
    await saveConfig(env, cfg);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `🗑 Removed <b>${escapeHtml(removed?.name || "search")}</b>\n\n` + formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: mainKeyboard(),
    });
    return;
  }

  if (data === "car:hybrid:yes" || data === "car:hybrid:no") {
    if (wizard.step !== "car_hybrid") return;
    wizard.draft.hybrid = data.endsWith("yes");
    const search = buildSearchFromWizard(wizard.draft);
    if (wizard.index >= 0) cfg.searches[wizard.index] = search;
    else cfg.searches.push(search);
    await saveConfig(env, cfg);
    await setWizard(env, chatId, null);
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `✅ Saved search <b>${escapeHtml(search.name)}</b> for the whole group.\n\n` + formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: mainKeyboard(),
    });
  }
}

async function handleWizardText(env, chatId, text) {
  const wizard = await getWizard(env, chatId);
  if (!wizard?.step) return false;
  if (text.startsWith("/")) {
    const cmd = text.split(/\s+/)[0].split("@")[0].toLowerCase();
    if (cmd === "/cancel") {
      await cancelWizard(env, chatId);
      return true;
    }
  }

  const cfg = await getConfig(env);
  const draft = wizard.draft || {};
  const trimmed = text.trim();

  if (wizard.step === "mileage_custom") {
    const km = Number(String(trimmed).replace(/[,\s]/g, ""));
    if (!Number.isFinite(km) || km < 1000) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Invalid km. Example: <code>250000</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return true;
    }
    cfg.max_mileage_km = Math.round(km);
    await saveConfig(env, cfg);
    await setWizard(env, chatId, null);
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `✅ Max mileage set to ${cfg.max_mileage_km.toLocaleString()} km`,
      reply_markup: mainKeyboard(),
    });
    return true;
  }

  if (wizard.step === "car_name") {
    draft.name = trimmed === "." ? draft.name : trimmed;
    wizard.draft = draft;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return true;
  }

  if (wizard.step === "car_query") {
    draft.query = trimmed === "." ? draft.name : trimmed;
    wizard.draft = draft;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return true;
  }

  if (wizard.step === "car_years") {
    const m = trimmed.match(/^(\d{4})\s*[-–to]+\s*(\d{4})$/i);
    if (!m) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Use format <code>2010-2014</code> or tap a button.",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard({
          keepLabel:
            draft.min_year != null
              ? `✅ Keep ${draft.min_year}-${draft.max_year}`
              : null,
          keepData: draft.min_year != null ? "wiz:keep" : null,
          extras: [
            [
              { text: "2010–2014", callback_data: "wiz:years:2010-2014" },
              { text: "2011–2017", callback_data: "wiz:years:2011-2017" },
            ],
          ],
        }),
      });
      return true;
    }
    draft.min_year = Number(m[1]);
    draft.max_year = Number(m[2]);
    wizard.draft = draft;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return true;
  }

  if (wizard.step === "car_price") {
    const m = trimmed.match(/^(\d+)\s*[-–to]+\s*(\d+)$/i);
    if (!m) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Use format <code>300-2300</code> or tap a button.",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard({
          keepLabel:
            draft.min_price != null
              ? `✅ Keep $${draft.min_price}-${draft.max_price}`
              : null,
          keepData: draft.min_price != null ? "wiz:keep" : null,
          extras: [
            [
              { text: "$300–2300", callback_data: "wiz:price:300-2300" },
              { text: "$1000–3000", callback_data: "wiz:price:1000-3000" },
            ],
          ],
        }),
      });
      return true;
    }
    draft.min_price = Number(m[1]);
    draft.max_price = Number(m[2]);
    wizard.draft = draft;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return true;
  }

  return false;
}

async function handleScan(env, chatId) {
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
    const raw = String(err.message || err);
    let hint = "See GUIDE.html → Errors.";
    if (raw.includes("401") || raw.includes("Bad credentials")) {
      hint = "Fix: refresh GITHUB_TOKEN on the Cloudflare Worker.";
    } else if (raw.includes("404")) {
      hint = "Fix: check GITHUB_REPO / marketplace.yml on main.";
    } else if (raw.includes("403")) {
      hint = "Fix: GitHub token needs Actions: write.";
    }
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `❌ Failed to start GitHub scan:\n${raw}\n\n${hint}`,
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Live config for GitHub Actions
    if (request.method === "GET" && url.pathname === "/config") {
      const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
      if (!token || token !== env.CONFIG_TOKEN) {
        return new Response("unauthorized", { status: 401 });
      }
      const cfg = await getConfig(env);
      return Response.json(cfg);
    }

    if (request.method !== "POST") {
      return new Response("ok");
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    try {
      if (update.callback_query) {
        await handleCallback(env, update.callback_query);
        return new Response("ok");
      }

      const msg = update.message;
      if (!msg) return new Response("ok");
      const chatId = msg.chat.id;
      const text = (msg.text || "").trim();
      if (!text) return new Response("ok");

      const cmd = text.split(/\s+/)[0].split("@")[0].toLowerCase();

      if (await handleWizardText(env, chatId, text)) {
        return new Response("ok");
      }

      if (ID.has(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text: `Chat id: ${chatId}\nType: ${msg.chat.type}\nTitle: ${msg.chat.title || msg.chat.first_name || "n/a"}`,
        });
        return new Response("ok");
      }

      if (HELP.has(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text:
            "🇨🇦 Canada Marketplace car alerts\n\n" +
            "/scan — start search now\n" +
            "/settings — view/change shared filters\n" +
            "/id — show chat id\n" +
            "/help — this message\n\n" +
            "Settings are shared by the whole group.",
        });
        return new Response("ok");
      }

      if (SETTINGS.has(cmd)) {
        if (!authorized(chatId, env)) {
          await tg(env, "sendMessage", {
            chat_id: chatId,
            text: `⚠️ Not authorized.\nChat id: ${chatId}`,
          });
          return new Response("ok");
        }
        const cfg = await getConfig(env);
        await setWizard(env, chatId, null);
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text: formatSettings(cfg),
          parse_mode: "HTML",
          reply_markup: mainKeyboard(),
        });
        return new Response("ok");
      }

      if (SCAN.has(cmd)) {
        if (!authorized(chatId, env)) {
          await tg(env, "sendMessage", {
            chat_id: chatId,
            text: `⚠️ Not authorized.\nChat id: ${chatId}`,
          });
          return new Response("ok");
        }
        await handleScan(env, chatId);
        return new Response("ok");
      }
    } catch (err) {
      return new Response(String(err), { status: 500 });
    }

    return new Response("ok");
  },
};
