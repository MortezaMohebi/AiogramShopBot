import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { controlJson } from "@/lib/control-request";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";

export const runtime = "nodejs";

function failure(code: string, status: number) {
  return NextResponse.json({ ok: false, code }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Forward a bounded, CSRF-protected setup request to the signed backend. */
export async function POST(request: NextRequest) {
  if (!publicOrigin(request)) return failure("service_unavailable", 503);
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return failure("security_check_failed", 403);
  }

  let raw: unknown;
  try { raw = await controlJson(request, 4096); }
  catch { return failure("invalid_request", 422); }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return failure("invalid_request", 422);
  }
  const { username, password, setup_code } = raw as Record<string, unknown>;
  if (typeof username !== "string" || !/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username)
    || typeof password !== "string" || !password || password.length > 256
    || typeof setup_code !== "string" || !/^[0-9]{10}\.[a-f0-9]{64}$/.test(setup_code)) {
    return failure("invalid_request", 422);
  }

  try {
    const result = await bridgeFetch<{ ok?: boolean }>("/auth/owner-setup", "POST", {
      username, password, setup_code,
    }, null);
    if (result?.ok !== true) return failure("service_unavailable", 503);
    return NextResponse.json({ ok: true }, {
      status: 201, headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError && error.code && [
      "invalid_setup_code", "owner_already_configured", "password_policy_failed", "invalid_request",
    ].includes(error.code)) {
      return failure(error.code, error.status);
    }
    return failure("service_unavailable", 503);
  }
}
