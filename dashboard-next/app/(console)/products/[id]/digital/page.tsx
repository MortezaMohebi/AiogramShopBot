import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { DigitalFileUploader } from "@/components/blocks/digital-file-uploader";
import { saveDigitalLicenses } from "./actions";

type Params = Promise<{ id: string }>;
type Query = Promise<{ saved?: string; error?: string }>;

interface DigitalSnapshot {
  product_id: number;
  store_id: string;
  product_type: "physical" | "digital";
  mode: "none" | "file" | "license";
  stock_quantity: number;
  available_licenses: number;
  claimed_or_delivered_licenses: number;
  ready: boolean;
  file: {
    id: string;
    original_filename: string;
    size_bytes: number;
    sha256: string;
    mime_type: string;
  } | null;
}

/** Paid private content is NOT the same as ProductMedia catalog attachments. */
export default async function DigitalProductPage({
  params, searchParams,
}: { params: Params; searchParams: Query }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const { id } = await params;
  if (!/^[1-9][0-9]{0,15}$/.test(id)) notFound();
  const [snapshot, query] = await Promise.all([
    adminFetch<DigitalSnapshot>(`/products/${id}/digital-assets`),
    searchParams,
  ]);
  return <div className="space-y-5">
    <Button asChild variant="outline" size="sm">
      <Link href={`/products/${id}/edit`}>بازگشت به ویرایش محصول</Link>
    </Button>
    <PageHeading title={`تحویل دیجیتال محصول #${id}`}
      description="فایل یا لایسنس یک‌بارمصرف فقط پس از تأیید پرداخت به مشتری تحویل می‌شود." />
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      لایسنس‌ها به موجودی اضافه شدند. کدهای ثبت‌شده دوباره نمایش داده نمی‌شوند.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      ثبت انجام نشد. کدها، دسترسی فروشگاه و تأیید مجدد هویت را بررسی کنید.
    </p> : null}
    {snapshot.product_type !== "digital" ? <Card>
      <CardContent className="p-5 text-sm">
        این کالا فیزیکی است. برای فعال‌سازی تحویل خصوصی، نوع محصول را ابتدا دیجیتال کنید.
      </CardContent>
    </Card> : <>
      <Card>
        <CardHeader><CardTitle>وضعیت تأمین دیجیتال</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>حالت: <strong>{snapshot.mode === "file" ? "فایل خصوصی" :
            snapshot.mode === "license" ? "لایسنس یک‌بارمصرف" : "تعریف نشده"}</strong></p>
          <p>آمادهٔ فروش: <strong>{snapshot.ready ? "بله" : "خیر"}</strong></p>
          <p>موجودی محصول: {snapshot.stock_quantity}</p>
          <p>لایسنس قابل تخصیص: {snapshot.available_licenses}</p>
          <p>لایسنس رزروشده/تحویل‌شده: {snapshot.claimed_or_delivered_licenses}</p>
          {snapshot.file ? <p className="break-words">
            فایل فعال: {snapshot.file.original_filename} — {snapshot.file.size_bytes} بایت
          </p> : null}
          <p className="text-muted-foreground">
            بعد از انتخاب روش تأمین، تغییر خودکار فایل به لایسنس یا برعکس
            غیرفعال است تا سفارش‌های پرداخت‌شده آسیب نبینند.
          </p>
        </CardContent>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        {snapshot.mode !== "license" ? <Card>
          <CardHeader><CardTitle>فایل خصوصی خریداری‌شده</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <DigitalFileUploader productId={snapshot.product_id} />
            <p className="text-xs leading-6 text-muted-foreground">
              جایگزینی فایل، نسخهٔ مربوط به سفارش‌های قبلی را حذف نمی‌کند.
            </p>
          </CardContent>
        </Card> : null}
        {snapshot.mode !== "file" ? <Card>
          <CardHeader><CardTitle>ثبت لایسنس‌های یک‌بارمصرف</CardTitle></CardHeader>
          <CardContent>
            <form action={saveDigitalLicenses} className="space-y-3">
              <input type="hidden" name="product_id" value={id} />
              <label className="block space-y-2 text-sm">
                کدهای جدید (هر سطر یک کد، حداکثر ۱۰۰)
                <Textarea name="license_codes" required rows={8} maxLength={12900}
                  autoComplete="off" placeholder="CODE-ONE&#10;CODE-TWO" />
              </label>
              <p className="text-xs leading-6 text-muted-foreground">
                موجودی از کدهای استفاده‌نشده تعیین می‌شود؛
                موجودی را از فرم عمومی محصول ویرایش نکنید.
              </p>
              <label className="block space-y-1 text-sm">
                رمز فعلی مدیر
                <Input name="current_password" type="password"
                  required autoComplete="current-password" />
              </label>
              <label className="block space-y-1 text-sm">
                کد احراز هویت دومرحله‌ای
                <Input name="second_factor" inputMode="numeric"
                  pattern="[0-9]{6}" maxLength={6} required
                  autoComplete="one-time-code" />
              </label>
              <Button type="submit">افزودن لایسنس‌ها</Button>
            </form>
          </CardContent>
        </Card> : null}
      </div>
    </>}
  </div>;
}
