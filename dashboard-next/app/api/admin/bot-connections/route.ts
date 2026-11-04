import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";
import type { BotProviderProbe } from "@/lib/bot-connections";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Restricted read-only provider status, without exposing Bot API tokens. */
export async function GET(): Promise<NextResponse> {
  const session = await readSession();
  if (!session) {
    return NextResponse.json(
      { ok: false, code: "session_expired" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (staff.role !== "superadmin") {
      return NextResponse.json(
        { ok: false, code: "permission_denied" },
        { status: 403, headers: { "Cache-Control": "no-store" } },
      );
    }
    // The URL contains no user-controlled provider hostname or secret.
    const probe = await bridgeFetch<BotProviderProbe>(
      "/bot-connections/probe", "GET", null, session,
    );
    return NextResponse.json(
      { ok: true, probe },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    const code = error instanceof ApiError && error.status === 401
      ? "session_expired" : "service_unavailable";
    const requestId = randomUUID();
    console.warn("[shop-admin/connections]", { code, requestId });
    return NextResponse.json(
      { ok: false, code, requestId },
      { status: code === "session_expired" ? 401 : 503,
        headers: { "Cache-Control": "no-store" } },
    );
  }
}
