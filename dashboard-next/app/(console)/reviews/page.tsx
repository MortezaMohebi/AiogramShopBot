import Link from "next/link";
import { notFound } from "next/navigation";
import { deleteReview, editReview, moderateReview } from "@/app/(console)/reviews/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Paginated } from "@/lib/types";
import { uploadErrorMessage } from "@/lib/upload-errors";

type Review = {
  id: number; product_id: number; product_name: string;
  text: string | null; has_file: boolean; is_approved: boolean;
  position: number; media_kind: string | null;
};
type ProductOption = { id: number; name: string; sku: string };
type Params = Promise<{ page?: string; saved?: string; error?: string }>;

/** Customer testimonials remain private until a content editor approves them. */
export default async function ReviewsPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const params = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  const [reviews, products] = await Promise.all([
    adminFetch<Paginated<Review>>(`/testimonials?page=${page}`),
    adminFetch<ProductOption[]>("/media/products"),
  ]);
  const lastPage = Math.max(1, Math.ceil(reviews.total / reviews.page_size));
  return (
    <div className="space-y-6">
      <PageHeading title="رضایت مشتریان" description="ثبت متن یا فایل، بررسی و تأیید مستقل برای نمایش در فروشگاه هر دو پیام‌رسان." />
      {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">تغییرات رضایت مشتری ثبت شد.</p> : null}
      {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{uploadErrorMessage(params.error, "عملیات انجام نشد؛ محدودیت فایل، متن یا مجوز انتشار را بررسی کنید.")}</p> : null}
      <Card>
        <CardHeader><CardTitle>افزودن رضایت جدید</CardTitle></CardHeader>
        <CardContent>
          <form action="/api/admin/upload?target=testimonial" method="post" encType="multipart/form-data" className="grid gap-4 lg:grid-cols-2">
            <label className="space-y-2 text-sm">شناسه محصول
              <Input name="product_id" type="number" min={1} list="review-products" required />
              <datalist id="review-products">
                {products.map((item) => <option key={item.id} value={item.id} label={`${item.sku} — ${item.name}`} />)}
              </datalist>
            </label>
            <label className="space-y-2 text-sm">فایل اختیاری (حداکثر ۱۰ MB عکس، ۵۰ MB سایر موارد)
              <Input name="file" type="file" accept="image/*,video/mp4,audio/mpeg,audio/ogg,application/pdf" />
            </label>
            <label className="space-y-2 text-sm lg:col-span-2">متن رضایت (اگر فایل ندارید، الزامی است)
              <Textarea name="caption" maxLength={2000} rows={3} />
            </label>
            <label className="space-y-2 text-sm">ترتیب
              <Input name="position" type="number" min={0} max={1000000} defaultValue={0} />
            </label>
            <div className="flex items-end">
              <Button type="submit">ثبت رضایتِ تأییدنشده</Button>
            </div>
          </form>
        </CardContent>
      </Card>
      <div className="space-y-4">
        {reviews.items.map((review) => (
          <Card key={review.id}>
            <CardContent className="space-y-4 py-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold">{review.product_name} <span className="text-xs font-normal text-muted-foreground">#{review.id}</span></div>
                <Badge tone={review.is_approved ? "success" : "warning"}>{review.is_approved ? "تأییدشده" : "در انتظار بررسی"}</Badge>
              </div>
              {review.has_file ? <a href={`/api/admin/preview/testimonial/${review.id}`} target="_blank" rel="noopener noreferrer" className="text-sm text-primary underline">مشاهده فایل {review.media_kind ?? ""}</a> : null}
              <form action={editReview} className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_7rem_auto] lg:items-end">
                <input type="hidden" name="id" value={review.id} />
                <label className="space-y-2 text-xs">متن
                  <Textarea name="text" rows={2} maxLength={2000} defaultValue={review.text ?? ""} />
                </label>
                <label className="space-y-2 text-xs">ترتیب
                  <Input type="number" min={0} max={1000000} name="position" defaultValue={review.position} />
                </label>
                <Button type="submit" variant="outline" size="sm">ذخیره</Button>
              </form>
              <div className="flex flex-wrap items-center gap-3">
                <form action={moderateReview}>
                  <input type="hidden" name="id" value={review.id} />
                  <input type="hidden" name="approve" value={String(!review.is_approved)} />
                  <Button size="sm" type="submit" variant={review.is_approved ? "secondary" : "default"}>
                    {review.is_approved ? "لغو تأیید" : "تأیید برای نمایش"}
                  </Button>
                </form>
                {!review.is_approved ? <form action={deleteReview} className="flex items-center gap-2">
                  <input type="hidden" name="id" value={review.id} />
                  <Input name="confirmation" required dir="ltr" placeholder="DELETE_DRAFT_REVIEW" aria-label="عبارت تأیید حذف" className="w-52 text-xs" />
                  <Button type="submit" variant="destructive" size="sm">حذف</Button>
                </form> : null}
              </div>
            </CardContent>
          </Card>
        ))}
        {!reviews.items.length ? <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">رضایتی ثبت نشده است.</CardContent></Card> : null}
      </div>
      <nav aria-label="صفحه‌بندی رضایت مشتری" className="flex items-center justify-between text-sm">
        <Button asChild variant="outline" size="sm"><Link href={`/reviews?page=${Math.max(1, page - 1)}`}>صفحه قبل</Link></Button>
        <span>{page} / {lastPage} · {reviews.total} مورد</span>
        <Button asChild variant="outline" size="sm"><Link href={`/reviews?page=${Math.min(lastPage, page + 1)}`}>صفحه بعد</Link></Button>
      </nav>
    </div>
  );
}
