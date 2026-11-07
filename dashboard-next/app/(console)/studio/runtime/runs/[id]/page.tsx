import Link from "next/link";
import { notFound } from "next/navigation";
import { adminFetch, ApiError } from "@/lib/bridge";
import { PageHeading } from "@/components/blocks/page-heading";
import { StudioHomeNav } from "@/components/workflows/studio-home-nav";
import { RuntimeRefresh } from "@/components/runtime/refresh";
import { RuntimeDate, RuntimeEmpty, RuntimeId, RuntimePanel, RuntimeStatus } from "@/components/runtime/shared";
import { RuntimeDeliveries } from "@/components/runtime/lists";
import { ApproveAction, RecoverRun } from "@/components/runtime/operations";
import type { RunDetail, RuntimeOverview } from "@/lib/runtime/types";
/** Render the server's private projection only; do not stringify event summaries or Action output. */
export default async function RuntimeRunPage({
  params
}: {
  params: Promise<{
    id: string;
  }>;
}) {
  const {
    id
  } = await params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) notFound();
  let run: RunDetail, overview: RuntimeOverview;
  try {
    [run, overview] = await Promise.all([adminFetch<RunDetail>(`/workflow-runtime/runs/${id}`), adminFetch<RuntimeOverview>("/workflow-runtime")]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  return <div className="min-w-0 space-y-5">
  <StudioHomeNav current="runtime" />
  <PageHeading title="جزئیات اجرا" action={<RuntimeRefresh />} />
  <Link className="inline-block text-sm text-primary underline" href="/studio/runtime?tab=runs">بازگشت به اجراها</Link>
  <RuntimePanel title="وضعیت اجرا">
    <RuntimeStatus status={run.status} />
    <dl className="grid min-w-0 gap-4 text-xs sm:grid-cols-2 xl:grid-cols-3">
      {[["شناسهٔ اجرا", run.id], ["فروشگاه", run.store_id], ["ربات", run.bot_id], ["پیام‌رسان", run.platform], ["فرایند", run.workflow_id], ["انتشار ثابت", run.publication_id], ["گره جاری", run.node_id], ["Correlation ID", run.correlation_id]].map(([label, value]) => <div key={label} className="min-w-0">
        <dt className="text-muted-foreground">
          {label}
        </dt>
        <dd className="mt-1">
          <RuntimeId>
            {value}
          </RuntimeId>
        </dd>
      </div>)}
      <div>
        <dt className="text-muted-foreground">نسخهٔ فرایند / اجرا</dt>
        <dd className="mt-1">r{run.revision} / {run.lock_version}</dd>
      </div>
      {[["شروع", run.created_at], ["به‌روزرسانی", run.updated_at], ["انقضا", run.expires_at]].map(([label, value]) => <div key={label}>
        <dt className="text-muted-foreground">
          {label}
        </dt>
        <dd className="mt-1">
          <RuntimeDate value={value} />
        </dd>
      </div>)}
    </dl>
    {run.error_code && <p className="text-xs">کد خطا <RuntimeId>
        {run.error_code}
      </RuntimeId></p>}
    <p className="text-xs leading-6 text-muted-foreground">این اجرا به نسخهٔ آغاز خود متصل است. انتشار یا بازگشت نسخهٔ جدید آن را جابه‌جا نمی‌کند.</p>
  </RuntimePanel>
  <div className="grid min-w-0 items-start gap-5 lg:grid-cols-2">
    <RuntimePanel title="متغیرها">
      <p className="text-xs leading-6 text-muted-foreground">مقدار متغیرها خصوصی است؛ فقط نوع و ثبت‌شدن مقدار نمایش داده می‌شود.</p>
      {run.variables.map(variable => <div key={variable.name} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border p-3 text-xs">
        <div className="min-w-0 space-y-1">
          <p>
            <RuntimeId>
              {variable.name}
            </RuntimeId>
          </p>
          <p>
            <RuntimeId>
              {variable.type}
            </RuntimeId>
          </p>
        </div>
        <span>
          {variable.is_set ? "مقدار ثبت شده · خصوصی" : "بدون مقدار"}
        </span>
      </div>)}
      {!run.variables.length && <RuntimeEmpty>متغیری در تعریف این نسخه نیست.</RuntimeEmpty>}
    </RuntimePanel>
    <RuntimePanel title="بازیابی اجرا">
      <RecoverRun key={`${run.id}-${run.lock_version}`} run={{id:run.id,status:run.status,lock_version:run.lock_version,expires_at:run.expires_at,actions:run.actions.map(action=>({status:action.status})),outbox:run.outbox.map(item=>({status:item.status,error_code:item.error_code}))}} canManage={overview.can_manage} />
    </RuntimePanel>
  </div>
  <RuntimePanel title="Actionها و رسید اجرا">
    {run.actions.map(action => <article key={`${action.id}-${action.status}-${action.expected_version}`} className="min-w-0 space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <RuntimeId>
          {`${action.key}@${action.version}`}
        </RuntimeId>
        <RuntimeStatus status={action.status} />
      </div>
      <p className="text-xs">گره <RuntimeId>
          {action.node_id}
        </RuntimeId> · تلاش {action.attempts}</p>
      <p className="text-xs">شناسهٔ عملیات <RuntimeId>
          {action.id}
        </RuntimeId></p>
      <p className="text-xs">رسید اجرای عملیات <RuntimeId>
          {action.receipt_id ?? "هنوز ثبت نشده"}
        </RuntimeId></p>
      {action.error_code && <p className="text-xs">کد خطا <RuntimeId>
          {action.error_code}
        </RuntimeId></p>}
      <ApproveAction item={action} canManage={overview.can_manage} />
    </article>)}
    {!run.actions.length && <RuntimeEmpty>Actionی در این اجرا ثبت نشده است.</RuntimeEmpty>}
  </RuntimePanel>
  <RuntimePanel title="رویدادها">
    <p className="text-xs leading-6 text-muted-foreground">حداکثر ۲۰۰ رویداد اخیر؛ متن مشتری، شماره تماس، فایل و دادهٔ تأیید نمایش داده نمی‌شوند.</p>
    <ol className="space-y-3">
      {run.events.map(event => <li key={event.id} className="min-w-0 space-y-2 rounded-lg border p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <RuntimeId>
            {event.kind}
          </RuntimeId>
          <RuntimeStatus status={event.status} />
        </div>
        <p className="text-xs text-muted-foreground">
          <RuntimeDate value={event.created_at} />
        </p>
        <p className="text-xs">گره <RuntimeId>
            {event.node_id}
          </RuntimeId></p>
        <p className="text-xs">
          {typeof event.summary.characters === "number" && Number.isSafeInteger(event.summary.characters) ? `${event.summary.characters} نویسه · ` : ""}
          {typeof event.summary.has_file === "boolean" ? event.summary.has_file ? "دارای فایل خصوصی" : "بدون فایل" : ""}
        </p>
        {event.error_code && <p className="text-xs">کد خطا <RuntimeId>
            {event.error_code}
          </RuntimeId></p>}
      </li>)}
    </ol>
    {!run.events.length && <RuntimeEmpty>رویدادی ثبت نشده است.</RuntimeEmpty>}
  </RuntimePanel>
  <RuntimePanel title="ارسال‌ها و رسید تحویل">
    <p className="text-xs leading-6 text-muted-foreground">ثبت در صف به معنی تحویل نیست. نتیجهٔ نامعلوم نیاز به بررسی دارد و دوباره ارسال نمی‌شود. حداکثر ۲۰۰ ارسال این اجرا نمایش داده می‌شود.</p>
    <RuntimeDeliveries items={run.outbox} canManage={overview.can_manage} />
  </RuntimePanel>
</div>;
}
