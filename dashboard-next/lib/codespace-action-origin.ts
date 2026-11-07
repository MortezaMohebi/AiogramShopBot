/** Restore only the Codespaces loopback Origin rewrite. Fetch Metadata and
 * the exact configured forwarded host must agree; other requests are unchanged.
 */
export function codespaceActionHeaders(method: string, headers: Headers, configured: string): Headers {
  let url: URL;
  try { url = new URL(configured); } catch { return headers; }
  const match = url.hostname.match(/^[a-z0-9-]+-([0-9]{1,5})\.app\.github\.dev$/);
  if (method !== "POST" || !headers.get("next-action") ||
      url.protocol !== "https:" || configured !== url.origin ||
      url.username || url.password || !match ||
      headers.get("sec-fetch-site") !== "same-origin" ||
      headers.get("x-forwarded-host") !== url.host ||
      headers.get("origin") !== `http://localhost:${match[1]}`) return headers;
  const restored = new Headers(headers);
  restored.set("origin", url.origin);
  return restored;
}
