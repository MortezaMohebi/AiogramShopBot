import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import {
  safeLoginFetchMetadata,
  verifyLoginChallenge,
} from "@/lib/login-challenge";
import { controlJson } from "@/lib/control-request";

export const runtime = "nodejs";
type Context = { params: Promise<{ operation: string }> };
const WRITES: Record<string, string> = {
  stage: "/telegram-transport/stage",
  probe: "/telegram-transport/probe",
  apply: "/telegram-transport/apply",
  rollback: "/telegram-transport/rollback",
  cancel: "/telegram-transport/cancel",
  reconcile: "/telegram-transport/reconcile",
};

function rejected(status: number, code: string): NextResponse {
  return NextResponse.json(
    { ok: false, code, requestId: randomUUID() },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}

/** Read only a redacted, session-bound snapshot of the current transport. */
export async function GET(
  _request: NextRequest, context: Context,
): Promise<NextResponse> {
  const { operation } = await context.params;
  if (operation !== "status") return rejected(404, "not_found");
  const session = await readSession();
  if (!session) return rejected(401, "session_expired");
  try {
    const result = await bridgeFetch(
      "/telegram-transport", "GET", null, session,
    );
    return NextResponse.json(result, {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return rejected(error.status, error.code ?? "transport_unavailable");
    }
    return rejected(503, "transport_unavailable");
  }
}

/**
 * Never expose arbitrary backend routes. A host-bound CSRF challenge
 * accompanies short, bounded JSON; secrets are never put in URL parameters,
 * logs, local storage, response bodies or redirect destinations.
 */
export async function POST(
  request: NextRequest, context: Context,
): Promise<NextResponse> {
  const { operation } = await context.params;
  if (!Object.hasOwn(WRITES, operation)) return rejected(404, "not_found");
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return rejected(403, "security_check_failed");
  }
  const session = await readSession();
  if (!session) return rejected(401, "session_expired");

  let values: unknown;
  try {
    values = await controlJson(request, 4_096);
  } catch {
    return rejected(422, "invalid_request");
  }
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return rejected(422, "invalid_request");
  }

  try {
    const result = await bridgeFetch<Record<string, unknown>>(
      WRITES[operation], "POST", values, session,
      operation === "apply" || operation === "reconcile" ? 70_000 : 25_000,
    );
    return NextResponse.json(result, {
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return rejected(
        error.status,
        error.code ?? (
          error.status === 401 ? "session_expired" :
          error.status === 403 ? "permission_denied" :
          "transport_unavailable"
        ),
      );
    }
    return rejected(503, "transport_unavailable");
  }
}
