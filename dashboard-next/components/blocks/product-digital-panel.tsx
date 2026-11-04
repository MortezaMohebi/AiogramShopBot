"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  FileKey2, FileUp, FileWarning, LoaderCircle, ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import type { DigitalAssetSnapshot } from "@/lib/digital-delivery";
import {
  activateLicenseMode, importLicenseCodes,
} from "@/app/(console)/digital-products/actions";

interface Props {
  productId: number;
  asset: DigitalAssetSnapshot;
  saved?: string;
  error?: string;
}

const ERRORS: Record<string, string> = {
  validation: "فایل یا کدهای واردشده معتبر نیستند.",
  digital_asset_not_ready: "فایل قابل استفاده نیست یا سفارش باز مانع تغییر Asset شده است.",
  digital_asset_change_blocked: "ابتدا سفارش‌های پرداخت‌نشدهٔ این محصول را تعیین تکلیف کنید.",
  digital_license_import_denied: "کدهای لایسنس معتبر یا منحصربه‌فرد نیستند.",
  store_switch_required: "ابتدا Store مالک محصول را جاری کنید.",
};

const LIMIT = 50_000_000;

/** Only exposes safe metadata; paid bytes and license keys are never public. */
export function ProductDigitalPanel({
  productId, asset, saved, error,
}: Props) {
  const router = useRouter();
  const uploadRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function uploadPrivateFile() {
    const file = uploadRef.current?.files?.[0];
    if (!file || busy) return;
    if (file.size <= 0 || file.size > LIMIT) {
      setNotice("حجم فایل باید بین ۱ بایت و ۵۰ مگابایت باشد.");
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const challenge = await requestBrowserChallenge();
      const payload = new FormData();
      payload.set("file", file);
      const response = await fetch(
        `/api/admin/digital-products/${productId}/file`,
        {
          method: "POST", credentials: "same-origin",
          cache: "no-store", redirect: "error",
          headers: {
            Accept: "application/json",
            "X-Shop-Login-Challenge": challenge,
          },
          body: payload,
          signal: AbortSignal.timeout(120_000),
        },
      );
      const result = await response.json() as {
        ok?: boolean; code?: string;
      };
      if (!response.ok || result.ok !== true) {
        setNotice(ERRORS[result.code ?? ""] ??
          "فایل ذخیره نشد؛ وضعیت سفارش‌ها، Store و مجوز را بررسی کنید.");
        return;
      }
      setNotice("نسخهٔ خصوصی فایل ثبت شد؛ فایل قبلی سفارش‌های پرداخت‌شده حفظ شده است.");
      if (uploadRef.current) uploadRef.current.value = "";
      router.refresh();
    } catch {
      setNotice(
        "نتیجهٔ آپلود مشخص نیست؛ قبل از تلاش دوباره وضعیت Asset را بررسی کنید.",
      );
    } finally {
      setBusy(false);
    }
  }

  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <ShieldCheck className="size-5" />
        محتوای تحویلی محصول دیجیتال
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-5">
      <p className="text-sm leading-7 text-muted-foreground">
        تصاویر عمومی محصول با فایل دیجیتال فروخته‌شده متفاوت‌اند.
        محتوای این بخش از Vault خصوصی فقط پس از پرداخت معتبر به همان
        Bot و مشتری ارسال می‌شود. تغییر فایل نباید سفارش‌های قدیمی را
        به نسخهٔ جدید منتقل کند.
      </p>
      <div className="rounded-lg border p-4 text-sm">
        <p className="font-semibold">
          {asset.configured ?
            asset.kind === "file" ? "فایل خصوصی" : "License Pool" :
            "هنوز محتوای تحویلی تعریف نشده است"}
        </p>
        {asset.configured ? <>
          <p className="mt-2 text-muted-foreground">
            نسخه: {asset.version}
            {asset.filename ? ` · نام فایل: ${asset.filename}` : ""}
          </p>
          {asset.kind === "license" ?
            <div className="mt-2 flex flex-wrap gap-3">
              <span>آماده: {asset.codes?.available ?? 0}</span>
              <span>رزروشده: {asset.codes?.reserved ?? 0}</span>
              <span>تحویل‌شده: {asset.codes?.delivered ?? 0}</span>
            </div> : null}
        </> : null}
      </div>
      {saved ? <p role="status" className="rounded-md border p-3 text-sm">
        تنظیمات دیجیتال ذخیره شدند.
      </p> : null}
      {error ? <p role="alert" className="rounded-md border border-destructive p-3 text-sm text-destructive">
        {ERRORS[error] ?? "عملیات انجام نشد؛ نسخه و دسترسی Store را بررسی کنید."}
      </p> : null}
      {notice ? <p role="status" className="rounded-md border p-3 text-sm">
        {notice}
      </p> : null}
      <section className="space-y-3 border-t pt-4">
        <h3 className="flex items-center gap-2 font-semibold">
          <FileUp className="size-4" /> فایل خصوصی
        </h3>
        <label className="block space-y-2 text-sm">
          فایل تحویلی PDF، ZIP، تصویر، صوت یا ویدیو — حداکثر ۵۰ MB
          <Input ref={uploadRef} type="file" disabled={busy}
            accept=".pdf,.zip,.png,.jpg,.jpeg,.webp,.gif,.mp4,.mp3,.ogg" />
        </label>
        <Button type="button" variant="outline" disabled={busy}
          onClick={() => void uploadPrivateFile()}>
          {busy ? <LoaderCircle className="size-4 animate-spin" /> :
            <FileUp className="size-4" />}
          بارگذاری نسخهٔ امن فایل
        </Button>
      </section>
      <section className="space-y-4 border-t pt-4">
        <h3 className="flex items-center gap-2 font-semibold">
          <FileKey2 className="size-4" /> License Pool
        </h3>
        <p className="text-xs leading-7 text-muted-foreground">
          اگر این محصول لایسنس دارد، ابتدا حالت لایسنس را فعال کنید.
          کدها در Backend رمزنگاری و به صورت یک‌بارمصرف به سفارش اختصاص داده
          می‌شوند. کدهای واقعی پس از ثبت در Dashboard نمایش داده نمی‌شوند.
        </p>
        {asset.kind !== "license" ? <form action={activateLicenseMode}
          className="space-y-3 rounded-lg border p-3">
          <input type="hidden" name="product_id" value={productId} />
          <p className="text-xs text-muted-foreground">
            فعال‌کردن License Pool، موجودی قابل فروش را بر اساس تعداد
            کدهای آماده محاسبه می‌کند. برای محافظت از سفارش‌های باز،
            تغییر حالت در زمان وجود سفارش پرداخت‌نشده رد می‌شود.
          </p>
          <SecurityProof />
          <Button type="submit" variant="outline">فعال‌سازی حالت لایسنس</Button>
        </form> : <form action={importLicenseCodes}
          className="space-y-3 rounded-lg border p-3">
          <input type="hidden" name="product_id" value={productId} />
          <label className="block space-y-2 text-sm">
            کدهای جدید؛ هر کد در یک خط (حداکثر ۵۰۰ کد)
            <Textarea name="license_codes" required rows={6}
              autoComplete="off" maxLength={75000}
              placeholder={"LICENSE-001\nLICENSE-002"} />
          </label>
          <SecurityProof />
          <Button type="submit" variant="outline">
            <FileKey2 className="size-4" /> افزودن کدهای رمزنگاری‌شده
          </Button>
        </form>}
      </section>
      <p className="flex items-start gap-2 text-xs leading-6 text-muted-foreground">
        <FileWarning className="size-4 shrink-0" />
        ارسال واقعی به Bot تنها با فعال‌سازی Worker، دریافت رسید معتبر
        پرداخت و کنترل Asset انجام می‌شود. در Timeout ارسال تکرار خودکار نداریم.
      </p>
    </CardContent>
  </Card>;
}

/** Sensitive asset or license mode changes require fresh administrator proof. */
function SecurityProof() {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="block space-y-2 text-sm">
      رمز فعلی مدیر
      <Input name="current_password" type="password"
        autoComplete="current-password" required />
    </label>
    <label className="block space-y-2 text-sm">
      کد شش‌رقمی MFA
      <Input name="second_factor" inputMode="numeric"
        pattern="[0-9]{6}" maxLength={6}
        autoComplete="one-time-code" required />
    </label>
  </div>;
}
