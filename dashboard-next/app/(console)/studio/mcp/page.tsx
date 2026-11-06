import { adminFetch } from "@/lib/bridge";
import { PageHeading } from "@/components/blocks/page-heading";
import { StudioHomeNav } from "@/components/workflows/studio-home-nav";
import { McpConnections } from "@/components/mcp/connections";
import type { McpHistoryPage, McpPage, McpPairingView } from "@/lib/mcp/types";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const pageNumber = (value?: string) => value && /^\d{1,6}$/.test(value)
  ? Math.max(1, Math.min(100000, Number(value))) : 1;

/** Only the server reads the signed human session and chooses native targets. */
export default async function McpPage({ searchParams }: {
  searchParams: Promise<{ page?: string; history_page?: string; pairing?: string }>;
}) {
  const query = await searchParams;
  const [data, history] = await Promise.all([
    adminFetch<McpPage>("/mcp?page=" + pageNumber(query.page)),
    adminFetch<McpHistoryPage>("/mcp/history?page=" + pageNumber(query.history_page)),
  ]);
  let pairing: McpPairingView | null = null;
  let pairingError = false;
  if (query.pairing) {
    if (!uuid.test(query.pairing)) pairingError = true;
    else {
      try { pairing = await adminFetch<McpPairingView>("/mcp/pairings/" + query.pairing); }
      catch { pairingError = true; }
    }
  }
  return <div className="min-w-0">
    <StudioHomeNav current="mcp" />
    <PageHeading title="MCP connections" description="دسترسی اتصال‌های WPMCP به Store انتخاب‌شده و رسیدهای Native را بررسی کنید." />
    <McpConnections key={`${data.actor_id}:${data.store_id}:${data.enabled}:${data.page}:${history.page}:${pairing?.id ?? "none"}:${pairing?.can_confirm}`} initial={data} history={history} pairing={pairing} pairingError={pairingError} />
  </div>;
}
