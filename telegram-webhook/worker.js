/**
 * Canada-only Marketplace Telegram webhook
 *  - /scan — shared saved settings
 *  - /settings — shared filters (cars, per-car km, locations + radius)
 *  - /customsearch — one-off search (not saved)
 *
 * Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, GITHUB_TOKEN, GITHUB_REPO, CONFIG_TOKEN
 * KV: SETTINGS
 */

import defaultConfig from "./default-config.json";

const SCAN = new Set(["/scan", "/search", "/run"]);
const HELP = new Set(["/start", "/help"]);
const ID = new Set(["/id", "/chatid"]);
const SETTINGS = new Set(["/settings", "/filters", "/config"]);
const CUSTOM = new Set(["/customsearch", "/custom", "/oneshot"]);

const CANADA_NOTE = "🇨🇦 <b>Canada only</b> — locations & prices are for Canadian Marketplace.";

/** Curated Facebook Marketplace city slugs (Canada) — tap to avoid misspelling */
const CANADA_CITIES = [
  { slug: "toronto", label: "Toronto, ON" },
  { slug: "richmond-hill", label: "Richmond Hill, ON" },
  { slug: "brampton", label: "Brampton, ON" },
  { slug: "north-york", label: "North York, ON" },
  { slug: "vaughan", label: "Vaughan, ON" },
  { slug: "markham", label: "Markham, ON" },
  { slug: "east-york", label: "East York, ON" },
  { slug: "mississauga", label: "Mississauga, ON" },
  { slug: "scarborough", label: "Scarborough, ON" },
  { slug: "hamilton", label: "Hamilton, ON" },
  { slug: "oakville", label: "Oakville, ON" },
  { slug: "burlington", label: "Burlington, ON" },
  { slug: "ajax", label: "Ajax, ON" },
  { slug: "pickering", label: "Pickering, ON" },
  { slug: "oshawa", label: "Oshawa, ON" },
  { slug: "barrie", label: "Barrie, ON" },
  { slug: "kitchener", label: "Kitchener, ON" },
  { slug: "waterloo", label: "Waterloo, ON" },
  { slug: "london", label: "London, ON" },
  { slug: "ottawa", label: "Ottawa, ON" },
  { slug: "niagara-falls", label: "Niagara Falls, ON" },
  { slug: "windsor", label: "Windsor, ON" },
  { slug: "kingston", label: "Kingston, ON" },
  { slug: "montreal", label: "Montreal, QC" },
  { slug: "quebec-city", label: "Quebec City, QC" },
  { slug: "laval", label: "Laval, QC" },
  { slug: "gatineau", label: "Gatineau, QC" },
  { slug: "vancouver", label: "Vancouver, BC" },
  { slug: "burnaby", label: "Burnaby, BC" },
  { slug: "surrey", label: "Surrey, BC" },
  { slug: "victoria", label: "Victoria, BC" },
  { slug: "calgary", label: "Calgary, AB" },
  { slug: "edmonton", label: "Edmonton, AB" },
  { slug: "winnipeg", label: "Winnipeg, MB" },
  { slug: "saskatoon", label: "Saskatoon, SK" },
  { slug: "regina", label: "Regina, SK" },
  { slug: "halifax", label: "Halifax, NS" },
  { slug: "st-johns", label: "St. John's, NL" },
];

/** User-facing km → Facebook mile radius (FB URL uses miles) */
const RADIUS_OPTS = [
  { km: 16, label: "16 km" },
  { km: 32, label: "32 km" },
  { km: 65, label: "65 km" },
  { km: 100, label: "100 km" },
  { km: 160, label: "160 km" },
  { km: 400, label: "400 km" },
];

const KM_OPTS = [100000, 150000, 200000, 250000, 300000, 400000];

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

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function normalizeConfig(cfg) {
  const out = structuredClone(cfg || defaultConfig);
  out.country = "CA";
  out.max_mileage_km = out.max_mileage_km || 250000;
  if (!Array.isArray(out.market_areas) || !out.market_areas.length) {
    const locs = out.locations || [];
    out.market_areas = locs.map((slug) => {
      const hit = CANADA_CITIES.find((c) => c.slug === slug);
      return {
        slug,
        label: hit?.label || String(slug).replaceAll("-", " "),
        radius_km: 65,
      };
    });
  }
  out.locations = out.market_areas.map((a) => a.slug);
  out.location_keywords = out.location_keywords || [];
  out.searches = (out.searches || []).map((s) => ({
    ...s,
    max_mileage_km: s.max_mileage_km ?? out.max_mileage_km ?? 250000,
  }));
  if (!out.scraper) out.scraper = structuredClone(defaultConfig.scraper);
  return out;
}

async function getConfig(env) {
  const raw = await env.SETTINGS.get("config");
  if (!raw) {
    const seeded = normalizeConfig(defaultConfig);
    await env.SETTINGS.put("config", JSON.stringify(seeded));
    return seeded;
  }
  return normalizeConfig(JSON.parse(raw));
}

async function saveConfig(env, cfg) {
  await env.SETTINGS.put("config", JSON.stringify(normalizeConfig(cfg)));
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

function syncAreas(cfg) {
  cfg.locations = (cfg.market_areas || []).map((a) => a.slug);
  if (!cfg.locations.length) {
    cfg.market_areas = [
      { slug: "toronto", label: "Toronto, ON", radius_km: 65 },
    ];
    cfg.locations = ["toronto"];
  }
}

function formatSettings(cfg) {
  const lines = [
    "⚙️ <b>Shared settings</b> (whole group)",
    CANADA_NOTE,
    "",
    "<b>Locations + radius</b>",
  ];
  if (!(cfg.market_areas || []).length) lines.push("• (none — add one)");
  for (const a of cfg.market_areas || []) {
    lines.push(`• ${escapeHtml(a.label)} · <b>${a.radius_km} km</b>`);
  }
  lines.push("");
  (cfg.searches || []).forEach((s, i) => {
    lines.push(`<b>${i + 1}. ${escapeHtml(s.name)}</b>`);
    lines.push(`   Query: <code>${escapeHtml(s.query)}</code>`);
    lines.push(`   Years: ${s.min_year}–${s.max_year}`);
    lines.push(`   Price: $${s.min_price}–$${s.max_price}`);
    lines.push(`   Max km: ${(s.max_mileage_km ?? 250000).toLocaleString()}`);
    lines.push("");
  });
  lines.push("Buttons below · /customsearch for a one-off run");
  return lines.join("\n");
}

function mainKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "👀 View", callback_data: "set:view" },
        { text: "🚗 Cars", callback_data: "set:cars" },
      ],
      [
        { text: "📍 Locations + km", callback_data: "set:areas" },
      ],
      [{ text: "❌ Close", callback_data: "set:close" }],
    ],
  };
}

function carsKeyboard(cfg) {
  const rows = (cfg.searches || []).map((s, i) => [
    { text: `✏️ ${s.name}`, callback_data: `car:edit:${i}` },
    { text: "🗑", callback_data: `car:delask:${i}` },
  ]);
  rows.push([{ text: "➕ Add car", callback_data: "car:add" }]);
  rows.push([{ text: "⬅️ Menu", callback_data: "set:menu" }]);
  return { inline_keyboard: rows };
}

function areasKeyboard(cfg) {
  const rows = (cfg.market_areas || []).map((a, i) => [
    {
      text: `${a.label} · ${a.radius_km} km`,
      callback_data: `area:edit:${i}`,
    },
    { text: "🗑", callback_data: `area:del:${i}` },
  ]);
  rows.push([{ text: "➕ Add location", callback_data: "area:add" }]);
  rows.push([{ text: "⬅️ Menu", callback_data: "set:menu" }]);
  return { inline_keyboard: rows };
}

function cityPickerKeyboard(page = 0, prefix = "locpick") {
  const pageSize = 8;
  const start = page * pageSize;
  const slice = CANADA_CITIES.slice(start, start + pageSize);
  const rows = [];
  for (let i = 0; i < slice.length; i += 2) {
    const row = [];
    for (let j = i; j < i + 2 && j < slice.length; j++) {
      const c = slice[j];
      row.push({
        text: c.label,
        callback_data: `${prefix}:${c.slug}`,
      });
    }
    rows.push(row);
  }
  const nav = [];
  if (page > 0) nav.push({ text: "⬅️ Prev", callback_data: `${prefix}page:${page - 1}` });
  if (start + pageSize < CANADA_CITIES.length) {
    nav.push({ text: "Next ➡️", callback_data: `${prefix}page:${page + 1}` });
  }
  if (nav.length) rows.push(nav);
  rows.push([
    { text: "❌ Cancel", callback_data: "wiz:cancel" },
    { text: "⬅️ Back", callback_data: "set:areas" },
  ]);
  return { inline_keyboard: rows };
}

function radiusKeyboard(prefix = "rad") {
  const rows = [];
  for (let i = 0; i < RADIUS_OPTS.length; i += 2) {
    rows.push(
      RADIUS_OPTS.slice(i, i + 2).map((r) => ({
        text: r.label,
        callback_data: `${prefix}:${r.km}`,
      }))
    );
  }
  rows.push([
    { text: "❌ Cancel", callback_data: "wiz:cancel" },
    { text: "⬅️ Back", callback_data: "set:areas" },
  ]);
  return { inline_keyboard: rows };
}

function wizardKeyboard({ keepLabel, keepData, extras } = {}) {
  const rows = [];
  if (extras?.length) rows.push(...extras);
  if (keepLabel && keepData) rows.push([{ text: keepLabel, callback_data: keepData }]);
  rows.push([
    { text: "❌ Cancel", callback_data: "wiz:cancel" },
    { text: "⬅️ Cars", callback_data: "wiz:tocars" },
  ]);
  return { inline_keyboard: rows };
}

function hybridKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "Yes — hybrid", callback_data: "car:hybrid:yes" },
        { text: "No", callback_data: "car:hybrid:no" },
      ],
      [
        { text: "❌ Cancel", callback_data: "wiz:cancel" },
        { text: "⬅️ Cars", callback_data: "wiz:tocars" },
      ],
    ],
  };
}

function mileageCarKeyboard() {
  const rows = [];
  for (let i = 0; i < KM_OPTS.length; i += 2) {
    rows.push(
      KM_OPTS.slice(i, i + 2).map((km) => ({
        text: `${km.toLocaleString()} km`,
        callback_data: `carkm:${km}`,
      }))
    );
  }
  rows.push([{ text: "⌨️ Type custom km", callback_data: "carkm:custom" }]);
  rows.push([
    { text: "❌ Cancel", callback_data: "wiz:cancel" },
    { text: "⬅️ Cars", callback_data: "wiz:tocars" },
  ]);
  return { inline_keyboard: rows };
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
    max_mileage_km: draft.max_mileage_km ?? 250000,
    must_include_any: qLower.split(/\s+/).filter(Boolean).slice(0, 3),
    must_include_all: [],
    powertrain_any: hybrid
      ? ["hybrid", "hev", "phev", "plug-in", "plugin", "plug in"]
      : [],
    body_styles: [],
    require_body_style: false,
    require_mileage: false,
  };
  const compact = qLower.replace(/\s+/g, "");
  if (compact && !searches.queries.includes(compact)) searches.queries.push(compact);
  if (!searches.must_include_any.length) searches.must_include_any = [qLower];
  return searches;
}

async function dispatchScan(env, jobId = null) {
  const [owner, repo] = String(env.GITHUB_REPO).split("/");
  const body = { ref: "main" };
  if (jobId) body.inputs = { job_id: jobId };
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
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(`GitHub dispatch ${res.status}: ${await res.text()}`);
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

async function promptCarName(env, chatId, wizard, { editing, custom } = {}) {
  const draft = wizard.draft || {};
  const extras = editing
    ? []
    : [
        [
          { text: "Mazda 3", callback_data: "wiz:pick:Mazda 3" },
          { text: "Kia Optima Hybrid", callback_data: "wiz:pick:Kia Optima Hybrid" },
        ],
      ];
  const title = custom ? "🔎 <b>Custom search</b> (not saved)" : editing ? "✏️ Edit car" : "➕ Add car";
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      `${title}\n${CANADA_NOTE}\n\n` +
      "🚗 <b>Step 1/6 — Car</b>\n" +
      (editing
        ? `Current: <code>${escapeHtml(draft.name || "")}</code>\nType new name or Keep.`
        : "Tap an example or type a name (e.g. <code>Honda Civic</code>)."),
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
  const suggestion = (draft.query || draft.name || "").toLowerCase();
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "🔎 <b>Step 2/6 — Facebook search text</b>\n" +
      "Same as typing into Marketplace.\n" +
      `Suggested: <code>${escapeHtml(suggestion)}</code>`,
    parse_mode: "HTML",
    reply_markup: wizardKeyboard({
      keepLabel: suggestion ? `✅ Use “${suggestion}”` : null,
      keepData: suggestion ? "wiz:keep" : null,
    }),
  });
}

async function promptCarYears(env, chatId, wizard) {
  const d = wizard.draft || {};
  const has = d.min_year != null ? `${d.min_year}-${d.max_year}` : "";
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "📅 <b>Step 3/6 — Years</b>\nType <code>2010-2014</code> or tap:" +
      (has ? `\nCurrent: <code>${has}</code>` : ""),
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
  const d = wizard.draft || {};
  const has = d.min_price != null ? `${d.min_price}-${d.max_price}` : "";
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "💰 <b>Step 4/6 — Price (CAD)</b>\nType <code>300-2300</code> or tap:" +
      (has ? `\nCurrent: <code>$${has}</code>` : ""),
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

async function promptCarMileage(env, chatId, wizard) {
  const d = wizard.draft || {};
  const cur = d.max_mileage_km ?? 250000;
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "⏱ <b>Step 5/6 — Max mileage for THIS car</b>\n" +
      `Current / default: <b>${Number(cur).toLocaleString()} km</b>\n` +
      "Each car has its own max km.",
    parse_mode: "HTML",
    reply_markup: mileageCarKeyboard(),
  });
}

async function promptCarHybrid(env, chatId) {
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text: "🔋 <b>Step 6/6 — Hybrid preference?</b>\nOptima Hybrid → Yes · Mazda 3 → No",
    parse_mode: "HTML",
    reply_markup: hybridKeyboard(),
  });
}

async function advanceCarWizard(env, chatId, wizard) {
  const draft = wizard.draft || {};
  if (wizard.step === "car_name") {
    if (!draft.name) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Choose or type a car name.",
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
    if (draft.min_year == null) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Pick years or type <code>2010-2014</code>",
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
    if (draft.min_price == null) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Pick price or type <code>300-2300</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return;
    }
    if (draft.max_mileage_km == null) draft.max_mileage_km = 250000;
    wizard.draft = draft;
    wizard.step = "car_mileage";
    await setWizard(env, chatId, wizard);
    await promptCarMileage(env, chatId, wizard);
    return;
  }
  if (wizard.step === "car_mileage") {
    if (draft.max_mileage_km == null) draft.max_mileage_km = 250000;
    wizard.draft = draft;
    wizard.step = "car_hybrid";
    await setWizard(env, chatId, wizard);
    await promptCarHybrid(env, chatId);
  }
}

async function finishCarSave(env, chatId, wizard, hybrid) {
  const cfg = await getConfig(env);
  wizard.draft.hybrid = hybrid;
  const search = buildSearchFromWizard(wizard.draft);

  if (wizard.mode === "custom") {
    // One-off: need location next (or use saved areas)
    wizard.step = "custom_area";
    wizard.draft = { ...wizard.draft, hybrid };
    wizard.search = search;
    await setWizard(env, chatId, wizard);
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text:
        "📍 <b>Custom search location</b>\n" +
        CANADA_NOTE +
        "\n\nUse your saved locations, or pick a different city:",
      parse_mode: "HTML",
      reply_markup: {
        inline_keyboard: [
          [{ text: "✅ Use saved locations", callback_data: "custom:usesaved" }],
          [{ text: "➕ Pick another city", callback_data: "custom:pickcity" }],
          [
            { text: "❌ Cancel", callback_data: "wiz:cancel" },
          ],
        ],
      },
    });
    return;
  }

  if (wizard.index >= 0) cfg.searches[wizard.index] = search;
  else cfg.searches.push(search);
  await saveConfig(env, cfg);
  await setWizard(env, chatId, null);
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      `✅ Saved <b>${escapeHtml(search.name)}</b> ` +
      `(max ${(search.max_mileage_km || 250000).toLocaleString()} km)\n\n` +
      formatSettings(cfg),
    parse_mode: "HTML",
    reply_markup: mainKeyboard(),
  });
}

async function runCustomJob(env, chatId, search, market_areas) {
  const jobId = `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const base = await getConfig(env);
  const job = {
    country: "CA",
    max_mileage_km: search.max_mileage_km || 250000,
    market_areas,
    locations: market_areas.map((a) => a.slug),
    location_keywords: [],
    searches: [search],
    scraper: {
      ...base.scraper,
      // Custom: fewer hubs — only vehicles mode for speed
      url_modes: ["vehicles"],
      search_mode_locations: market_areas.map((a) => a.slug),
      max_scrolls: 6,
    },
  };
  await env.SETTINGS.put(`job:${jobId}`, JSON.stringify(job), {
    expirationTtl: 60 * 60 * 6,
  });
  await setWizard(env, chatId, null);
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "🔎 <b>Custom search starting</b> (not saved to settings)\n" +
      CANADA_NOTE +
      `\n\n🚗 ${escapeHtml(search.name)}` +
      `\n🔎 <code>${escapeHtml(search.query)}</code>` +
      `\n📅 ${search.min_year}–${search.max_year}` +
      `\n💰 $${search.min_price}–$${search.max_price}` +
      `\n⏱ max ${(search.max_mileage_km || 250000).toLocaleString()} km` +
      `\n📍 ${market_areas.map((a) => `${a.label} (${a.radius_km} km)`).join(", ")}` +
      "\n\n⏳ Running on GitHub now…",
    parse_mode: "HTML",
  });
  try {
    await dispatchScan(env, jobId);
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: "🚀 Custom search dispatched. Results will appear here.",
    });
  } catch (err) {
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `❌ Failed to start custom search:\n${String(err.message || err)}`,
    });
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
      text: "🚗 Cars (each has its own max km):",
      reply_markup: carsKeyboard(cfg),
    });
    return;
  }

  if (data === "set:areas") {
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        "📍 <b>Locations + search radius</b>\n" +
        CANADA_NOTE +
        "\n\nLike Facebook: pick a city, then km radius.\nTap a row to change radius, or add/remove.",
      parse_mode: "HTML",
      reply_markup: areasKeyboard(cfg),
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
      text: "🚗 Cars:",
      reply_markup: carsKeyboard(cfg),
    });
    return;
  }

  if (data === "area:add") {
    await setWizard(env, chatId, { step: "area_pick", page: 0 });
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        "📍 <b>Pick a Canadian city</b> (correct spelling):\n" +
        CANADA_NOTE +
        "\n\nTap a city, then choose radius.",
      parse_mode: "HTML",
      reply_markup: cityPickerKeyboard(0, "locpick"),
    });
    return;
  }

  if (data.startsWith("locpickpage:")) {
    const page = Number(data.split(":")[1]) || 0;
    wizard = { step: "area_pick", page };
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: "📍 Pick a Canadian city:",
      reply_markup: cityPickerKeyboard(page, "locpick"),
    });
    return;
  }

  if (data.startsWith("locpick:")) {
    const slug = data.slice("locpick:".length);
    const city = CANADA_CITIES.find((c) => c.slug === slug);
    if (!city) return;
    wizard = { step: "area_radius", pendingCity: city };
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `📍 <b>${escapeHtml(city.label)}</b>\nChoose search radius (like Facebook):`,
      parse_mode: "HTML",
      reply_markup: radiusKeyboard("rad"),
    });
    return;
  }

  if (data.startsWith("rad:")) {
    const km = Number(data.split(":")[1]);
    const city = wizard.pendingCity;
    if (!city || !Number.isFinite(km)) return;
    cfg.market_areas = cfg.market_areas || [];
    const existing = cfg.market_areas.findIndex((a) => a.slug === city.slug);
    const area = { slug: city.slug, label: city.label, radius_km: km };
    if (existing >= 0) cfg.market_areas[existing] = area;
    else cfg.market_areas.push(area);
    syncAreas(cfg);
    await saveConfig(env, cfg);
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        `✅ Added <b>${escapeHtml(city.label)}</b> · ${km} km\n\n` + formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: areasKeyboard(cfg),
    });
    return;
  }

  if (data.startsWith("area:edit:")) {
    const index = Number(data.split(":")[2]);
    const area = cfg.market_areas[index];
    if (!area) return;
    wizard = { step: "area_radius", pendingCity: area, editIndex: index };
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `📍 Change radius for <b>${escapeHtml(area.label)}</b>\nCurrent: ${area.radius_km} km`,
      parse_mode: "HTML",
      reply_markup: radiusKeyboard("radedit"),
    });
    return;
  }

  if (data.startsWith("radedit:")) {
    const km = Number(data.split(":")[1]);
    const index = wizard.editIndex;
    if (index == null || !cfg.market_areas[index] || !Number.isFinite(km)) return;
    cfg.market_areas[index].radius_km = km;
    syncAreas(cfg);
    await saveConfig(env, cfg);
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `✅ Radius updated to ${km} km\n\n` + formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: areasKeyboard(cfg),
    });
    return;
  }

  if (data.startsWith("area:del:")) {
    const index = Number(data.split(":")[2]);
    if ((cfg.market_areas || []).length <= 1) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "⚠️ Keep at least one location.",
      });
      return;
    }
    const removed = cfg.market_areas.splice(index, 1)[0];
    syncAreas(cfg);
    await saveConfig(env, cfg);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `🗑 Removed ${escapeHtml(removed?.label || "location")}\n\n` + formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: areasKeyboard(cfg),
    });
    return;
  }

  // —— car wizard callbacks ——
  if (data === "wiz:keep") {
    if (wizard.step) await advanceCarWizard(env, chatId, wizard);
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

  if (data.startsWith("carkm:")) {
    if (wizard.step !== "car_mileage" && wizard.step !== "mileage_custom") return;
    if (data === "carkm:custom") {
      wizard.step = "mileage_custom";
      await setWizard(env, chatId, wizard);
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Type max km for this car.\nExample: <code>250000</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return;
    }
    const km = Number(data.split(":")[1]);
    wizard.draft = wizard.draft || {};
    wizard.draft.max_mileage_km = km;
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
    return;
  }

  if (data === "car:add") {
    const w = { step: "car_name", draft: { max_mileage_km: 250000 }, index: -1 };
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
        max_mileage_km: s.max_mileage_km ?? 250000,
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
      await tg(env, "sendMessage", { chat_id: chatId, text: "⚠️ Keep at least one car." });
      return;
    }
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `🗑 Delete <b>${escapeHtml(s.name)}</b>?`,
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
    if ((cfg.searches || []).length <= 1) return;
    const removed = cfg.searches.splice(index, 1)[0];
    await saveConfig(env, cfg);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `🗑 Removed <b>${escapeHtml(removed?.name || "")}</b>\n\n` + formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: mainKeyboard(),
    });
    return;
  }

  if (data === "car:hybrid:yes" || data === "car:hybrid:no") {
    if (wizard.step !== "car_hybrid") return;
    await finishCarSave(env, chatId, wizard, data.endsWith("yes"));
    return;
  }

  // custom search location branch
  if (data === "custom:usesaved") {
    if (wizard.mode !== "custom" || !wizard.search) return;
    const areas = cfg.market_areas || [];
    if (!areas.length) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "No saved locations. Pick a city:",
        reply_markup: cityPickerKeyboard(0, "customloc"),
      });
      wizard.step = "custom_pick";
      await setWizard(env, chatId, wizard);
      return;
    }
    await runCustomJob(env, chatId, wizard.search, areas);
    return;
  }

  if (data === "custom:pickcity") {
    wizard.step = "custom_pick";
    wizard.page = 0;
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: "📍 Pick city for this custom search:\n" + CANADA_NOTE,
      parse_mode: "HTML",
      reply_markup: cityPickerKeyboard(0, "customloc"),
    });
    return;
  }

  if (data.startsWith("customlocpage:")) {
    const page = Number(data.split(":")[1]) || 0;
    wizard.page = page;
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: "📍 Pick city:",
      reply_markup: cityPickerKeyboard(page, "customloc"),
    });
    return;
  }

  if (data.startsWith("customloc:")) {
    const slug = data.slice("customloc:".length);
    const city = CANADA_CITIES.find((c) => c.slug === slug);
    if (!city) return;
    wizard.pendingCity = city;
    wizard.step = "custom_radius";
    await setWizard(env, chatId, wizard);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `📍 ${escapeHtml(city.label)} — radius for this custom search:`,
      parse_mode: "HTML",
      reply_markup: radiusKeyboard("customrad"),
    });
    return;
  }

  if (data.startsWith("customrad:")) {
    const km = Number(data.split(":")[1]);
    const city = wizard.pendingCity;
    if (!city || !wizard.search || !Number.isFinite(km)) return;
    await runCustomJob(env, chatId, wizard.search, [
      { slug: city.slug, label: city.label, radius_km: km },
    ]);
  }
}

async function handleWizardText(env, chatId, text) {
  const wizard = await getWizard(env, chatId);
  if (!wizard?.step) return false;
  const cmd = text.split(/\s+/)[0].split("@")[0].toLowerCase();
  if (cmd === "/cancel") {
    await cancelWizard(env, chatId);
    return true;
  }

  const draft = wizard.draft || {};
  const trimmed = text.trim();

  if (wizard.step === "mileage_custom") {
    const km = Number(String(trimmed).replace(/[,\s]/g, ""));
    if (!Number.isFinite(km) || km < 1000) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Invalid. Example: <code>250000</code>",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
      });
      return true;
    }
    draft.max_mileage_km = Math.round(km);
    wizard.draft = draft;
    wizard.step = "car_mileage";
    await setWizard(env, chatId, wizard);
    await advanceCarWizard(env, chatId, wizard);
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
        text: "❌ Use <code>2010-2014</code> or tap a button.",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard({
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
        text: "❌ Use <code>300-2300</code> or tap a button.",
        parse_mode: "HTML",
        reply_markup: wizardKeyboard(),
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
      "🔎 Scan with <b>saved settings</b>…\n" +
      CANADA_NOTE +
      "\n⏳ 3–15 min · only NEW cars (no duplicates).",
    parse_mode: "HTML",
  });
  try {
    await dispatchScan(env);
    await tg(env, "sendMessage", { chat_id: chatId, text: "🚀 Scan started." });
  } catch (err) {
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `❌ Failed:\n${String(err.message || err)}`,
    });
  }
}

async function startCustomSearch(env, chatId) {
  const w = {
    mode: "custom",
    step: "car_name",
    draft: { max_mileage_km: 250000 },
    index: -1,
  };
  await setWizard(env, chatId, w);
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "🔎 <b>Custom search</b>\n" +
      CANADA_NOTE +
      "\n\nOne-time run — <b>not</b> saved to /settings.\n" +
      "Cancel anytime with the ❌ button or /cancel.",
    parse_mode: "HTML",
  });
  await promptCarName(env, chatId, w, { custom: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/config") {
      const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
      if (!token || token !== env.CONFIG_TOKEN) {
        return new Response("unauthorized", { status: 401 });
      }
      return Response.json(await getConfig(env));
    }

    if (request.method === "GET" && url.pathname.startsWith("/job/")) {
      const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
      if (!token || token !== env.CONFIG_TOKEN) {
        return new Response("unauthorized", { status: 401 });
      }
      const jobId = url.pathname.slice("/job/".length);
      const raw = await env.SETTINGS.get(`job:${jobId}`);
      if (!raw) return new Response("not found", { status: 404 });
      return new Response(raw, {
        headers: { "content-type": "application/json" },
      });
    }

    if (request.method !== "POST") return new Response("ok");

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
      if (!msg?.text) return new Response("ok");
      const chatId = msg.chat.id;
      const text = msg.text.trim();
      const cmd = text.split(/\s+/)[0].split("@")[0].toLowerCase();

      if (await handleWizardText(env, chatId, text)) return new Response("ok");

      if (ID.has(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text: `Chat id: ${chatId}\nType: ${msg.chat.type}`,
        });
        return new Response("ok");
      }

      if (HELP.has(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text:
            "🇨🇦 <b>Canada Marketplace car alerts</b>\n\n" +
            "/scan — run saved filters\n" +
            "/settings — shared cars, km, locations+radius\n" +
            "/customsearch — one-off search (not saved)\n" +
            "/cancel — abort wizard\n" +
            "/id — chat id\n\n" +
            CANADA_NOTE,
          parse_mode: "HTML",
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
        await setWizard(env, chatId, null);
        const cfg = await getConfig(env);
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text: formatSettings(cfg),
          parse_mode: "HTML",
          reply_markup: mainKeyboard(),
        });
        return new Response("ok");
      }

      if (CUSTOM.has(cmd)) {
        if (!authorized(chatId, env)) {
          await tg(env, "sendMessage", {
            chat_id: chatId,
            text: `⚠️ Not authorized.\nChat id: ${chatId}`,
          });
          return new Response("ok");
        }
        await startCustomSearch(env, chatId);
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
