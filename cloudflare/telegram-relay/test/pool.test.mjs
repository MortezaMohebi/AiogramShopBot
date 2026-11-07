/**
 * Self-contained P5 regression contracts for multi-bot Cloudflare relay auth.
 * Node exercises fake providers and quota storage without external calls.
 */
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { afterEach, test } from "node:test";
import worker, { RelayQuota } from "../src/index.mjs";

const BASE = "https://relay-pool.example.workers.dev";
const BOT_A = "1b52e917-6b79-4305-9ecf-40fb8f23b306";
const BOT_B = "54671634-3d4e-4a33-92e5-3a998bf9ca2d";
const TOKEN_A = "123456789:" + "A".repeat(35);
const TOKEN_B = "987654321:" + "B".repeat(35);
const KEY_A = "distinct-per-bot-a-key-" + "c".repeat(40);
const KEY_B = "distinct-per-bot-b-key-" + "d".repeat(40);
const ORIGINAL_FETCH = globalThis.fetch;

afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

function hash(value) {
  return createHash("sha256").update(value).digest("hex");
}

function quota(responseStatus = 204) {
  return {
    idFromName: name => name,
    get: () => ({
      fetch: async () => new Response(null, { status: responseStatus }),
    }),
  };
}

function env(overrides = {}) {
  return {
    RELAY_CLIENTS_JSON: JSON.stringify({
      [BOT_A]: {
        token_sha256: hash(TOKEN_A), keys: { "1": KEY_A, "2": KEY_A + "next" },
        rps: 3, max_inflight: 2,
      },
      [BOT_B]: {
        token_sha256: hash(TOKEN_B), keys: { "1": KEY_B },
        rps: 3, max_inflight: 2,
      },
    }),
    RELAY_QUOTA: quota(),
    RELAY_GLOBAL_RPS: "10",
    RELAY_GLOBAL_INFLIGHT: "4",
    ...overrides,
  };
}

function request(botId, key, token, method = "getMe") {
  return new Request(`${BASE}/bot${token}/${method}`, {
    method: "POST",
    headers: {
      "x-relay-bot-id": botId,
      "x-relay-version": "1",
      "x-relay-key": key,
    },
  });
}

test("one Worker serves two bots with distinct secrets", async () => {
  const observed = [];
  globalThis.fetch = async inbound => {
    observed.push({
      url: inbound.url,
      botId: inbound.headers.get("x-relay-bot-id"),
      secret: inbound.headers.get("x-relay-key"),
    });
    return Response.json({ ok: true, result: { id: 123 } });
  };
  for (const [botId, key, token] of [
    [BOT_A, KEY_A, TOKEN_A], [BOT_B, KEY_B, TOKEN_B],
  ]) {
    const response = await worker.fetch(request(botId, key, token), env());
    assert.equal(response.status, 200);
    await response.text();
  }
  assert.equal(observed.length, 2);
  assert.equal(observed[0].url, `https://api.telegram.org/bot${TOKEN_A}/getMe`);
  assert.equal(observed[1].url, `https://api.telegram.org/bot${TOKEN_B}/getMe`);
  assert.ok(observed.every(record => record.botId === null && record.secret === null));
});

test("cross-bot key reuse cannot forward another bot's token", async () => {
  let called = false;
  globalThis.fetch = () => { called = true; throw Error("unexpected"); };
  const wrongKey = await worker.fetch(request(BOT_A, KEY_B, TOKEN_A), env());
  const wrongToken = await worker.fetch(request(BOT_A, KEY_A, TOKEN_B), env());
  assert.equal(wrongKey.status, 401);
  assert.equal(wrongToken.status, 401);
  assert.equal(called, false);
});

test("configuration and quota failure fail closed before contacting Telegram", async () => {
  let called = false;
  globalThis.fetch = () => { called = true; throw Error("unexpected"); };
  const missingQuota = await worker.fetch(
    request(BOT_A, KEY_A, TOKEN_A), env({ RELAY_QUOTA: null }),
  );
  const overloaded = await worker.fetch(
    request(BOT_A, KEY_A, TOKEN_A), env({ RELAY_QUOTA: quota(429) }),
  );
  const misconfigured = await worker.fetch(
    request(BOT_A, KEY_A, TOKEN_A), env({ RELAY_CLIENTS_JSON: "{" }),
  );
  assert.equal(missingQuota.status, 503);
  assert.equal(overloaded.status, 429);
  assert.equal(misconfigured.status, 503);
  assert.equal(called, false);
});

test("rotating a key permits only the explicitly provisioned version", async () => {
  let called = 0;
  globalThis.fetch = async () => {
    called += 1;
    return Response.json({ ok: true, result: { id: 123 } });
  };
  const active = request(BOT_A, KEY_A + "next", TOKEN_A);
  active.headers.set("x-relay-version", "2");
  const valid = await worker.fetch(active, env());
  assert.equal(valid.status, 200);
  await valid.text();
  const unknown = request(BOT_A, KEY_A, TOKEN_A);
  unknown.headers.set("x-relay-version", "999");
  assert.equal((await worker.fetch(unknown, env())).status, 401);
  assert.equal(called, 1);
});

test("no automatic replay after a failed Telegram mutation", async () => {
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts += 1;
    throw Error("upstream outcome unknown");
  };
  const response = await worker.fetch(
    request(BOT_A, KEY_A, TOKEN_A, "sendMessage"), env(),
  );
  assert.equal(response.status, 502);
  assert.equal(attempts, 1);
  assert.equal((await response.text()).includes(TOKEN_A), false);
});

test("persistent Durable Object reserves per-bot and global inflight quotas", async () => {
  const data = new Map();
  const ctx = {
    storage: {
      get: async key => data.get(key),
      put: async (key, value) => { data.set(key, value); },
    },
    blockConcurrencyWhile: callback => callback(),
  };
  const object = new RelayQuota(ctx);
  const payload = id => ({
    id, bot_id: BOT_A, rps: 10,
    max_inflight: 1, global_rps: 20, global_inflight: 20,
  });
  const reserve = id => object.fetch(new Request("https://quota.internal/reserve", {
    method: "POST", body: JSON.stringify(payload(id)),
  }));
  const id1 = randomUUID();
  assert.equal((await reserve(id1)).status, 204);
  assert.equal((await reserve(randomUUID())).status, 429);
  assert.equal((await object.fetch(new Request("https://quota.internal/release", {
    method: "POST", body: JSON.stringify({ id: id1 }),
  }))).status, 204);
  assert.equal((await reserve(randomUUID())).status, 204);
});
