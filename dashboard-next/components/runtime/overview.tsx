import Link from "next/link";
import type { RuntimeMetrics, RuntimeOverview } from "@/lib/runtime/types";
import { RuntimeEmpty, RuntimeId, RuntimePanel } from "./shared";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const countLabels: [Exclude<keyof RuntimeMetrics, "completed_duration_seconds_avg" | "delivery_failures_by_platform">, string][] = [
  ["runs_started", "اجراهای آغازشده"],
  ["runs_completed", "اجراهای تکمیل‌شده"],
  ["runs_cancelled", "اجراهای لغوشده"],
  ["runs_failed", "اجراهای ناموفق"],
  ["node_transitions", "عبور از گره‌ها"],
  ["input_validation_errors", "خطاهای اعتبارسنجی ورودی"],
  ["action_failures", "خطاهای Action"],
  ["timeouts", "پایان مهلت‌ها"],
  ["duplicate_events", "رویدادهای تکراری"],
  ["outbox_retries", "تلاش‌های مجدد ارسال"],
  ["outbox_deadletters", "ارسال‌های متوقف‌شده پس از خطا"]
];

/** Preserve unavailable aggregates rather than presenting missing data as zero. */
function count(value: number | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString("fa-IR") : "در دسترس نیست";
}

/** Only server-supplied operational aggregates are rendered; raw values stay private. */
export function RuntimeOperationalOverview({ overview }: { overview: RuntimeOverview }) {
  const metrics = overview.metrics;
  const duration = metrics?.completed_duration_seconds_avg;
  const groups = overview.active_groups;
  return <div className="min-w-0 space-y-5">
    <RuntimePanel title="اجراهای فعال بر اساس فرایند و انتشار">
      <p className="text-xs leading-6 text-muted-foreground">این گروه‌ها شامل اجراهای منقضی‌نشده، غیرنهایی و تعلیق‌نشدهٔ فروشگاه جاری هستند. تعدادها با فهرست همهٔ وضعیت‌های اجرا یکسان نیستند.</p>
      {!Array.isArray(groups) ? <RuntimeEmpty>گروه‌های فعال در دسترس نیست.</RuntimeEmpty>
        : !groups.length ? <RuntimeEmpty>اجرای فعالی در این گروه‌بندی وجود ندارد.</RuntimeEmpty>
          : <ul className="space-y-3" aria-label="گروه‌های اجرای فعال">
            {groups.slice(0, 100).map(group => {
              const safe = uuid.test(group.workflow_id) && uuid.test(group.publication_id);
              const params = new URLSearchParams({ tab: "runs", workflow_id: group.workflow_id, publication_id: group.publication_id });
              return <li key={`${group.workflow_id}-${group.publication_id}-${group.revision}`} className="min-w-0 space-y-3 rounded-lg border p-3">
                <dl className="grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
                  <div className="min-w-0"><dt className="text-muted-foreground">فرایند</dt><dd className="mt-1"><RuntimeId>{group.workflow_id}</RuntimeId></dd></div>
                  <div className="min-w-0"><dt className="text-muted-foreground">انتشار</dt><dd className="mt-1"><RuntimeId>{group.publication_id}</RuntimeId></dd></div>
                  <div><dt className="text-muted-foreground">نسخه</dt><dd className="mt-1">{count(group.revision)}</dd></div>
                  <div><dt className="text-muted-foreground">تعداد اجرای فعال</dt><dd className="mt-1">{count(group.active_runs)}</dd></div>
                </dl>
                {safe && <div className="flex flex-wrap gap-4 text-xs">
                  <Link className="text-primary underline focus-visible:outline-2 focus-visible:outline-ring" href={`/studio/runtime?${params}`}>اجراهای این فرایند و انتشار</Link>
                  <Link className="text-primary underline focus-visible:outline-2 focus-visible:outline-ring" href={`/studio/runtime?tab=publications&workflow_id=${group.workflow_id}`}>انتشارهای این فرایند</Link>
                </div>}
              </li>;
            })}
          </ul>}
      {(overview.active_groups_has_more || (groups?.length ?? 0) > 100) && <p className="text-xs leading-6 text-muted-foreground">فقط ۱۰۰ گروه اول نمایش داده می‌شوند؛ گروه‌های بیشتری وجود دارند. برای بررسی هر فرایند، از فیلترهای بخش اجراها استفاده کنید.</p>}
    </RuntimePanel>
    <RuntimePanel title="آمار عملیاتی فروشگاه">
      {!metrics ? <RuntimeEmpty>آمار عملیاتی در دسترس نیست.</RuntimeEmpty>
        : overview.metrics_scope?.window !== "all_retained_history" ? <RuntimeEmpty>دامنهٔ آمار در دسترس نیست.</RuntimeEmpty>
          : <>
            <p className="text-xs leading-6 text-muted-foreground">دامنه: تمام تاریخچهٔ نگهداری‌شدهٔ فروشگاه جاری؛ این آمار محدود به امروز نیست. تعداد اجراهای تکمیل‌شده، لغوشده و ناموفق بر اساس وضعیت فعلی آن‌هاست.</p>
            <dl className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-3">
              {countLabels.map(([key, label]) => <div key={key} className="space-y-1"><dt className="text-xs text-muted-foreground">{label}</dt><dd>{count(metrics[key])}</dd></div>)}
              <div className="space-y-1"><dt className="text-xs text-muted-foreground">میانگین مدت اجرای تکمیل‌شده</dt><dd>{duration === null ? "نمونهٔ تکمیل‌شده‌ای وجود ندارد" : typeof duration === "number" && Number.isFinite(duration) && duration >= 0 ? `${duration.toLocaleString("fa-IR", { maximumFractionDigits: 2 })} ثانیه` : "در دسترس نیست"}</dd></div>
            </dl>
            <p className="text-xs leading-6 text-muted-foreground">مدت اجرا از زمان ایجاد تا آخرین به‌روزرسانی اجرای تکمیل‌شده محاسبه می‌شود. تلاش‌های مجدد ارسال، تعداد تلاش‌های فیزیکی پس از تلاش اول هستند.</p>
            <h3 className="text-sm font-semibold">خطاهای تحویل به تفکیک پیام‌رسان</h3>
            <p className="text-xs leading-6 text-muted-foreground">تعداد ارسال‌های متمایزی که رسید تلاش فیزیکی ردشده یا نامعلوم داشته‌اند؛ حتی اگر تلاش بعدی موفق شده باشد. پیام ارسال‌نشده در این شمارش نیست.</p>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              {([ ["telegram", "تلگرام"], ["bale", "بله"] ] as const).map(([platform, label]) => <div key={platform} className="flex flex-wrap justify-between gap-3 rounded-lg border p-3"><dt>{label}</dt><dd>{metrics.delivery_failures_by_platform ? count(metrics.delivery_failures_by_platform[platform] ?? 0) : "در دسترس نیست"}</dd></div>)}
            </dl>
          </>}
    </RuntimePanel>
  </div>;
}
