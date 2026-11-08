import { NextResponse, type NextRequest } from "next/server";
import { codespaceActionHeaders } from "./lib/codespace-action-origin";

/** Restore verified Codespaces metadata before Next enforces action CSRF. */
export function proxy(request: NextRequest) {
  const headers = codespaceActionHeaders(request.method, request.headers,
    process.env.NEXT_ADMIN_PUBLIC_ORIGIN ?? "");
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
