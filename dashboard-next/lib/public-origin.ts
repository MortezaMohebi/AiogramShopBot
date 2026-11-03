import "server-only";

import type { NextRequest } from "next/server";

/** Resolve one configured public HTTPS origin behind Codespaces forwarding. */
export function publicOrigin(request: NextRequest): URL | null {
  const configured = process.env.NEXT_ADMIN_PUBLIC_ORIGIN;
  if (!configured) {
    // Local development remains supported without relying on untrusted Host.
    return process.env.NODE_ENV === "production" ? null : request.nextUrl;
  }
  try {
    const origin = new URL(configured);
    if (
      origin.protocol !== "https:" ||
      origin.username || origin.password ||
      origin.search || origin.hash || origin.pathname !== "/" ||
      configured !== origin.origin
    ) {
      return null;
    }
    return origin;
  } catch {
    return null;
  }
}

/** CSRF guard independent of the internal HTTP host of the Next.js server. */
export function trustedBrowserOrigin(
  request: NextRequest,
): URL | null {
  const expected = publicOrigin(request);
  if (!expected) return null;
  if (request.headers.get("origin") !== expected.origin) return null;
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return null;
  return expected;
}
