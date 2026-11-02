import { NextResponse, type NextRequest } from "next/server";
import { sessionCookieName } from "@/lib/session";

/** Logout is POST-only and requires same-origin browser intent. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (request.headers.get("origin") !== request.nextUrl.origin) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.delete(sessionCookieName());
  return response;
}
