import { NextResponse, type NextRequest } from "next/server";
import {
  catalogBotId, catalogListParams, parseCatalogListParams,
  type BotCatalogRuleList, type CatalogAuditRow,
} from "@/lib/bot-catalog-acl";
import { bridgeFetch } from "@/lib/bridge";
import { sectionRpcError } from "@/lib/section-rpc-server";
import type { SectionRpcResult } from "@/lib/section-rpc";
import { readSession } from "@/lib/session";

const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const search = request.nextUrl.searchParams;
  const audit = search.size === 1 && search.get("audit") === "1";
  const query = parseCatalogListParams(search);
  if (!catalogBotId.test(id) || (!audit && !query)) {
    return NextResponse.json({ ok: false, code: "validation" }, { status: 422, headers });
  }
  const session = await readSession();
  if (!session) return NextResponse.json({ ok: false, code: "session_expired" }, { status: 401, headers });

  try {
    const base = `/bot-catalog/bots/${id}`;
    const data = query
      ? await bridgeFetch<BotCatalogRuleList>(`${base}?${catalogListParams(query)}`, "GET", null, session)
      : await bridgeFetch<{ items: CatalogAuditRow[] }>(`${base}/audit?page=1`, "GET", null, session);
    return NextResponse.json<SectionRpcResult<typeof data>>({ ok: true, data }, { headers });
  } catch (error) {
    const code = sectionRpcError(error);
    const status = {
      session_expired: 401, permission_denied: 403, store_switch_required: 409,
      validation: 422, reauthentication_required: 428, conflict: 409,
      unavailable: 503, outcome_unknown: 503,
    }[code];
    return NextResponse.json({ ok: false, code }, { status, headers });
  }
}
