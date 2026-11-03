/**
 * Bot-scoped relay authentication and strict global Worker quotas.
 *
 * RELAY_CLIENTS_JSON must be provisioned as an encrypted Cloudflare secret:
 * { "<bot-uuid>": { "token_sha256": "<64 hex>", "keys": {"1": "<key>"},
 *   "rps": 5, "max_inflight": 10 } }
 * A Worker may serve many bot UUIDs; each has a separate key and token hash.
 */
const ENCODER = new TextEncoder();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HEX = /^[0-9a-f]{64}$/;
const VERSION = /^[1-9][0-9]{0,8}$/;
const TOKEN_PATH = /^\/(?:file\/)?bot([0-9]+:[A-Za-z0-9_-]{20,})(?:\/|$)/;

async function sha256(value) {
  const bytes = await crypto.subtle.digest("SHA-256", ENCODER.encode(value));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
}

/** A length-normalized fixed-work digest comparison, without early returns. */
function equalHex(left, right) {
  const a = HEX.test(left) ? left : "0".repeat(64);
  const b = HEX.test(right) ? right : "0".repeat(64);
  let mismatch = left.length !== 64 || right.length !== 64 ? 1 : 0;
  for (let index = 0; index < 64; index += 1) {
    mismatch |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return mismatch === 0;
}

/**
 * Validate a route-scoped key AND the Telegram bot token in the URL.
 * Never select a client from the token alone; signed request headers select
 * the bot, and the Worker checks both identities before forwarding.
 */
export async function authorizePool(request, env, path) {
  if (typeof env?.RELAY_CLIENTS_JSON !== "string" || !env.RELAY_CLIENTS_JSON) {
    return { ok: false, status: 503 };
  }
  let records;
  try {
    records = JSON.parse(env.RELAY_CLIENTS_JSON);
  } catch {
    return { ok: false, status: 503 };
  }
  if (!records || typeof records !== "object" || Array.isArray(records)) {
    return { ok: false, status: 503 };
  }
  const botId = request.headers.get("x-relay-bot-id") || "";
  const version = request.headers.get("x-relay-version") || "";
  const key = request.headers.get("x-relay-key") || "";
  const match = TOKEN_PATH.exec(path);
  if (!UUID.test(botId) || !VERSION.test(version) || !match || key.length < 32) {
    return { ok: false, status: 401 };
  }
  if (!Object.hasOwn(records, botId)) {
    return { ok: false, status: 401 };
  }
  const client = records[botId];
  const expected = client?.keys?.[version];
  if (
    typeof expected !== "string" || expected.length < 32
    || typeof client?.token_sha256 !== "string"
    || !HEX.test(client.token_sha256)
  ) {
    return { ok: false, status: 401 };
  }
  // Hash both secrets before comparing. Token hashes are never logged.
  const [actualKeyHash, expectedKeyHash, tokenHash] = await Promise.all([
    sha256(key), sha256(expected), sha256(match[1]),
  ]);
  if (
    !equalHex(actualKeyHash, expectedKeyHash)
    || !equalHex(tokenHash, client.token_sha256)
  ) {
    return { ok: false, status: 401 };
  }
  const rps = Number(client.rps);
  const maxInflight = Number(client.max_inflight);
  if (
    !Number.isInteger(rps) || rps < 1 || rps > 20
    || !Number.isInteger(maxInflight)
    || maxInflight < 1 || maxInflight > 50
  ) {
    return { ok: false, status: 503 };
  }
  return {
    ok: true, botId,
    rps, maxInflight,
  };
}

/** Access the single global Durable Object for quotas across Worker isolates. */
export async function reserveQuota(env, policy) {
  if (!env?.RELAY_QUOTA) {
    return { ok: false, status: 503 };
  }
  const globalRps = Number(env.RELAY_GLOBAL_RPS);
  const globalInflight = Number(env.RELAY_GLOBAL_INFLIGHT);
  if (
    !Number.isInteger(globalRps) || globalRps < 1 || globalRps > 100
    || !Number.isInteger(globalInflight)
    || globalInflight < 1 || globalInflight > 200
  ) {
    return { ok: false, status: 503 };
  }
  const id = crypto.randomUUID();
  const stub = env.RELAY_QUOTA.get(env.RELAY_QUOTA.idFromName("relay-v2-global"));
  try {
    const response = await stub.fetch(new Request("https://quota.internal/reserve", {
      method: "POST",
      body: JSON.stringify({
        id, bot_id: policy.botId, rps: policy.rps,
        max_inflight: policy.maxInflight,
        global_rps: globalRps, global_inflight: globalInflight,
      }),
    }));
    return response.ok
      ? { ok: true, id, stub }
      : { ok: false, status: response.status === 429 ? 429 : 503 };
  } catch {
    // Quota outages never allow an unmetered provider request.
    return { ok: false, status: 503 };
  }
}

/** Release one completed network operation without retrying its side effect. */
export async function releaseQuota(reservation) {
  if (!reservation?.ok) return;
  try {
    await reservation.stub.fetch(new Request("https://quota.internal/release", {
      method: "POST", body: JSON.stringify({ id: reservation.id }),
    }));
  } catch {
    // Leases expire conservatively after 60s, not by replaying the send.
  }
}

/**
 * One global persistent quota owner, shared by all isolates of this Worker.
 * Usage is stored across Durable Object restarts. A lease can expire without
 * assuming anything about the upstream result.
 */
export class RelayQuota {
  constructor(ctx) {
    this.ctx = ctx;
  }

  async fetch(request) {
    if (request.method !== "POST") return new Response(null, { status: 405 });
    let body;
    try {
      body = await request.json();
    } catch {
      return new Response(null, { status: 400 });
    }
    return this.ctx.blockConcurrencyWhile(async () => {
      const now = Date.now();
      const bucket = Math.floor(now / 1000);
      const state = await this.ctx.storage.get("quota") || {
        bucket, total: 0, per_bot: {}, leases: {},
      };
      if (state.bucket !== bucket) {
        state.bucket = bucket;
        state.total = 0;
        state.per_bot = {};
      }
      for (const [id, lease] of Object.entries(state.leases)) {
        if (lease.expires_at <= now) delete state.leases[id];
      }
      if (new URL(request.url).pathname === "/release") {
        if (typeof body?.id === "string") {
          delete state.leases[body.id];
          await this.ctx.storage.put("quota", state);
        }
        return new Response(null, { status: 204 });
      }
      if (new URL(request.url).pathname !== "/reserve") {
        return new Response(null, { status: 404 });
      }
      const leases = Object.values(state.leases);
      const activeBot = leases.filter(lease => lease.bot_id === body.bot_id).length;
      const usedBot = state.per_bot[body.bot_id] || 0;
      if (
        !UUID.test(body?.bot_id || "")
        || typeof body.id !== "string" || !UUID.test(body.id)
        || !Number.isInteger(body.rps) || body.rps < 1 || body.rps > 20
        || !Number.isInteger(body.global_rps) || body.global_rps < 1
        || !Number.isInteger(body.max_inflight) || body.max_inflight < 1
        || !Number.isInteger(body.global_inflight) || body.global_inflight < 1
      ) {
        return new Response(null, { status: 400 });
      }
      if (
        state.total >= body.global_rps || usedBot >= body.rps
        || leases.length >= body.global_inflight
        || activeBot >= body.max_inflight
      ) {
        return new Response(null, {
          status: 429, headers: { "retry-after": "1" },
        });
      }
      state.total += 1;
      state.per_bot[body.bot_id] = usedBot + 1;
      state.leases[body.id] = { bot_id: body.bot_id, expires_at: now + 60_000 };
      await this.ctx.storage.put("quota", state);
      return new Response(null, { status: 204 });
    });
  }
}
