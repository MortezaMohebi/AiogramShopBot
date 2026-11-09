import { NextResponse, type NextRequest } from "next/server";
import { productBotQuery, type ProductBotCatalogList } from "@/lib/bot-catalog-acl";
import { bridgeFetch } from "@/lib/bridge";
import { sectionRpcError } from "@/lib/section-rpc-server";
import { readSession } from "@/lib/session";

const headers = { "Cache-Control": "private, no-store" };

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,15}$/.test(id) || !Number.isSafeInteger(Number(id))) {
    return NextResponse.json({ ok: false, code: "validation" }, { status: 422, headers });
  }
  const session = await readSession();
  if (!session) return NextResponse.json({ ok: false, code: "session_expired" }, { status: 401, headers });
  const query = productBotQuery.read(request.nextUrl.searchParams);
  const search = new URLSearchParams({ q: query.q, page: String(query.page), page_size: "25" });
  try {
    const data = await bridgeFetch<ProductBotCatalogList>(`/bot-catalog/products/${id}?${search}`, "GET", null, session);
    return NextResponse.json({ ok: true, data }, { headers });
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
