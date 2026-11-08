import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { RuntimeDate, RuntimeEmpty, RuntimeId, RuntimeStatus } from "./shared";
import { RetryDelivery } from "./operations";
import type { Binding, HistoryItem, OutboxItem, Run } from "@/lib/runtime/types";
export function RuntimeRuns({
  items,
  filtered = false
}: {
  items: Run[];
  filtered?: boolean;
}) {
  return <div className="space-y-3">
  {items.map(run => <RecordClickArea as="article" key={run.id} className="min-w-0 space-y-3 rounded-xl border bg-card p-4 hover:bg-muted/30">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <RecordLink href={`/studio/runtime/runs/${run.id}`}>
        <RuntimeId>
          {run.id}
        </RuntimeId>
      </RecordLink>
      <RuntimeStatus status={run.status} />
    </div>
    <dl className="grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
      {[["ربات", run.bot_id], ["انتشار ثابت", run.publication_id], ["گره جاری", run.node_id], ["پیام‌رسان", run.platform]].map(([key, value]) => <div key={key} className="min-w-0">
        <dt className="text-muted-foreground">
          {key}
        </dt>
        <dd className="mt-1">
          <RuntimeId>
            {value}
          </RuntimeId>
        </dd>
      </div>)}
    </dl>
    <p className="text-xs text-muted-foreground">به‌روزرسانی <RuntimeDate value={run.updated_at} /></p>
    {run.error_code && <p className="text-xs">کد خطا <RuntimeId>
        {run.error_code}
      </RuntimeId></p>}
  </RecordClickArea>)}
  {!items.length && <RuntimeEmpty>
    {filtered ? "اجرایی با این فیلترها پیدا نشد." : "اجرایی در این صفحه ثبت نشده است."}
  </RuntimeEmpty>}
</div>;
}
export function RuntimeDeliveries({
  items,
  canManage
}: {
  items: OutboxItem[];
  canManage: boolean;
}) {
  return <div className="space-y-3">
  {items.map(item => <article key={`${item.id}-${item.attempts}-${item.status}`} className="min-w-0 space-y-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <RuntimeId>
        {item.id}
      </RuntimeId>
      <RuntimeStatus status={item.status} delivery />
    </div>
    <div className="flex flex-wrap gap-4 text-xs">
      <Link className="text-primary underline" href={`/studio/runtime/runs/${item.run_id}`}>جزئیات اجرا</Link>
      <span>نوع <RuntimeId>
          {item.kind}
        </RuntimeId></span>
      <span>ترتیب {item.sequence} · تعداد تلاش {item.attempts}</span>
    </div>
    <p className="text-xs">گره <RuntimeId>
        {item.node_id}
      </RuntimeId></p>
    {item.error_code && <p className="text-xs">خطا <RuntimeId>
        {item.error_code}
      </RuntimeId></p>}
    {(/unknown|uncertain/.test(item.error_code ?? "") || ["uncertain", "sending"].includes(item.status)) && <p className="text-xs leading-6 text-muted-foreground">نتیجه هنوز قطعی نیست؛ ارسال دوباره ارائه نمی‌شود.</p>}
    {item.message_ids.length > 0 && <p className="text-xs">شناسهٔ رسید پیام‌رسان: {item.message_ids.map((id, index) => <span key={index} className="ms-2">
        <RuntimeId>
          {id}
        </RuntimeId>
      </span>)}</p>}
    <RetryDelivery item={item} canManage={canManage} />
  </article>)}
  {!items.length && <RuntimeEmpty>ارسالی با این وضعیت در این صفحه نیست.</RuntimeEmpty>}
</div>;
}
export function RuntimeBindings({
  items
}: {
  items: Binding[];
}) {
  return <div className="space-y-3">
  {items.map(item => <article key={item.id} className="min-w-0 space-y-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <RuntimeId>
        {`${item.kind}:${item.key}`}
      </RuntimeId>
      <span className="text-xs">{item.enabled ? "ورودی فعال" : "ورودی غیرفعال"} · نسخهٔ اتصال {item.version}</span>
    </div>
    <dl className="grid gap-3 text-xs sm:grid-cols-2">
      <div className="min-w-0">
        <dt className="text-muted-foreground">ربات</dt>
        <dd className="mt-1">
          <RuntimeId>
            {item.bot_id}
          </RuntimeId>
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="text-muted-foreground">انتشار</dt>
        <dd className="mt-1">
          <RuntimeId>
            {item.publication_id}
          </RuntimeId>
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="text-muted-foreground">گره ورود</dt>
        <dd className="mt-1">
          <RuntimeId>
            {item.node_id}
          </RuntimeId>
        </dd>
      </div>
      <div>
        <dt className="text-muted-foreground">قاعده</dt>
        <dd className="mt-1">اولویت {item.priority} · {item.eligibility === "all" ? "همهٔ مشتریان" : "مشتری موجود"} · جایگزین بدون پاسخ</dd>
      </div>
    </dl>
    <Link className="text-xs text-primary underline" href={`/studio/runtime?tab=publications&workflow_id=${item.workflow_id}`}>بررسی نسخه‌های این فرایند</Link>
  </article>)}
  {!items.length && <RuntimeEmpty>ورودی‌ای در این صفحه ثبت نشده است. انتشار نیازمند انتخاب ورودی و ربات است.</RuntimeEmpty>}
</div>;
}
const historyLabels: Record<string, string> = {
  activate: "فعال‌سازی نسخه برای اجراهای جدید",
  retire: "بازنشستگی انتشار",
  gate: "تغییر مجوز اجرا",
  recover: "بازیابی اجرا",
  approve: "تأیید Action",
  retry_delivery: "تلاش مجدد ارسال",
  outbox_retry: "تلاش مجدد ارسال"
};
export function RuntimeHistory({
  items
}: {
  items: HistoryItem[];
}) {
  return <div className="space-y-3">
  {items.map(item => <article key={item.id} className="min-w-0 space-y-2 rounded-lg border bg-card p-4">
    <h2 className="text-sm font-semibold">
      {historyLabels[item.action] ?? "عملیات Runtime"}
      <RuntimeId>
        {item.action}
      </RuntimeId>
    </h2>
    <p className="text-xs text-muted-foreground">
      <RuntimeDate value={item.created_at} />
    </p>
    <p className="text-xs">شناسهٔ عملیات <RuntimeId>
        {item.id}
      </RuntimeId></p>
    <p className="text-xs">مقصد <RuntimeId>
        {item.target_id}
      </RuntimeId></p>
    {Number.isSafeInteger(item.summary.revision) && <p className="text-xs">نسخهٔ r{item.summary.revision}</p>}
    {item.summary.preview_id && <p className="text-xs">پیش‌نمایش <RuntimeId>
        {item.summary.preview_id}
      </RuntimeId></p>}
  </article>)}
  {!items.length && <RuntimeEmpty>عملیاتی در این صفحهٔ تاریخچه ثبت نشده است.</RuntimeEmpty>}
</div>;
}
