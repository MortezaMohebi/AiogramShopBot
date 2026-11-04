import { adminFetch } from "@/lib/bridge";
import { workflowRecord } from "@/lib/workflows/server";
import { WorkflowEditor } from "@/components/workflows/editor";
import type { Catalog } from "@/lib/workflows/types";
export default async function SettingsPage({
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
    <div className="space-y-7">
      <WorkflowEditor
        key={`${record.id}-${record.revision}`}
        initial={record}
        catalog={catalog}
        settings
      />
    </div>
  );
}
