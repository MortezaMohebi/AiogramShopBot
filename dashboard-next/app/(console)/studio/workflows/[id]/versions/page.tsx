import { adminFetch } from "@/lib/bridge";
import { workflowRecord } from "@/lib/workflows/server";
import { WorkflowVersions } from "@/components/workflows/versions";
import type { RevisionPage } from "@/lib/workflows/types";
export default async function VersionsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [record, versions] = await Promise.all([
    workflowRecord(id),
    adminFetch<RevisionPage>(`/workflows/${id}/revisions`),
  ]);
  return (
    <WorkflowVersions
      key={`${record.id}-${record.revision}`}
      initial={record}
      initialVersions={versions}
    />
  );
}
