/**
 * Node's native Fetch implementation exercises the Worker without real API
 * requests, paid Cloudflare resources or a Telegram bot token.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { afterEach, test } from "node:test";
import worker from "../src/index.mjs";

const SECRET = "test-relay-key-with-at-least-32-characters";
const TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd";
const BASE = "https://dynamic-relay.example.workers.dev";
const ORIGINAL_FETCH = globalThis.fetch;
const BOT_ID = "00000000-0000-4000-8000-000000000101";
const AUTH_HEADERS = {
  "x-relay-bot-id": BOT_ID,
  "x-relay-version": "1",
  "x-relay-key": SECRET,
};

/** Supply reviewed per-bot credentials and a local quota stub, without I/O. */
function environment() {
  return {
    RELAY_CLIENTS_JSON: JSON.stringify({
      [BOT_ID]: {
        token_sha256: createHash("sha256").update(TOKEN).digest("hex"),
        keys: { "1": SECRET }, rps: 5, max_inflight: 4,
      },
    }),
    RELAY_GLOBAL_RPS: "10",
    RELAY_GLOBAL_INFLIGHT: "10",
    RELAY_QUOTA: {
      idFromName: name => name,
      get: () => ({ fetch: async () => new Response(null, { status: 204 }) }),
    },
  };
}

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

test("rejects unauthenticated requests without contacting Telegram", async () => {
  globalThis.fetch = () => {
    throw Error("Upstream must not be called.");
  };
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/getMe`, { method: "POST" }),
    environment(),
  );
  assert.equal(response.status, 401);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("fails closed if Worker secret has not been provisioned", async () => {
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/getMe`, {
      method: "POST",
      headers: AUTH_HEADERS,
    }),
    {},
  );
  assert.equal(response.status, 503);
});

test("rejects arbitrary paths and non-Telegram upstream targets", async () => {
  let called = false;
  globalThis.fetch = () => {
    called = true;
    return new Response("unexpected");
  };
  const request = new Request(`${BASE}/https://evil.example/`, {
    headers: AUTH_HEADERS,
  });
  const response = await worker.fetch(request, environment());
  assert.equal(response.status, 404);
  assert.equal(called, false);
});

test("forwards POST multipart bodies unchanged to a fixed Telegram host", async () => {
  let forwarded;
  globalThis.fetch = async (request, options) => {
    forwarded = {
      url: request.url,
      method: request.method,
      headers: request.headers,
      body: await request.text(),
      redirect: options.redirect,
    };
    return new Response(JSON.stringify({ ok: true, result: { id: 1 } }), {
      headers: { "content-type": "application/json", "set-cookie": "private=1" },
    });
  };
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/sendPhoto`, {
      method: "POST",
      headers: {
        "content-type": "multipart/form-data; boundary=example",
        ...AUTH_HEADERS,
        "authorization": "Bearer attacker-supplied",
        "cookie": "private=1",
      },
      body: "--example\r\ncontent\r\n--example--\r\n",
    }),
    environment(),
  );
  assert.equal(response.status, 200);
  await response.text();
  assert.equal(forwarded.url, `https://api.telegram.org/bot${TOKEN}/sendPhoto`);
  assert.equal(forwarded.method, "POST");
  assert.equal(forwarded.redirect, "manual");
  for (const name of Object.keys(AUTH_HEADERS)) {
    assert.equal(forwarded.headers.get(name), null);
  }
  assert.equal(forwarded.headers.get("x-telegram-relay-key"), null);
  assert.equal(forwarded.headers.get("authorization"), null);
  assert.equal(forwarded.headers.get("cookie"), null);
  assert.match(forwarded.body, /--example--/);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("streams a file path without replacing its response bytes", async () => {
  let url;
  globalThis.fetch = async request => {
    url = request.url;
    return new Response(new Uint8Array([0, 1, 255]), {
      headers: { "content-type": "application/octet-stream" },
    });
  };
  const response = await worker.fetch(
    new Request(`${BASE}/file/bot${TOKEN}/photos/any.jpg`, {
      headers: AUTH_HEADERS,
    }),
    environment(),
  );
  assert.equal(url, `https://api.telegram.org/file/bot${TOKEN}/photos/any.jpg`);
  assert.deepEqual(Array.from(new Uint8Array(await response.arrayBuffer())), [0, 1, 255]);
});

test("does not follow upstream redirects into a different origin", async () => {
  globalThis.fetch = async () => new Response(null, {
    status: 302,
    headers: { location: "https://other.example/file" },
  });
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/getMe`, {
      method: "POST",
      headers: AUTH_HEADERS,
    }),
    environment(),
  );
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("location"), null);
});

test("does not allow a POST request to download a file", async () => {
  const response = await worker.fetch(
    new Request(`${BASE}/file/bot${TOKEN}/photos/photo.jpg`, {
      method: "POST",
      headers: AUTH_HEADERS,
      body: "x",
    }),
    environment(),
  );
  assert.equal(response.status, 405);
});

test("keeps the upstream failure text and secrets out of errors", async () => {
  globalThis.fetch = async () => {
    throw new Error(`failed on /bot${TOKEN}/getMe with ${SECRET}`);
  };
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/getMe`, {
      method: "POST",
      headers: AUTH_HEADERS,
    }),
    environment(),
  );
  assert.equal(response.status, 502);
  const body = await response.text();
  assert.equal(body.includes(TOKEN), false);
  assert.equal(body.includes(SECRET), false);
});

test("retired shared-key requests fail closed without any upstream fetch", async () => {
  let called = false;
  globalThis.fetch = () => { called = true; throw Error("unexpected"); };
  for (const settings of [environment(), { RELAY_SHARED_SECRET: SECRET }]) {
    const response = await worker.fetch(new Request(`${BASE}/bot${TOKEN}/getMe`, {
      method: "POST", headers: { "x-telegram-relay-key": SECRET },
    }), settings);
    assert.equal(response.status, 401);
    assert.equal((await response.text()).includes(SECRET), false);
  }
  assert.equal(called, false);
});
