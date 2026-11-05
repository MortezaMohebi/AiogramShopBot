import Link from "next/link";
import { StudioHomeNav } from "@/components/workflows/studio-home-nav";
import { adminFetch } from "@/lib/bridge";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Catalog, WorkflowList } from "@/lib/workflows/types";
export default async function WorkflowsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;
  const q = typeof search.q === "string" ? search.q.slice(0, 100) : "";
  const status =
    typeof search.status === "string" &&
    ["draft", "archived", "deleted", "all"].includes(search.status)
      ? search.status
      : "draft";
  const page =
    typeof search.page === "string" && /^[1-9][0-9]{0,7}$/.test(search.page)
      ? Number(search.page)
      : 1;
  const [data, catalog] = await Promise.all([
    adminFetch<WorkflowList>(
      `/workflows?q=${encodeURIComponent(q)}&status=${status}&page=${page}`,
    ),
    adminFetch<Catalog>("/workflows/catalog"),
  ]);
  const href = (p: number) =>
    `/studio/workflows?q=${encodeURIComponent(q)}&status=${status}&page=${p}`;
  return (
    <div className="min-w-0">
      <StudioHomeNav current="workflows" />
      <PageHeading
        title="Bot Experience Studio"
        description="طراحی فرایندهای مکالمه برای Telegram و Bale؛ تعریف قابل‌حمل، تاریخچهٔ نسخه و شبیه‌سازی در فروشگاه شما."
        action={
          catalog.can_write ? (
            <Button asChild>
              <Link href="/studio/workflows/new">فرایند جدید</Link>
            </Button>
          ) : undefined
        }
      />
      <div className="mb-6 rounded-xl border border-primary/20 bg-primary/5 px-5 py-4 text-sm leading-7">
        فرایندها در این مرحله پیش‌نویس هستند. Preview با دادهٔ نمونه اجرا
        می‌شود؛ فعال‌سازی Runtime پس از بررسی‌های مرحلهٔ بعد فراهم خواهد شد.
      </div>
      <form
        action="/studio/workflows"
        className="mb-5 flex flex-wrap items-end gap-3"
      >
        <label className="min-w-0 flex-1 space-y-2 text-xs font-semibold">
          جستجوی فرایند
          <Input
            name="q"
            defaultValue={q}
            maxLength={100}
            placeholder="نام فرایند"
          />
        </label>
        <label className="space-y-2 text-xs font-semibold">
          وضعیت
          <select
            name="status"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            defaultValue={status}
          >
            <option value="draft">پیش‌نویس</option>
            <option value="archived">بایگانی</option>
            <option value="deleted">حذف‌شده</option>
            <option value="all">همه</option>
          </select>
        </label>
        <Button type="submit" variant="outline">
          اعمال
        </Button>
      </form>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.items.map((item) => (
          <article
            key={item.id}
            className="min-w-0 space-y-3 rounded-xl border bg-card p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <h2 className="break-words font-semibold">
                <Link
                  href={`/studio/workflows/${item.id}`}
                  className="text-primary hover:underline"
                >
                  {item.name}
                </Link>
              </h2>
              <span className="shrink-0 rounded-full bg-muted px-2 py-1 text-[10px]">
                {item.status === "draft"
                  ? "پیش‌نویس"
                  : item.status === "archived"
                    ? "بایگانی"
                    : "حذف‌شده"}
              </span>
            </div>
            <p className="line-clamp-2 min-h-12 text-xs leading-6 text-muted-foreground">
              {item.description || "بدون توضیحات"}
            </p>
            <p dir="ltr" className="break-all text-xs text-muted-foreground">
              {item.key} · r{item.revision}
            </p>
            <p className="text-xs text-muted-foreground">
              {new Date(item.updated_at).toLocaleString("fa-IR", {
                timeZone: "Asia/Tehran",
              })}
            </p>
            <div className="flex flex-wrap gap-4 border-t pt-3 text-xs">
              <Link
                href={`/studio/workflows/${item.id}/preview`}
                className="text-primary"
              >
                شبیه‌ساز
              </Link>
              <Link
                href={`/studio/workflows/${item.id}/versions`}
                className="text-primary"
              >
                نسخه‌ها
              </Link>
              <Link
                href={`/studio/workflows/${item.id}/settings`}
                className="text-primary"
              >
                تنظیمات
              </Link>
            </div>
          </article>
        ))}
      </div>
      {!data.items.length && (
        <div className="rounded-xl border border-dashed bg-card px-6 py-16 text-center">
          <h2 className="font-semibold">فرایندی در این فهرست نیست</h2>
          <p className="mx-auto mt-3 max-w-md text-sm leading-7 text-muted-foreground">
            از یک فرایند خالی یا نمونهٔ مرجوعی شروع کنید؛ بعد گره‌ها و مسیرهای
            گفت‌وگو را در ویرایشگر بچینید.
          </p>
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>
          {data.total} فرایند · صفحهٔ {page}
        </span>
        <div className="flex gap-4">
          {page > 1 && (
            <Link href={href(page - 1)} className="text-primary">
              قبلی
            </Link>
          )}
          {data.has_more && (
            <Link href={href(page + 1)} className="text-primary">
              بعدی
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
