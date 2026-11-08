import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
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
        title="فرایندها"
        action={
          catalog.can_write ? (
            <Button asChild>
              <Link href="/studio/workflows/new">فرایند جدید</Link>
            </Button>
          ) : undefined
        }
      />
      <div className="mb-6 rounded-xl border border-primary/20 bg-primary/5 px-5 py-4 text-sm leading-7">
        پیش‌نویس روی ربات اجرا نمی‌شود. برای اجرا، نسخه را منتشر کنید و ورودی، ربات و مجوز اجرا را مشخص کنید.{" "}
        <Link href="/studio/runtime" className="text-primary underline">بررسی وضعیت اجرا</Link>
      </div>
      <form
        action="/studio/workflows"
        className="mb-5 flex flex-wrap items-end gap-3"
      >
        <label className="min-w-0 flex-1 basis-48 space-y-2 text-xs font-semibold">
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
            className="h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring"
            defaultValue={status}
          >
            <option value="draft">پیش‌نویس</option>
            <option value="archived">بایگانی</option>
            <option value="deleted">حذف‌شده</option>
            <option value="all">همه</option>
          </select>
        </label>
        <Button type="submit" variant="outline">
          اعمال فیلتر
        </Button>
      </form>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.items.map((item) => (
          <RecordClickArea
            as="article"
            key={item.id}
            className="min-w-0 space-y-3 rounded-xl border bg-card p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <h2 className="break-words font-semibold">
                <RecordLink href={`/studio/workflows/${item.id}`}>{item.name}</RecordLink>
              </h2>
              <span className="shrink-0 rounded-full bg-muted px-2 py-1 text-[10px]">
                {item.status === "draft"
                  ? "پیش‌نویس"
                  : item.status === "archived"
                    ? "بایگانی"
                    : "حذف‌شده"}
              </span>
            </div>
            {item.description && (
              <p className="line-clamp-2 text-xs leading-6 text-muted-foreground">
                {item.description}
              </p>
            )}
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
          </RecordClickArea>
        ))}
      </div>
      {!data.items.length && (
        <div className="rounded-xl border border-dashed bg-card px-6 py-16 text-center">
          <h2 className="font-semibold">
            {q ? "فرایندی با این جستجو پیدا نشد" : "فرایندی در این فهرست نیست"}
          </h2>
          {q ? (
            <Link href={`/studio/workflows?status=${status}`} className="mt-3 inline-block text-sm text-primary underline">
              پاک‌کردن جستجو
            </Link>
          ) : catalog.can_write && status === "draft" ? (
            <Link href="/studio/workflows/new" className="mt-3 inline-block text-sm text-primary underline">
              ایجاد فرایند
            </Link>
          ) : null}
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>
          {data.total.toLocaleString("fa-IR")} فرایند · صفحهٔ {page.toLocaleString("fa-IR")}
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
