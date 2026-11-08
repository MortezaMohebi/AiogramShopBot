/**
 * Installation is online only. Never intercept fetches or open CacheStorage:
 * navigation, credentials, API responses, and private media stay on the network.
 */
const worker = `
"use strict";
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
`;

export const dynamic = "force-dynamic";

export function GET() {
  return new Response(worker, {
    headers: {
      "Content-Type": "application/javascript; charset=utf-8",
      "Cache-Control": "no-store, max-age=0",
      "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'none'",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
