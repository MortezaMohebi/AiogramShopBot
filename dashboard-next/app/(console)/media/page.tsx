import Link from "next/link";
import { notFound } from "next/navigation";
import { deleteMedia, editMedia, moderateMedia } from "@/app/(console)/media/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { MediaThumbnail } from "@/components/blocks/media-thumbnail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Paginated } from "@/lib/types";
import { uploadErrorMessage } from "@/lib/upload-errors";

type Media = {
  id: number; product_id: number; product_name: string; kind: string;
  filename: string; size_bytes: number; is_published: boolean;
  position: number; caption: string | null; mime_type: string;
};
type ProductOption = { id: number; name: string; sku: string };
type Params = Promise<{page?: string; saved?: string; error?: string}>;
const sizes = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });

/** Native upload and moderation, all originals stored by the Python backend. */
export default async function MediaPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const params = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  const [result, products] = await Promise.all([
    adminFetch<Paginated<Media>>(`/media?page=${page}`),
    adminFetch<ProductOption[]>("/media/products"),
  ]);
  const lastPage = Math.max(1, Math.ceil(result.total / result.page_size));
  return (
    <div className="space-y-6">
      <PageHeading title="رسانه‌های فروشگاه" description="فایل‌های جدید تا زمان تأیید انتشار به مشتری نمایش داده نمی‌شوند." />
      {params.saved ? <p role="status" className="rounded-lg bg-accent px-4 py-3 text-sm">تغییرات رسانه ثبت شد.</p> : null}
      {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{uploadErrorMessage(params.error, "ثبت انجام نشد. نوع فایل، حجم، شناسهٔ محصول یا وضعیت انتشار را بررسی کنید.")}</p> : null}
      <Card>
        <CardHeader><CardTitle>بارگذاری فایل جدید</CardTitle></CardHeader>
        <CardContent>
          <form action="/api/admin/upload?target=product" method="post" encType="multipart/form-data" className="grid gap-4 lg:grid-cols-2">
            <label className="space-y-2 text-sm">شناسه محصول
              <Input name="product_id" type="number" min={1} required list="product-options" placeholder="شماره محصول" />
              <datalist id="product-options">
                {products.map((item) => <option key={item.id} value={item.id} label={`${item.sku} — ${item.name}`} />)}
              </datalist>
              <span className="block text-xs text-muted-foreground">از <Link href="/products" className="underline">فهرست محصولات</Link> هم می‌توانید شناسه را پیدا کنید.</span>
            </label>
            <label className="space-y-2 text-sm">فایل
              <Input name="file" type="file" accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,video/mp4,audio/mpeg,audio/ogg" required />
              <span className="block text-xs text-muted-foreground">تصویر معمولی: حداکثر ۱۰ MB؛ ویدیو، صدا و سایر فایل‌ها: حداکثر ۵۰ MB</span>
            </label>
            <label className="space-y-2 text-sm">توضیح (اختیاری)
              <Input name="caption" maxLength={2000} />
            </label>
            <label className="space-y-2 text-sm">ترتیب نمایش
              <Input name="position" type="number" defaultValue={0} min={0} max={1000000} required />
            </label>
            <div className="lg:col-span-2">
              <p className="mb-3 text-xs text-muted-foreground">هیچ فایل تازه‌ای خودکار منتشر نمی‌شود؛ پس از مشاهدهٔ پیش‌نمایش آن را تأیید کنید.</p>
              <Button type="submit">بارگذاری فایل</Button>
            </div>
          </form>
        </CardContent>
      </Card>
      <div className="space-y-4">
        {result.items.map((item) => (
          <Card key={item.id}>
            <CardContent className="grid gap-4 py-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
              <div className="space-y-2">
                <MediaThumbnail mediaId={item.id} mimeType={item.mime_type} alt={item.caption || item.product_name} />
                <div className="flex flex-wrap items-center gap-2">
                  <strong>{item.product_name}</strong>
                  <Badge tone={item.is_published ? "success" : "warning"}>{item.is_published ? "منتشرشده" : "در انتظار تأیید"}</Badge>
                </div>
                <p className="break-all text-xs" dir="ltr">{item.filename}</p>
                <p className="text-xs text-muted-foreground">#{item.id} · {item.kind} · {sizes.format(item.size_bytes / 1_000_000)} MB</p>
                <a href={`/api/admin/preview/product/${item.id}`} target="_blank" rel="noopener noreferrer" className="inline-flex text-sm font-medium text-primary underline underline-offset-4">پیش‌نمایش فایل</a>
              </div>
              <div className="space-y-3">
                <form action={editMedia} className="grid grid-cols-[minmax(0,1fr)_6rem_auto] items-end gap-2">
                  <input type="hidden" name="id" value={item.id} />
                  <label className="space-y-1 text-xs">توضیح
                    <Input name="caption" maxLength={2000} defaultValue={item.caption ?? ""} />
                  </label>
                  <label className="space-y-1 text-xs">ترتیب
                    <Input name="position" type="number" min={0} max={1000000} required defaultValue={item.position} />
                  </label>
                  <Button variant="outline" type="submit" size="sm">ذخیره</Button>
                </form>
                <div className="flex flex-wrap items-center gap-3">
                  <form action={moderateMedia}>
                    <input type="hidden" name="id" value={item.id} />
                    <input type="hidden" name="publish" value={String(!item.is_published)} />
                    <Button type="submit" size="sm" variant={item.is_published ? "secondary" : "default"}>
                      {item.is_published ? "لغو انتشار" : "تأیید و انتشار"}
                    </Button>
                  </form>
                  {!item.is_published ? (
                    <form action={deleteMedia} className="flex flex-wrap items-center gap-2">
                      <input type="hidden" name="id" value={item.id} />
                      <Input aria-label="عبارت تأیید حذف" name="confirmation" required placeholder="DELETE_DRAFT_MEDIA" dir="ltr" className="w-48 text-xs" />
                      <Button size="sm" variant="destructive" type="submit">حذف فایل</Button>
                    </form>
                  ) : null}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
        {!result.items.length ? <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">هنوز رسانه‌ای ذخیره نشده است.</CardContent></Card> : null}
      </div>
      <nav aria-label="صفحه‌بندی رسانه" className="flex flex-wrap items-center justify-between gap-4 text-sm">
        {page <= 1 ? <Button variant="outline" size="sm" disabled>صفحه قبل</Button> : <Button asChild variant="outline" size="sm"><Link href={`/media?page=${page - 1}`}>صفحه قبل</Link></Button>}
        <span>صفحه {page} از {lastPage} · {result.total} فایل</span>
        {page >= lastPage ? <Button variant="outline" size="sm" disabled>صفحه بعد</Button> : <Button asChild variant="outline" size="sm"><Link href={`/media?page=${page + 1}`}>صفحه بعد</Link></Button>}
      </nav>
    </div>
  );
}
