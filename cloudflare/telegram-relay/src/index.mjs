/**
 * Authenticated Telegram Bot API relay (Cloudflare Module Worker).
 *
 * The target hostname is intentionally fixed. Only the Bot API and its file
 * endpoint can be reached; no arbitrary upstream URL is ever accepted.
 * The relay secret is an encrypted Worker binding, not a committed variable.
 */

import { authorizePool, reserveQuota, releaseQuota } from "./pool-auth.mjs";
export { RelayQuota } from "./pool-auth.mjs";

const AUTH_HEADER = "x-telegram-relay-key";
const BOT_API_PATH = /^\/bot[0-9]+:[A-Za-z0-9_-]{20,}\/[A-Za-z][A-Za-z0-9_]*$/;
const BOT_FILE_PATH = /^\/file\/bot[0-9]+:[A-Za-z0-9_-]{20,}\/.+$/;
const ENCODER = new TextEncoder();

/**
 * Compare SHA-256 digests in fixed time, without exposing raw secret values.
 *
 * @param {string | null} received - Authentication header supplied by caller.
 * @param {string} expected - Worker secret binding.
 * @returns {Promise<boolean>} True when the shared keys match.
 */
async function authorized(received, expected) {
  if (typeof received !== "string" || !received) {
    return false;
  }
  const [first, second] = await Promise.all([
    crypto.subtle.digest("SHA-256", ENCODER.encode(received)),
    crypto.subtle.digest("SHA-256", ENCODER.encode(expected)),
  ]);
  const a = new Uint8Array(first);
  const b = new Uint8Array(second);
  let difference = 0;
  for (let i = 0; i < a.length; i += 1) {
    difference |= a[i] ^ b[i];
  }
  return difference === 0;
}

/**
 * Return a generic, never-cacheable error without echoing credentials.
 *
 * @param {number} status - HTTP status code.
 * @param {string} message - Safe error message.
 * @returns {Response} Sanitized response.
 */
function reject(status, message) {
  return new Response(message, {
    status,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

/**
 * Forward an authorized Bot API request to Telegram without buffering media.
 *
 * @param {Request} request - Inbound Worker request.
 * @param {{ RELAY_SHARED_SECRET: string }} env - Secret bindings.
 * @returns {Promise<Response>} Upstream response or sanitized error.
 */
async function handleRequest(request, env) {
  const poolMode = env && Object.prototype.hasOwnProperty.call(
    env, "RELAY_CLIENTS_JSON",
  );
  if (!poolMode) {
    // Existing v1 deployment remains compatible until explicit migration.
    if (!env || typeof env.RELAY_SHARED_SECRET !== "string"
      || env.RELAY_SHARED_SECRET.length < 32) {
      return reject(503, "Relay is not configured.");
    }
    if (!await authorized(request.headers.get(AUTH_HEADER), env.RELAY_SHARED_SECRET)) {
      return reject(401, "Unauthorized.");
    }
  }

  const incoming = new URL(request.url);
  if (incoming.username || incoming.password) {
    return reject(400, "Invalid relay URL.");
  }

  const isApiMethod = BOT_API_PATH.test(incoming.pathname);
  const isFile = BOT_FILE_PATH.test(incoming.pathname);
  if (!isApiMethod && !isFile) {
    return reject(404, "Not found.");
  }

  if (isFile ? request.method !== "GET" : !["GET", "POST"].includes(request.method)) {
    return reject(405, "Method not allowed.");
  }

  // A v2 Worker must have an authenticated per-bot mapping and a global
  // Durable Object quota before it can issue ANY Telegram API request.
  let reservation = null;
  if (poolMode) {
    const policy = await authorizePool(request, env, incoming.pathname);
    if (!policy.ok) {
      return reject(policy.status, "Relay authentication unavailable.");
    }
    reservation = await reserveQuota(env, policy);
    if (!reservation.ok) {
      return reject(reservation.status, "Relay quota unavailable.");
    }
  }

  // This is the only permitted upstream. The inbound Host and query never
  // determine the destination hostname, preventing an open/SSRF proxy.
  const upstream = new URL(incoming.pathname + incoming.search, "https://api.telegram.org");

  // Clone the original body (including multipart boundaries) as a stream.
  const outbound = new Request(upstream.toString(), request);
  for (const name of [
    AUTH_HEADER,
    "x-relay-bot-id",
    "x-relay-key",
    "x-relay-version",
    "authorization",
    "cookie",
    "host",
    "proxy-authorization",
    "x-forwarded-for",
    "x-real-ip",
    "forwarded",
  ]) {
    outbound.headers.delete(name);
  }

  try {
    const response = await fetch(outbound, { redirect: "manual" });
    // Never forward a redirect to an unverified host.
    if (response.status >= 300 && response.status < 400) {
      return reject(502, "Unexpected Telegram redirect.");
    }
    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("set-cookie");
    responseHeaders.set("cache-control", "no-store");
    responseHeaders.set("x-content-type-options", "nosniff");

    const noBody = [204, 205, 304].includes(response.status);
    return new Response(noBody ? null : response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch {
    // No URL, token, or upstream exception text is sent back or logged.
    return reject(502, "Telegram upstream is unavailable.");
  } finally {
    await releaseQuota(reservation);
  }
}

export default {
  fetch: handleRequest,
};
