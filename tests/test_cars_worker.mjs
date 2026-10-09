import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../telegram-webhook/worker.js", import.meta.url), "utf8");
const config = JSON.parse(await readFile(new URL("../telegram-webhook/default-config.json", import.meta.url), "utf8"));

async function fixture({ allowScans = false } = {}) {
  const values = new Map();
  const messages = [];
  const dispatches = [];
  const context = vm.createContext({
    URL, Response, TextEncoder, structuredClone,
    fetch: async (url, options) => {
      if (allowScans && String(url).startsWith("https://api.github.com/")) {
        dispatches.push(JSON.parse(options.body));
        return new Response(null, { status: 204 });
      }
      assert.ok(String(url).startsWith("https://api.telegram.org/"), "Browsing cars must not dispatch scans");
      messages.push({ method: String(url).split("/").at(-1), ...JSON.parse(options.body) });
      return Response.json({ ok: true });
    },
  });
  const mod = new vm.SourceTextModule(source + "\nexport { buildSearchFromWizard };", { context });
  await mod.link(async () => {
    const dependency = new vm.SyntheticModule(["default"], function () {
      this.setExport("default", config);
    }, { context });
    return dependency;
  });
  await mod.evaluate();
  const env = {
    CONFIG_TOKEN: "test-config", TELEGRAM_CHAT_IDS: "123", TELEGRAM_BOT_TOKEN: "test-bot",
    GITHUB_REPO: "test/repo", GITHUB_TOKEN: "test-github",
    SETTINGS: {
      get: async (key) => values.get(key) ?? null,
      put: async (key, value) => values.set(key, value),
      delete: async (key) => values.delete(key),
    },
  };
  const request = (path, body, token = "test-config") => mod.namespace.default.fetch(
    new Request(`https://worker.invalid${path}`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(body),
    }), env,
  );
  const cars = (text = "/cars", chat = 123) => request("/", { message: { text, chat: { id: chat } } });
  const findings = Array.from({ length: 12 }, (_, index) => ({
    listing_id: String(100 + index), title: `Car ${index}`, search_name: "Mazda",
    url: "https://untrusted.invalid/", first_seen_at: "2026-10-07 08:00:00",
  }));
  return { values, messages, dispatches, request, cars, findings, buildSearch: mod.namespace.buildSearchFromWizard };
}

test("confirmed login failure silently pauses repeated automatic ticks without changing settings or cars", async () => {
  const f = await fixture();
  await f.request("/findings", { findings: f.findings });
  const findings = f.values.get("findings");
  const interval = config.poll_interval_minutes;
  const result = await f.request("/session", { status: "inactive", scan_started_at: 1000 });
  assert.deepEqual(await result.json(), { ok: true, applied: true });
  for (let i = 0; i < 3; i++) {
    const tick = await f.request("/tick", {});
    assert.deepEqual(await tick.json(), { ok: true, skipped: "facebook_login_needed", interval_min: interval });
  }
  assert.equal(f.messages.length, 0);
  assert.equal(f.values.get("findings"), findings);
  assert.equal(f.values.has("last_auto_scan_at"), false);
});

test("only a newer verified scan resumes auto scans and old failures cannot re-pause it", async () => {
  const f = await fixture({ allowScans: true });
  await f.request("/session", { status: "inactive", scan_started_at: 2000 });
  assert.equal((await f.request("/session", { status: "active", scan_started_at: 1000 })).status, 200);
  assert.equal(JSON.parse(f.values.get("facebook_session_status")).status, "inactive");
  assert.deepEqual(await (await f.request("/session", { status: "active", scan_started_at: 3000 })).json(),
    { ok: true, applied: true });
  assert.deepEqual(await (await f.request("/session", { status: "inactive", scan_started_at: 2000 })).json(),
    { ok: true, applied: false });
  const tick = await f.request("/tick", {});
  assert.equal((await tick.json()).skipped, "not_due");
  assert.equal(f.dispatches.length, 0);
  f.values.set("last_auto_scan_at", String(Date.now() - config.poll_interval_minutes * 60000 - 1000));
  assert.equal((await (await f.request("/tick", {})).json()).started, true);
  assert.equal(f.dispatches.length, 1);
});

test("normal successful scans and stale reports do not move the timer's saved due time", async () => {
  const f = await fixture();
  f.values.set("last_auto_scan_at", "1000");
  await f.request("/session", { status: "active", scan_started_at: 1000 });
  await f.request("/session", { status: "active", scan_started_at: 2000 });
  assert.equal(f.values.get("last_auto_scan_at"), "1000");
  await f.request("/session", { status: "inactive", scan_started_at: 3000 });
  await f.request("/session", { status: "active", scan_started_at: 2000 });
  assert.equal(f.values.get("last_auto_scan_at"), "1000");
  assert.equal(JSON.parse(f.values.get("facebook_session_status")).status, "inactive");
});

test("session writes require authentication and reject unknown or malformed states", async () => {
  const f = await fixture();
  assert.equal((await f.request("/session", { status: "inactive", scan_started_at: 1000 }, "wrong")).status, 401);
  for (const payload of [null, { status: "unknown", scan_started_at: 1000 },
    { status: "active", scan_started_at: "1000" }, { status: "active", scan_started_at: -1 },
    { status: "active", scan_started_at: Date.now() + 120000 }]) {
    assert.equal((await f.request("/session", payload)).status, 400);
  }
  assert.equal(f.values.has("facebook_session_status"), false);
});

test("session command shows last-known state without starting a Facebook scan", async () => {
  const f = await fixture();
  await f.cars("/session", 999);
  assert.equal(f.messages.at(-1).text, "Not authorized.");
  await f.cars("/session");
  assert.match(f.messages.at(-1).text, /has not been recorded/);
  await f.request("/session", { status: "inactive", scan_started_at: 1000 });
  await f.cars("/session@MyBot");
  assert.match(f.messages.at(-1).text, /Automatic scans are paused/);
  await f.request("/session", { status: "active", scan_started_at: 2000 });
  await f.cars("/status");
  assert.match(f.messages.at(-1).text, /not a live Facebook check/);
});

test("manual recovery scan remains available while paused but queueing does not clear the pause", async () => {
  const f = await fixture({ allowScans: true });
  await f.request("/session", { status: "inactive", scan_started_at: 1000 });
  await f.cars("/scan");
  assert.equal(f.dispatches.length, 1);
  assert.equal(JSON.parse(f.values.get("facebook_session_status")).status, "inactive");
});

test("saved and custom Telegram searches delegate all car models to general expansion", async () => {
  const f = await fixture();
  for (const query of ["kia optima hybrid", "toyota camry hybrid", "honda civic", "ford f150", "mazda3"]) {
    const search = f.buildSearch({ query, min_year: 2010, max_year: 2020, min_price: 1000,
      max_price: 3000, max_mileage_km: 200000 });
    assert.equal(search.query, query);
    assert.equal(search.queries.length, 1);
    assert.equal(search.must_include_any.length, 0);
    assert.equal(search.must_include_all.length, 0);
    assert.equal(search.max_price, 3000);
    assert.equal(search.max_mileage_km, 200000);
    assert.equal(search.powertrain_any.length > 0, query.includes("hybrid"));
  }
  assert.ok(f.buildSearch({ query: "toyota camry", hybrid: true }).powertrain_any.includes("hev"));
  assert.ok(f.buildSearch({ query: "outlander plug-in hybrid" }).powertrain_any.includes("phev"));
});

test("full authenticated snapshot preserves all rows and canonical links", async () => {
  const f = await fixture();
  const res = await f.request("/findings", { findings: f.findings });
  assert.deepEqual(await res.json(), { ok: true, count: 12 });
  const snapshot = JSON.parse(f.values.get("findings"));
  assert.equal(snapshot.findings.length, 12);
  assert.equal(snapshot.findings[0].url, "https://www.facebook.com/marketplace/item/100");
  assert.ok(snapshot.updated_at);
});

test("snapshot rejects unauthorized, duplicate, and invalid IDs without replacing history", async () => {
  const f = await fixture();
  await f.request("/findings", { findings: f.findings });
  const before = f.values.get("findings");
  assert.equal((await f.request("/findings", { findings: [] }, "wrong")).status, 401);
  assert.equal((await f.request("/findings", { findings: [f.findings[0], f.findings[0]] })).status, 400);
  assert.equal((await f.request("/findings", { findings: [{ listing_id: '1"><bad>' }] })).status, 400);
  assert.equal(f.values.get("findings"), before);
});

test("cars command and navigation reach every saved finding", async () => {
  const f = await fixture();
  await f.request("/findings", { findings: f.findings });
  await f.cars("/cars@MyBot");
  assert.match(f.messages.at(-1).text, /Saved cars: 12/);
  assert.match(f.messages.at(-1).text, /Car 0/);
  assert.doesNotMatch(f.messages.at(-1).text, /Car 3/);
  assert.equal(f.messages.at(-1).reply_markup.inline_keyboard[0][0].callback_data, "cars:page:1");
  await f.request("/", { callback_query: {
    id: "callback", data: "cars:page:1", message: { message_id: 9, chat: { id: 123 } },
  } });
  assert.equal(f.messages.at(-1).method, "editMessageText");
  assert.match(f.messages.at(-1).text, /Car 3/);
  assert.match(f.messages.at(-1).text, /Car 5/);
  await f.cars("/cars 4");
  assert.match(f.messages.at(-1).text, /Car 10/);
  assert.match(f.messages.at(-1).text, /Car 11/);
  await f.cars("/cars 999999");
  assert.match(f.messages.at(-1).text, /Page 4\/4/);
});

test("unauthorized commands and callbacks do not disclose findings", async () => {
  const f = await fixture();
  await f.request("/findings", { findings: f.findings });
  await f.cars("/cars", 999);
  assert.equal(f.messages.at(-1).text, "Not authorized.");
  await f.request("/", { callback_query: {
    id: "callback", data: "cars:page:0", message: { message_id: 9, chat: { id: 999 } },
  } });
  assert.equal(f.messages.at(-1).method, "answerCallbackQuery");
  assert.equal(f.messages.at(-1).text, "Not authorized");
});

test("missing and empty snapshots have distinct messages", async () => {
  const f = await fixture();
  await f.cars();
  assert.match(f.messages.at(-1).text, /has not synced yet/);
  await f.request("/findings", { findings: [] });
  await f.cars();
  assert.match(f.messages.at(-1).text, /No saved findings yet/);
});

test("pathological titles are escaped and stay within Telegram message limits", async () => {
  const f = await fixture();
  const rows = f.findings.slice(0, 5).map((row) => ({ ...row,
    title: "&<script>".repeat(100), search_name: "&".repeat(100),
    price: "&".repeat(100), location: "&".repeat(100),
    safety: "yes", safety_evidence: "&".repeat(200),
  }));
  await f.request("/findings", { findings: rows });
  await f.cars();
  const text = f.messages.at(-1).text;
  assert.ok(text.length < 4096);
  assert.ok(text.includes("&lt;script&gt;"));
  assert.ok(!text.includes("<script>"));
});

test("cars preserves and displays captured price, year, mileage, location and dates", async () => {
  const f = await fixture();
  await f.request("/findings", { findings: [{ ...f.findings[0],
    price: "CA$2,500", price_amount: 2500, year: 2014, mileage_km: 220000,
    location: "North York, ON", last_seen_at: "2026-10-07 09:15:00",
    safety: "no", safety_evidence: "No safety <certificate>",
  }] });
  await f.cars();
  const text = f.messages.at(-1).text;
  assert.match(text, /CA\$2,500/);
  assert.match(text, /Year: 2014/);
  assert.match(text, /220,000 km/);
  assert.match(text, /North York, ON/);
  assert.match(text, /First found: 2026-10-07 08:00 UTC/);
  assert.match(text, /Last seen: 2026-10-07 09:15 UTC/);
  assert.match(text, /Safety: <b>no<\/b>/);
  assert.match(text, /No safety &lt;certificate&gt;/);
});

test("older rows show missing details honestly and cannot inject HTML through dates", async () => {
  const f = await fixture();
  await f.request("/findings", { findings: [{ ...f.findings[0],
    title: "2012 Mazda 3", first_seen_at: "<script>bad</script>",
  }] });
  await f.cars();
  const text = f.messages.at(-1).text;
  assert.match(text, /Price: <b>not saved yet<\/b>/);
  assert.match(text, /Year: 2012/);
  assert.match(text, /Mileage: not shown/);
  assert.match(text, /Last seen: not saved yet/);
  assert.match(text, /Safety: <b>unknown<\/b>/);
  assert.doesNotMatch(text, /<script>/);
});
