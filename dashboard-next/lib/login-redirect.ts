import "server-only";

import { NextResponse } from "next/server";

/** Keep auth navigation on the browser origin, independent of proxy headers. */
export function loginRedirect(error?: string): NextResponse {
  // Location is deliberately relative: request.nextUrl may contain a private
  // loopback address, and forwarded Host must never choose an auth destination.
  const location = error
    ? `/login?error=${encodeURIComponent(error)}`
    : "/login";
  return new NextResponse(null, {
    status: 303,
    headers: { Location: location, "Cache-Control": "no-store" },
  });
}
