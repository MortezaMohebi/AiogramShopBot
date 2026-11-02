/**
 * Node's native Fetch implementation exercises the Worker without real API
 * requests, paid Cloudflare resources or a Telegram bot token.
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import worker from "../src/index.mjs";

const SECRET = "test-relay-key-with-at-least-32-characters";
const TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd";
const BASE = "https://dynamic-relay.example.workers.dev";
const ORIGINAL_FETCH = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

test("rejects unauthenticated requests without contacting Telegram", async () => {
  globalThis.fetch = () => {
    throw Error("Upstream must not be called.");
  };
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/getMe`, { method: "POST" }),
    { RELAY_SHARED_SECRET: SECRET },
  );
  assert.equal(response.status, 401);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("fails closed if Worker secret has not been provisioned", async () => {
  const response = await worker.fetch(
    new Request(`${BASE}/bot${TOKEN}/getMe`, {
      method: "POST",
      headers: { "x-telegram-relay-key": SECRET },
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
    headers: { "x-telegram-relay-key": SECRET },
  });
  const response = await worker.fetch(request, { RELAY_SHARED_SECRET: SECRET });
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
        "x-telegram-relay-key": SECRET,
        "authorization": "Bearer attacker-supplied",
        "cookie": "private=1",
      },
      body: "--example\r\ncontent\r\n--example--\r\n",
    }),
    { RELAY_SHARED_SECRET: SECRET },
  );
  assert.equal(response.status, 200);
  assert.equal(forwarded.url, `https://api.telegram.org/bot${TOKEN}/sendPhoto`);
  assert.equal(forwarded.method, "POST");
  assert.equal(forwarded.redirect, "manual");
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
      headers: { "x-telegram-relay-key": SECRET },
    }),
    { RELAY_SHARED_SECRET: SECRET },
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
      headers: { "x-telegram-relay-key": SECRET },
    }),
    { RELAY_SHARED_SECRET: SECRET },
  );
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("location"), null);
});

test("does not allow a POST request to download a file", async () => {
  const response = await worker.fetch(
    new Request(`${BASE}/file/bot${TOKEN}/photos/photo.jpg`, {
      method: "POST",
      headers: { "x-telegram-relay-key": SECRET },
      body: "x",
    }),
    { RELAY_SHARED_SECRET: SECRET },
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
      headers: { "x-telegram-relay-key": SECRET },
    }),
    { RELAY_SHARED_SECRET: SECRET },
  );
  assert.equal(response.status, 502);
  const body = await response.text();
  assert.equal(body.includes(TOKEN), false);
  assert.equal(body.includes(SECRET), false);
});
