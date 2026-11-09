import Link from "next/link";
import { notFound } from "next/navigation";
import { Plus } from "lucide-react";
import { ListSearch } from "@/components/blocks/search-tools";
import { StoreScopeNotice } from "@/components/blocks/store-scope-notice";
import { PageHeading } from "@/components/blocks/page-heading";
import { RelaySetupGuide } from "@/components/blocks/relay-setup-guide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { optionalStoreRead, currentStaff } from "@/lib/bridge";
import { relayWorkerLabels, type RelayWorkersSnapshot } from "@/lib/relay-pool";

export default async function RelayWorkersPage({ searchParams }: {
  searchParams: Promise<{ saved?: string; search?: string; state?: string }>;
}) {
  if ((await currentStaff()).role !== "superadmin") notFound();
  const query = await searchParams;
  const data = await optionalStoreRead<RelayWorkersSnapshot>("/relay-workers");
  if (!data) return <div className="space-y-6">
    <StoreScopeNotice title="سرویس‌های Relay" />
    <RelaySetupGuide />
  </div>;

  const search = query.search?.trim().slice(0, 160) ?? "";
  const state = Object.hasOwn(relayWorkerLabels, query.state ?? "") ? query.state! : "";
  const term = search.toLocaleLowerCase("fa-IR");
  const items = data.items.filter(worker =>
    (!state || worker.status === state) &&
    (!term || [worker.name, worker.origin, worker.slug].some(value => value.toLocaleLowerCase("fa-IR").includes(term))),
  );
  return <div className="space-y-5">
    <PageHeading title="سرویس‌های Relay" action={<Button asChild><Link href="/relay-workers/new"><Plus /> Worker جدید</Link></Button>} />
    {query.saved === "removed" && <p role="status" className="text-sm">Worker و اتصال‌های آن از رجیستری حذف شدند.</p>}
    <Card><CardContent className="space-y-4 pt-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={data.enabled ? "success" : "neutral"}>{data.enabled ? "سرویس روشن" : "سرویس متوقف"}</Badge>
        {!data.enabled && <Link className="text-primary underline" href="/services">تنظیم سرویس</Link>}
      </div>
      <ListSearch path="/relay-workers"
        query={{ name: "search", label: "جست‌وجوی Workerها", value: search, placeholder: "نام یا نشانی Worker…" }}
        values={{ state: { label: "وضعیت", value: state, display: relayWorkerLabels[state] } }}
        filters={<label className="block space-y-2 text-sm">وضعیت
          <select name="state" defaultValue={state} className="block h-10 w-full rounded-md border bg-background px-3">
            <option value="">همه</option>
            {Object.entries(relayWorkerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>} />
      {items.length ? <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[33rem] text-sm">
          <thead className="bg-muted"><tr>
            <th scope="col" className="p-3 text-start">Worker</th>
            <th scope="col" className="p-3 text-start">نشانی</th>
            <th scope="col" className="p-3 text-start">ربات‌ها</th>
            <th scope="col" className="p-3 text-start">وضعیت</th>
          </tr></thead>
          <tbody>{items.map(worker => <RecordClickArea as="tr" key={worker.id} className="border-t">
            <td className="p-3"><RecordLink href={`/relay-workers/${worker.id}`}>{worker.name}</RecordLink></td>
            <td className="p-3"><bdi className="break-all">{worker.origin}</bdi></td>
            <td className="p-3">{worker.bot_count.toLocaleString("fa-IR")}</td>
            <td className="p-3"><Badge tone={worker.status === "active" ? "success" : "neutral"}>{relayWorkerLabels[worker.status]}</Badge></td>
          </RecordClickArea>)}</tbody>
        </table>
      </div> : <p className="py-5 text-center text-sm text-muted-foreground">
        {search || state ? "Worker مطابق جست‌وجو پیدا نشد." : "هنوز Worker ثبت نشده است."}
      </p>}
    </CardContent></Card>
    <RelaySetupGuide />
  </div>;
}
