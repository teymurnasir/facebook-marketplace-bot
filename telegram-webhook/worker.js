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

const INTERVAL_OPTS = [15, 30, 45, 60, 90, 120]; // minutes (0 = auto off)

function normalizeConfig(cfg) {
  const out = structuredClone(cfg || defaultConfig);
  out.country = "CA";
  out.max_mileage_km = out.max_mileage_km || 250000;
  let interval = Number(out.poll_interval_minutes);
  if (!Number.isFinite(interval)) interval = 30;
  if (interval < 0) interval = 0;
  if (interval > 0 && interval < 15) interval = 15; // minimum auto interval
  out.poll_interval_minutes = Math.round(interval);
  if (!Array.isArray(out.market_areas)) out.market_areas = [];
  // Migrate legacy locations list → at most ONE area (user adds more themselves)
  if (!out.market_areas.length && Array.isArray(out.locations) && out.locations.length) {
    const slug = String(out.locations[0]);
    const hit = CANADA_CITIES.find((c) => c.slug === slug);
    out.market_areas = [
      {
        slug,
        label: hit?.label || slug.replaceAll("-", " "),
        radius_km: 65,
      },
    ];
  }
  out.locations = out.market_areas.map((a) => a.slug);
  out.location_keywords = out.location_keywords || [];
  out.searches = (out.searches || []).map((s) => ({
    ...s,
    max_mileage_km: s.max_mileage_km ?? out.max_mileage_km ?? 250000,
  }));
  if (!out.scraper) out.scraper = structuredClone(defaultConfig.scraper);
  const activeLocations = new Set(out.locations || []);
  const searchModeLocations = Array.isArray(out.scraper.search_mode_locations)
    ? out.scraper.search_mode_locations
    : [];
  if (
    searchModeLocations.length &&
    activeLocations.size &&
    !searchModeLocations.some((slug) => activeLocations.has(slug))
  ) {
    out.scraper.search_mode_locations = [out.locations[0]];
  }
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
  cfg.market_areas = cfg.market_areas || [];
  cfg.locations = cfg.market_areas.map((a) => a.slug);
}

function hasLocations(cfg) {
  return Array.isArray(cfg.market_areas) && cfg.market_areas.length > 0;
}

function hasCars(cfg) {
  return Array.isArray(cfg.searches) && cfg.searches.length > 0;
}

/** Returns error text if scan cannot start, else null */
function scanBlockReason(cfg) {
  if (!hasCars(cfg)) {
    return "⚠️ Add at least one <b>car</b> in /settings before scanning.";
  }
  if (!hasLocations(cfg)) {
    return (
      "⚠️ Add at least one <b>location + radius</b> in /settings before scanning.\n" +
      "Locations work like cars: add only the cities you want (each city = more search work)."
    );
  }
  return null;
}

function formatInterval(minutes) {
  if (!minutes) return "Off (manual /scan only)";
  return `Every ${minutes} min`;
}

function formatSettings(cfg) {
  const lines = [
    "⚙️ <b>Shared settings</b> (whole group)",
    CANADA_NOTE,
    "",
    `<b>Auto scan:</b> ${formatInterval(cfg.poll_interval_minutes)}`,
    "",
    "<b>Locations</b> (add only what you need — each one is searched)",
  ];
  if (!hasLocations(cfg)) {
    lines.push("• ⚠️ <b>None</b> — add a location or /scan will be blocked");
  } else {
    for (const a of cfg.market_areas) {
      lines.push(`• ${escapeHtml(a.label)} · <b>${a.radius_km} km</b>`);
    }
  }
  lines.push("");
  lines.push("<b>Cars</b> (each has its own max km)");
  if (!hasCars(cfg)) {
    lines.push("• ⚠️ <b>None</b> — add a car or /scan will be blocked");
  } else {
    (cfg.searches || []).forEach((s, i) => {
      lines.push(`<b>${i + 1}. ${escapeHtml(s.name)}</b>`);
      lines.push(`   Query: <code>${escapeHtml(s.query)}</code>`);
      lines.push(`   Years: ${s.min_year}–${s.max_year}`);
      lines.push(`   Price: $${s.min_price}–$${s.max_price}`);
      lines.push(`   Max km: ${(s.max_mileage_km ?? 250000).toLocaleString()}`);
      lines.push("");
    });
  }
  lines.push("/customsearch = one-off run (not saved)");
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
        { text: "📍 Locations", callback_data: "set:areas" },
        { text: "⏰ Auto interval", callback_data: "set:interval" },
      ],
      [{ text: "❌ Close", callback_data: "set:close" }],
    ],
  };
}

function intervalKeyboard(current) {
  const rows = [];
  for (let i = 0; i < INTERVAL_OPTS.length; i += 3) {
    rows.push(
      INTERVAL_OPTS.slice(i, i + 3).map((m) => ({
        text: m === current ? `✅ ${m} min` : `${m} min`,
        callback_data: `interval:${m}`,
      }))
    );
  }
  rows.push([
    {
      text: current === 0 ? "✅ Auto off" : "⏸ Auto off",
      callback_data: "interval:0",
    },
  ]);
  rows.push([{ text: "⬅️ Menu", callback_data: "set:menu" }]);
  return { inline_keyboard: rows };
}

function carsKeyboard(cfg) {
  const rows = (cfg.searches || []).map((s, i) => [
    { text: `✏️ ${s.name}`, callback_data: `car:edit:${i}` },
    { text: "🗑 Delete", callback_data: `car:delask:${i}` },
  ]);
  rows.push([{ text: "➕ Add car", callback_data: "car:add" }]);
  rows.push([{ text: "⬅️ Menu", callback_data: "set:menu" }]);
  return { inline_keyboard: rows };
}

function areasKeyboard(cfg) {
  const areas = cfg.market_areas || [];
  const rows = areas.map((a, i) => [
    { text: `✏️ ${a.label}`, callback_data: `area:edit:${i}` },
    { text: "🗑 Delete", callback_data: `area:delask:${i}` },
  ]);
  rows.push([{ text: "➕ Add location", callback_data: "area:add" }]);
  rows.push([{ text: "⬅️ Menu", callback_data: "set:menu" }]);
  return { inline_keyboard: rows };
}

function areasMenuText(cfg) {
  const n = (cfg.market_areas || []).length;
  let text =
    "📍 <b>Locations</b> (same idea as cars)\n" +
    CANADA_NOTE +
    "\n\n" +
    "1) Tap <b>Add location</b> → pick a Canadian city\n" +
    "2) Choose <b>km radius</b>\n" +
    "3) Add more cities anytime — each location is searched separately\n\n";
  if (!n) {
    text += "⚠️ <b>No locations yet</b> — you must add at least one before /scan.";
  } else {
    text += `<b>Saved (${n})</b> — tap ✏️ to change radius, 🗑 to remove:`;
  }
  return text;
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

/**
 * Queue a scan for the always-on local PC scanner.
 * Facebook work stays on one home machine/IP (better session stability).
 * GitHub Actions is no longer used to start Marketplace scans.
 */
async function dispatchScan(env, jobId = null) {
  const payload = {
    requested_at: Date.now(),
    job_id: jobId || null,
  };
  await env.SETTINGS.put("pending_scan", JSON.stringify(payload));
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
      "\n\n⏳ Queued for your home PC…",
    parse_mode: "HTML",
  });
  try {
    await dispatchScan(env, jobId);
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: "🚀 Custom search queued. Results will appear here shortly.",
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
      text: areasMenuText(cfg),
      parse_mode: "HTML",
      reply_markup: areasKeyboard(cfg),
    });
    return;
  }

  if (data === "set:interval") {
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        "⏰ <b>Auto scan interval</b>\n" +
        CANADA_NOTE +
        `\n\nCurrent: <b>${formatInterval(cfg.poll_interval_minutes)}</b>\n` +
        "Cloud checks about every 15 minutes; a scan starts only when this interval has passed.\n" +
        "/scan always works immediately (ignores this timer).",
      parse_mode: "HTML",
      reply_markup: intervalKeyboard(cfg.poll_interval_minutes),
    });
    return;
  }

  if (data.startsWith("interval:")) {
    const minutes = Number(data.split(":")[1]);
    if (!Number.isFinite(minutes) || minutes < 0) return;
    cfg.poll_interval_minutes = minutes === 0 ? 0 : Math.max(15, Math.round(minutes));
    await saveConfig(env, cfg);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        `✅ Auto scan set to <b>${formatInterval(cfg.poll_interval_minutes)}</b>\n\n` +
        formatSettings(cfg),
      parse_mode: "HTML",
      reply_markup: mainKeyboard(),
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
    let note;
    if (existing >= 0) {
      cfg.market_areas[existing] = area;
      note = `✅ Updated <b>${escapeHtml(city.label)}</b> · ${km} km (already in list)`;
    } else {
      cfg.market_areas.push(area);
      note = `✅ Added <b>${escapeHtml(city.label)}</b> · ${km} km`;
    }
    syncAreas(cfg);
    await saveConfig(env, cfg);
    await setWizard(env, chatId, null);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text: `${note}\n\n${areasMenuText(cfg)}`,
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

  if (data.startsWith("area:delask:")) {
    const index = Number(data.split(":")[2]);
    const area = cfg.market_areas?.[index];
    if (!area) return;
    const last = (cfg.market_areas || []).length <= 1;
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        `🗑 Delete location <b>${escapeHtml(area.label)}</b> (${area.radius_km} km)?` +
        (last
          ? "\n\n⚠️ This is your <b>last</b> location — /scan will be blocked until you add another."
          : ""),
      parse_mode: "HTML",
      reply_markup: {
        inline_keyboard: [
          [
            { text: "Yes, delete", callback_data: `area:del:${index}` },
            { text: "❌ Cancel", callback_data: "set:areas" },
          ],
        ],
      },
    });
    return;
  }

  if (data.startsWith("area:del:")) {
    const index = Number(data.split(":")[2]);
    const removed = (cfg.market_areas || []).splice(index, 1)[0];
    syncAreas(cfg);
    await saveConfig(env, cfg);
    await tg(env, "editMessageText", {
      chat_id: chatId,
      message_id: cq.message.message_id,
      text:
        `🗑 Removed ${escapeHtml(removed?.label || "location")}\n\n` +
        areasMenuText(cfg),
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
      await tg(env, "editMessageText", {
        chat_id: chatId,
        message_id: cq.message.message_id,
        text:
          "⚠️ No saved locations yet.\n" +
          "Pick a city for this custom search (or cancel and add locations in /settings):",
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
  const cfg = await getConfig(env);
  const block = scanBlockReason(cfg);
  if (block) {
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: block + "\n\nOpen /settings to fix this.",
      parse_mode: "HTML",
      reply_markup: {
        inline_keyboard: [
          [
            { text: "📍 Add location", callback_data: "set:areas" },
            { text: "🚗 Cars", callback_data: "set:cars" },
          ],
        ],
      },
    });
    return;
  }
  const areaN = cfg.market_areas.length;
  const carN = cfg.searches.length;
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text:
      "🔎 Scan with <b>saved settings</b>…\n" +
      CANADA_NOTE +
      `\n🚗 ${carN} car(s) × 📍 ${areaN} location(s)` +
      "\n⏳ 3–15 min · only NEW cars (no duplicates).",
    parse_mode: "HTML",
  });
  try {
    await dispatchScan(env);
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: "🚀 Scan queued for your home PC. Results will arrive here shortly.",
    });
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
      "You will pick a location + radius at the end (required).\n" +
      "Cancel anytime with ❌ or /cancel.",
    parse_mode: "HTML",
  });
  await promptCarName(env, chatId, w, { custom: true });
}

async function scheduledScan(env, { source = "timer" } = {}) {
  // Auto timing is owned by the local PC scanner (main.py loop).
  // Cloud ticks stay as a no-op so GitHub/Cloudflare do not start Facebook scans.
  return {
    ok: true,
    skipped: "local_scanner_owns_timer",
    source,
  };
}

export default {
  // Cloudflare cron (Free plan often only fires ~hourly) — backup tick
  async scheduled(event, env, ctx) {
    ctx.waitUntil(scheduledScan(env, { source: "cloudflare_cron" }));
  },

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

    // Local PC scanner polls this for Telegram /scan and /customsearch jobs.
    if (request.method === "GET" && url.pathname === "/pending-scan") {
      const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
      if (!token || token !== env.CONFIG_TOKEN) {
        return new Response("unauthorized", { status: 401 });
      }
      const raw = await env.SETTINGS.get("pending_scan");
      if (!raw) return Response.json({ pending: false });
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        await env.SETTINGS.delete("pending_scan");
        return Response.json({ pending: false });
      }
      return Response.json({ pending: true, ...payload });
    }

    if (request.method === "POST" && url.pathname === "/pending-scan/ack") {
      const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
      if (!token || token !== env.CONFIG_TOKEN) {
        return new Response("unauthorized", { status: 401 });
      }
      let body = {};
      try {
        body = await request.json();
      } catch {
        body = {};
      }
      const raw = await env.SETTINGS.get("pending_scan");
      if (!raw) return Response.json({ ok: true, cleared: false });
      try {
        const payload = JSON.parse(raw);
        if (
          body.requested_at != null &&
          Number(payload.requested_at) !== Number(body.requested_at)
        ) {
          return Response.json({ ok: true, cleared: false, reason: "stale" });
        }
      } catch {
        // clear corrupt payload
      }
      await env.SETTINGS.delete("pending_scan");
      return Response.json({ ok: true, cleared: true });
    }

    // Legacy tick endpoint (GitHub auto-tick). Local scanner owns the timer now.
    if (
      (request.method === "GET" || request.method === "POST") &&
      url.pathname === "/tick"
    ) {
      const token = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
      if (!token || token !== env.CONFIG_TOKEN) {
        return new Response("unauthorized", { status: 401 });
      }
      const result = await scheduledScan(env, { source: "github_tick" });
      return Response.json(result);
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
