import "server-only";

import type { NextRequest } from "next/server";

/** The only allowed external HTTPS origin; never trust a forwarded Host. */
export function publicOrigin(request: NextRequest): URL | null {
  const configured = process.env.NEXT_ADMIN_PUBLIC_ORIGIN;
  if (!configured) {
    return process.env.NODE_ENV === "production" ? null : request.nextUrl;
  }

  try {
    const parsed = new URL(configured);
    if (
      parsed.protocol !== "https:" ||
      parsed.username || parsed.password ||
      parsed.search || parsed.hash || parsed.pathname !== "/" ||
      configured !== parsed.origin
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Accept only demonstrably same-origin browser form submissions.
 *
 * Codespaces and some privacy policies can omit Origin on native POST forms.
 * Sec-Fetch-Site: same-origin is browser-controlled evidence, independent of
 * proxy rewriting. An explicit configured Origin is also allowed when Fetch
 * Metadata is absent or says same-site. Cross-site requests always fail.
 */
export function trustedBrowserOrigin(
  request: NextRequest,
): URL | null {
  const expected = publicOrigin(request);
  if (!expected) return null;

  const site = request.headers.get("sec-fetch-site");
  if (site === "cross-site") return null;

  if (site === "same-origin") {
    // This header is set by browsers; JavaScript cannot forge its value.
    return expected;
  }

  const origin = request.headers.get("origin");
  if (
    origin === expected.origin &&
    (site === null || site === "same-site" || site === "none")
  ) {
    return expected;
  }

  return null;
}
