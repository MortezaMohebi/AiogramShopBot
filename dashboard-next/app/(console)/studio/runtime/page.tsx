import Link from "next/link";
import { adminFetch } from "@/lib/bridge";
import { PageHeading } from "@/components/blocks/page-heading";
import { StudioHomeNav } from "@/components/workflows/studio-home-nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RuntimeRefresh } from "@/components/runtime/refresh";
import { RuntimeOperationalOverview } from "@/components/runtime/overview";
import { RuntimeGates } from "@/components/runtime/gates";
import { RuntimePublications } from "@/components/runtime/publication";
import { RuntimeBindings, RuntimeDeliveries, RuntimeHistory, RuntimeRuns } from "@/components/runtime/lists";
import { RuntimePanel, RuntimePager } from "@/components/runtime/shared";
import { gateStatus, gateLabels, runLabels, deliveryLabels } from "@/lib/runtime/state";
import type { Binding, HistoryItem, OutboxItem, Page, Publication, Run, RuntimeOverview } from "@/lib/runtime/types";
import type { BotChoice, WorkflowList } from "@/lib/workflows/types";
import type { StoreContextSnapshot } from "@/lib/store-context";
const tabs = [{
  key: "overview",
  label: "وضعیت و مجوز اجرا"
}, {
  key: "publications",
  label: "انتشار و بازگشت"
}, {
  key: "bindings",
  label: "ورودی‌ها"
}, {
  key: "runs",
  label: "اجراها"
}, {
  key: "outbox",
  label: "ارسال‌ها"
}, {
  key: "history",
  label: "تاریخچه"
}];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
/** Read-only server pages retain signed Store authorization. All mutation controls use the closed BFF. */
export default async function RuntimePage({
  searchParams
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams,
    one = (key: string) => typeof search[key] === "string" ? search[key] as string : "";
  const tab = tabs.some(t => t.key === one("tab")) ? one("tab") : "overview";
  const page = /^[1-9][0-9]{0,6}$/.test(one("page")) ? Number(one("page")) : 1;
  const botPage = /^[1-9][0-9]{0,6}$/.test(one("bot_page")) ? Number(one("bot_page")) : 1;
  const workflowId = uuid.test(one("workflow_id")) ? one("workflow_id") : "",
    publicationId = uuid.test(one("publication_id")) ? one("publication_id") : "";
  const statuses = tab === "outbox" ? deliveryLabels : runLabels,
    status = Object.hasOwn(statuses, one("status")) ? one("status") : "";
  const [overview, context] = await Promise.all([adminFetch<RuntimeOverview>("/workflow-runtime"), adminFetch<StoreContextSnapshot>("/store-context")]);
  const params = new URLSearchParams({
    page: String(page)
  });
  if (status) params.set("status", status);
  if (workflowId && ["runs", "publications"].includes(tab)) params.set("workflow_id", workflowId);
  if (publicationId && tab === "runs") params.set("publication_id", publicationId);
  let content;
  let paged: {
    page: number;
    has_more: boolean;
  } | undefined;
  if (tab === "overview") {
    const bots = await adminFetch<Page<BotChoice>>(`/workflows/bots?page=${botPage}`);
    content = <div className="space-y-5">
  <div className="grid gap-4 lg:grid-cols-2">
    <RuntimePanel title="اجراهای نیازمند بررسی">
      <div className="flex flex-wrap gap-3">
        {["waiting_approval", "failed", "suspended"].map(status => <Link key={status} href={`/studio/runtime?tab=runs&status=${status}`} className="rounded-lg border px-4 py-3 text-sm text-primary hover:bg-muted">{runLabels[status]} · {(overview.runs[status] ?? 0).toLocaleString("fa-IR")}</Link>)}
      </div>
      <p className="text-xs leading-6 text-muted-foreground">شمارش‌ها مربوط به فروشگاه جاری هستند؛ نبود اجرا با قطع ارتباط سرویس یکسان نیست.</p>
    </RuntimePanel>
    <RuntimePanel title="وضعیت تحویل">
      <dl className="space-y-2 text-sm">
        {Object.entries(overview.deliveries).map(([state, count]) => <div key={state} className="flex flex-wrap justify-between gap-3">
          <dt>
            <Link className="text-primary hover:underline" href={`/studio/runtime?tab=outbox&status=${state}`}>
              {deliveryLabels[state] ?? state}
            </Link>
          </dt>
          <dd>
            {count.toLocaleString("fa-IR")}
          </dd>
        </div>)}
      </dl>
      {!Object.keys(overview.deliveries).length && <p className="text-sm text-muted-foreground">ارسالی ثبت نشده است.</p>}
      <p className="text-xs leading-6 text-muted-foreground">در صف، ارسال‌شده و نتیجهٔ نامعلوم وضعیت‌های جدا هستند.</p>
    </RuntimePanel>
  </div>
  <RuntimeOperationalOverview overview={overview} />
  <RuntimeGates key={context.current_store_id} overview={overview} bots={bots.items} storeId={context.current_store_id} />
  <RuntimePager page={botPage} hasMore={bots.has_more} href={p => `/studio/runtime?bot_page=${p}`} />
  <details className="rounded-xl border bg-card p-4">
    <summary className="cursor-pointer text-sm">گره‌های پشتیبانی‌شدهٔ Runtime</summary>
    <p dir="ltr" className="mt-3 break-words text-xs leading-7">
      {overview.supported_nodes.join(" · ")}
    </p>
  </details>
</div>;
  } else if (tab === "publications") {
    const [publications, bindings, workflows, bots] = await Promise.all([adminFetch<Page<Publication>>(`/workflow-runtime/publications?${params}`), adminFetch<Page<Binding>>("/workflow-runtime/bindings"), adminFetch<WorkflowList>("/workflows?status=draft"), adminFetch<Page<BotChoice>>("/workflows/bots")]);
    paged = publications;
    content = <RuntimePublications key={`${context.current_store_id}-${overview.can_publish}`} publications={publications} bindings={bindings} workflows={workflows} bots={bots} canPublish={overview.can_publish} />;
  } else if (tab === "bindings") {
    const data = await adminFetch<Page<Binding>>(`/workflow-runtime/bindings?page=${page}`);
    paged = data;
    content = <RuntimeBindings items={data.items} />;
  } else if (tab === "runs") {
    const data = await adminFetch<Page<Run>>(`/workflow-runtime/runs?${params}`);
    paged = data;
    content = <RuntimeRuns items={data.items} filtered={!!(status || workflowId || publicationId)} />;
  } else if (tab === "outbox") {
    const data = await adminFetch<Page<OutboxItem>>(`/workflow-runtime/outbox?${params}`);
    paged = data;
    content = <RuntimeDeliveries items={data.items} canManage={overview.can_manage} />;
  } else {
    const data = await adminFetch<Page<HistoryItem>>(`/workflow-runtime/history?page=${page}`);
    paged = data;
    content = <RuntimeHistory items={data.items} />;
  }
  const href = (p: number) => {
    const next = new URLSearchParams(params);
    next.set("tab", tab);
    next.set("page", String(p));
    return `/studio/runtime?${next}`;
  };
  return <div className="min-w-0 space-y-5">
  <StudioHomeNav current="runtime" />
  <PageHeading title="Runtime فرایندها" description="نسخه‌های منتشرشده، ورودی ربات‌ها و اجرای فرایندهای فروشگاه جاری را بررسی کنید. انتشار و مجوز اجرا نیازمند انتخاب و تأیید جدا هستند." action={<RuntimeRefresh />} />
  <div className="rounded-xl border bg-muted/30 px-4 py-3 text-sm leading-7" role="status">{gateLabels[gateStatus(overview)]}. هیچ پیش‌نویسی به‌صورت خودکار اجرا نمی‌شود.</div>
  <nav aria-label="بخش‌های Runtime" className="flex flex-wrap gap-2">
    {tabs.map(item => <Link key={item.key} href={`/studio/runtime?tab=${item.key}`} aria-current={tab === item.key ? "page" : undefined} className={`rounded-md border px-3 py-2 text-xs focus-visible:outline-2 focus-visible:outline-ring ${tab === item.key ? "border-primary bg-primary/10 text-primary" : "hover:bg-muted"}`}>
      {item.label}
    </Link>)}
  </nav>
  {["runs", "outbox", "publications"].includes(tab) && <form action="/studio/runtime" className="flex flex-wrap items-end gap-3 rounded-xl border bg-card p-4">
    <input type="hidden" name="tab" value={tab} />
    {tab !== "publications" && <label className="min-w-0 space-y-2 text-xs">
      <span>وضعیت</span>
      <select name="status" defaultValue={status} className="h-10 w-full rounded-md border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring">
        <option value="">همهٔ وضعیت‌ها</option>
        {Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>
          {label}
        </option>)}
      </select>
    </label>}
    {tab !== "outbox" && <label className="min-w-0 flex-1 space-y-2 text-xs">
      <span>شناسهٔ فرایند</span>
      <Input name="workflow_id" dir="ltr" defaultValue={workflowId} maxLength={36} pattern={uuid.source} />
    </label>}
    {tab === "runs" && <label className="min-w-0 flex-1 space-y-2 text-xs">
      <span>شناسهٔ انتشار</span>
      <Input name="publication_id" dir="ltr" defaultValue={publicationId} maxLength={36} pattern={uuid.source} />
    </label>}
    <Button type="submit" variant="outline">اعمال فیلتر</Button>
    <Link href={`/studio/runtime?tab=${tab}`} className="text-xs text-primary underline">پاک‌کردن فیلترها</Link>
  </form>}
  {content}
  {paged && <RuntimePager page={paged.page} hasMore={paged.has_more} href={href} />}
</div>;
}
