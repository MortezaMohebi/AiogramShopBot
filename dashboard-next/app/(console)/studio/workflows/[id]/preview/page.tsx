import { adminFetch } from "@/lib/bridge";
import { workflowRecord } from "@/lib/workflows/server";
import { WorkflowPreview } from "@/components/workflows/preview";
import type { BotChoice, Catalog, ChoicePage } from "@/lib/workflows/types";
export default async function PreviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [record, catalog] = await Promise.all([
    workflowRecord(id),
    adminFetch<Catalog>("/workflows/catalog"),
  ]);
  const bots = await adminFetch<ChoicePage<BotChoice>>(
    `/workflows/bots?store_id=${record.store_id}`,
  );
  return (
    <WorkflowPreview
      key={`${record.id}-${record.revision}`}
      record={record}
      catalog={catalog}
      initialBots={bots}
    />
  );
}
