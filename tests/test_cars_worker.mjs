import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../telegram-webhook/worker.js", import.meta.url), "utf8");
const config = JSON.parse(await readFile(new URL("../telegram-webhook/default-config.json", import.meta.url), "utf8"));

async function fixture() {
  const values = new Map();
  const messages = [];
  const context = vm.createContext({
    URL, Response, TextEncoder, structuredClone,
    fetch: async (url, options) => {
      assert.ok(String(url).startsWith("https://api.telegram.org/"), "Browsing cars must not dispatch scans");
      messages.push({ method: String(url).split("/").at(-1), ...JSON.parse(options.body) });
      return Response.json({ ok: true });
    },
  });
  const mod = new vm.SourceTextModule(source, { context });
  await mod.link(async () => {
    const dependency = new vm.SyntheticModule(["default"], function () {
      this.setExport("default", config);
    }, { context });
    return dependency;
  });
  await mod.evaluate();
  const env = {
    CONFIG_TOKEN: "test-config", TELEGRAM_CHAT_IDS: "123", TELEGRAM_BOT_TOKEN: "test-bot",
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
  return { values, messages, request, cars, findings };
}

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
  assert.doesNotMatch(f.messages.at(-1).text, /Car 5/);
  assert.equal(f.messages.at(-1).reply_markup.inline_keyboard[0][0].callback_data, "cars:page:1");
  await f.request("/", { callback_query: {
    id: "callback", data: "cars:page:1", message: { message_id: 9, chat: { id: 123 } },
  } });
  assert.equal(f.messages.at(-1).method, "editMessageText");
  assert.match(f.messages.at(-1).text, /Car 5/);
  assert.match(f.messages.at(-1).text, /Car 9/);
  await f.cars("/cars 3");
  assert.match(f.messages.at(-1).text, /Car 10/);
  assert.match(f.messages.at(-1).text, /Car 11/);
  await f.cars("/cars 999999");
  assert.match(f.messages.at(-1).text, /Page 3\/3/);
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
  }));
  await f.request("/findings", { findings: rows });
  await f.cars();
  const text = f.messages.at(-1).text;
  assert.ok(text.length < 4096);
  assert.ok(text.includes("&lt;script&gt;"));
  assert.ok(!text.includes("<script>"));
});
