import { NextResponse, type NextRequest } from "next/server";
import { sessionCookieName } from "@/lib/session";
import { trustedBrowserOrigin } from "@/lib/public-origin";

/** Logout is POST-only and requires same-origin browser intent. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = trustedBrowserOrigin(request);
  if (!origin) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  const response = NextResponse.redirect(new URL("/login", origin), 303);
  response.cookies.delete(sessionCookieName());
  return response;
}
