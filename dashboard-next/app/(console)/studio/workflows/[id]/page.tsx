import { adminFetch } from "@/lib/bridge";
import { workflowRecord } from "@/lib/workflows/server";
import { WorkflowEditor } from "@/components/workflows/editor";
import type { Catalog } from "@/lib/workflows/types";
export default async function EditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [record, catalog] = await Promise.all([
    workflowRecord(id),
    adminFetch<Catalog>("/workflows/catalog"),
  ]);
  return (
    <WorkflowEditor
      key={`${record.id}-${record.revision}`}
      initial={record}
      catalog={catalog}
    />
  );
}
