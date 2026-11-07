"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Save, LoaderCircle, TriangleAlert, CheckCircle2 } from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { CategoryMany2One } from "@/components/blocks/category-many2one";
import { ProductBotMany2ManyPanel } from "@/components/blocks/product-bot-many2many-panel";
import type { ProductBotCatalogList } from "@/lib/bot-catalog-acl";
import { FieldEye } from "@/components/blocks/field-eye";
import {
  ProductMediaPanel,
  type ProductFile,
} from "@/components/blocks/product-media-panel";
import { Button } from "@/components/ui/button";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { Category, Product } from "@/lib/types";
import type { UomUnit } from "@/lib/uoms";

type SaveCode =
  | "invalid_product" | "sku_exists" | "uom_locked" | "permission_denied"
  | "session_expired" | "security_check_failed"
  | "service_unavailable" | "invalid_request";

const messages: Record<SaveCode, string> = {
  invalid_product: "اطلاعات محصول معتبر نیست. قیمت، موجودی، نوع کالا و دسته‌بندی را بررسی کنید.",
  sku_exists: "این کد SKU قبلاً ثبت شده است؛ کد دیگری انتخاب کنید یا کادر SKU را خالی بگذارید.",
  uom_locked: "واحد فروش محصول دارای موجودی، سبد فعال یا سابقهٔ سفارش را نمی‌توان تغییر داد؛ ابتدا موجودی را صفر و سوابق را بررسی کنید.",
  permission_denied: "حساب شما اجازهٔ ایجاد یا ویرایش محصول را ندارد.",
  session_expired: "نشست مدیریت پایان یافته است. دوباره وارد شوید.",
  security_check_failed: "بررسی امنیتی ناموفق بود؛ صفحه را تازه‌سازی کنید.",
  service_unavailable: "ارتباط با سرویس اصلی برقرار نشد؛ اطلاعات فرم همچنان حفظ شده‌اند.",
  invalid_request: "اطلاعات ارسالی ناقص یا نامعتبر است.",
};

interface ProductEditorProps {
  product?: Product;
  categories: Category[];
  uoms: UomUnit[];
  media?: ProductFile[];
  botAccess?: ProductBotCatalogList;
  botAccessQuery?: string;
  botAccessSaved?: boolean;
  botAccessError?: boolean;
}

/** Real PostgreSQL-backed product editor with explicit public-field eyes. */
export function ProductEditor({
  product,
  categories,
  uoms,
  media = [],
  botAccess,
  botAccessQuery = "",
  botAccessSaved = false,
  botAccessError = false,
}: ProductEditorProps) {
  const router = useRouter();
  const [kind, setKind] = useState<"physical" | "digital">(
    product?.product_type ?? "physical",
  );
  const [uomId, setUomId] = useState(
    product?.uom_id ?? uoms.find((item) => item.code === "piece")?.id ?? "",
  );
  const [purchaseUnit, setPurchaseUnit] = useState(
    product?.purchase_uom_id ?? "",
  );
  const currentCategory = uoms.find((item) => item.id === uomId)?.category_id;
  const purchaseChoices = uoms.filter((item) =>
    item.active && item.category_id === currentCategory,
  );
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{
    ok: boolean; message: string; requestId?: string;
  } | null>(null);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const value = (name: string) => String(data.get(name) ?? "").trim();
    const payload = {
      ...(product ? { id: product.id } : {}),
      name: value("name"),
      sku: value("sku"),
      external_ref: value("external_ref") || null,
      uom_id: uomId || null,
      purchase_uom_id: purchaseUnit || null,
      description: value("description"),
      category_id: value("category_id") ? Number(value("category_id")) : null,
      price_irr: value("price_irr"),
      price_stars: kind === "digital" && value("price_stars")
        ? Number(value("price_stars")) : null,
      ...(
        product?.digital_delivery_mode === "license"
          ? {}
          : { stock_quantity: Number(value("stock_quantity")) }
      ),
      product_type: kind,
      requires_shipping: kind === "physical" && data.has("requires_shipping"),
      is_published: data.has("is_published"),
      show_description: value("show_description") === "true",
      show_stock: value("show_stock") === "true",
      show_media: value("show_media") === "true",
      show_reviews: value("show_reviews") === "true",
    };

    setSaving(true);
    setNotice(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/admin/products", {
        method: product ? "PATCH" : "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(25_000),
      });
      if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
        throw new Error("پاسخ سرور معتبر نیست؛ وضعیت محصول را بررسی کنید.");
      }
      const result = await response.json() as {
        ok?: boolean; id?: number; code?: SaveCode; requestId?: string;
      };
      if (!response.ok || !result.ok || !Number.isSafeInteger(result.id)) {
        setNotice({
          ok: false,
          message: result.code && Object.hasOwn(messages, result.code)
            ? messages[result.code]
            : "ذخیره محصول انجام نشد؛ وضعیت فعلی را بررسی کنید.",
          requestId: result.requestId,
        });
        return;
      }
      if (!product) {
        // The persisted item now owns private media. Add images in the
        // same product-editing experience, without typing a numeric ID.
        router.push("/products/" + result.id + "/edit?created=1#media");
      } else {
        setNotice({ ok: true, message: "تغییرات محصول ذخیره شد." });
        router.refresh();
      }
    } catch (cause) {
      setNotice({
        ok: false,
        message: cause instanceof Error
          ? "ارتباط در هنگام ذخیره برقرار نشد. پیش از تلاش مجدد، وضعیت محصول را بررسی کنید."
          : "ذخیره انجام نشد.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={save} aria-busy={saving} className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <fieldset disabled={saving} className="contents">
          <Card>
            <CardHeader>
              <CardTitle>اطلاعات اصلی محصول</CardTitle>
              <CardDescription>
                علامت چشم، ارسال فیلدهای اختیاری را برای مشتریان هر دو ربات کنترل می‌کند.
                نام، قیمت و وضعیت ناموجودی ضروری‌اند.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <label htmlFor="product-name" className="text-sm font-medium">نام محصول</label>
                    <FieldEye label="نام محصول" required />
                  </div>
                  <Input id="product-name" name="name" required maxLength={255}
                    defaultValue={product?.name ?? ""} />
                </div>
                <div className="space-y-2">
                  <label htmlFor="product-sku" className="text-sm font-medium">
                    SKU داخلی (اختیاری)
                  </label>
                  <Input id="product-sku" name="sku" dir="ltr" maxLength={64}
                    className="text-start" defaultValue={product?.sku ?? ""}
                    placeholder="در صورت خالی‌بودن خودکار ساخته می‌شود" />
                  <p className="text-xs text-muted-foreground">
                    فقط برای مدیریت و سفارش است؛ در متن مشتری نمایش داده نمی‌شود.
                  </p>
                </div>
              </div>
              <div className="space-y-2">
                <label htmlFor="product-external-ref" className="text-sm font-medium">
                  شناسهٔ خارجی (اختیاری، برای ورود و خروج داده)
                </label>
                <Input id="product-external-ref" name="external_ref"
                  maxLength={80} dir="ltr" defaultValue={product?.external_ref ?? ""}
                  placeholder="supplier-product-001" />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <label htmlFor="product-description" className="text-sm font-medium">
                    توضیحات (اختیاری)
                  </label>
                  <FieldEye name="show_description" label="توضیحات"
                    initial={product?.show_description ?? true} />
                </div>
                <Textarea id="product-description" name="description"
                  maxLength={40000} rows={6} defaultValue={product?.description ?? ""} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">دسته‌بندی (اختیاری)</label>
                <CategoryMany2One categories={categories}
                  initialId={product?.category_id ?? null} canCreate />
              </div>
            </CardContent>
          </Card>

          <div className="space-y-5">
            <Card>
              <CardHeader><CardTitle>قیمت و موجودی</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block space-y-2 text-sm font-medium">
                    واحد فروش (UoM)
                    <select name="uom_id" value={uomId} required
                      onChange={(event) => {
                        setUomId(event.target.value);
                        setPurchaseUnit("");
                      }}
                      className="h-10 w-full rounded-md border border-input bg-background px-3">
                      {uoms.filter((unit) => unit.active).map((unit) =>
                        <option key={unit.id} value={unit.id}>
                          {unit.name} ({unit.symbol})
                        </option>)}
                    </select>
                  </label>
                  <label className="block space-y-2 text-sm font-medium">
                    واحد خرید (اختیاری)
                    <select name="purchase_uom_id" value={purchaseUnit}
                      onChange={(event) => setPurchaseUnit(event.target.value)}
                      className="h-10 w-full rounded-md border border-input bg-background px-3">
                      <option value="">همان واحد فروش</option>
                      {purchaseChoices.map((unit) =>
                        <option key={unit.id} value={unit.id}>
                          {unit.name} ({unit.symbol})
                        </option>)}
                    </select>
                  </label>
                </div>
                <p className="text-xs leading-6 text-muted-foreground">
                  قیمت برای یک واحد فروش است. موجودی و سبد خرید فقط تعداد صحیح می‌پذیرند.
                </p>
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <label htmlFor="product-price" className="text-sm font-medium">
                      قیمت به ریال (عدد صحیح)
                    </label>
                    <FieldEye label="قیمت محصول" required />
                  </div>
                  <Input id="product-price" type="number" dir="ltr" name="price_irr"
                    min={0} step={1} max={9999999999999999} required
                    defaultValue={product?.price_irr ?? "0"} className="text-start" />
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <label htmlFor="product-stock" className="text-sm font-medium">تعداد موجودی</label>
                    <FieldEye name="show_stock" label="تعداد موجودی"
                      initial={product?.show_stock ?? true} />
                  </div>
                  <Input id="product-stock" type="number" dir="ltr" name="stock_quantity"
                    min={0} max={100000000}
                    disabled={product?.digital_delivery_mode === "license"}
                    required={product?.digital_delivery_mode !== "license"}
                    defaultValue={product?.stock_quantity ?? 0} className="text-start" />
                  <p className="text-xs text-muted-foreground">
                    {product?.digital_delivery_mode === "license"
                      ? "موجودی این محصول از لایسنس‌های استفاده‌نشده محاسبه می‌شود."
                      : "با دکمهٔ چشم، نمایش تعداد موجودی به مشتری را در تلگرام و بله تنظیم کنید. پیام «ناموجود» همیشه نمایش داده می‌شود."}
                  </p>
                </div>
                <label className="block space-y-2 text-sm font-medium">
                  نوع کالا
                  <select className="h-10 w-full rounded-md border border-input bg-background px-3"
                    name="product_type" value={kind}
                    onChange={(event) => setKind(event.target.value as "physical" | "digital")}>
                    <option value="physical">فیزیکی</option>
                    <option value="digital">دیجیتال</option>
                  </select>
                </label>
                {kind === "digital" ? (
                  <label className="block space-y-2 text-sm font-medium">
                    قیمت Telegram Stars
                    <Input type="number" dir="ltr" name="price_stars"
                      min={1} step={1} defaultValue={product?.price_stars ?? ""}
                      className="text-start" />
                  </label>
                ) : (
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" name="requires_shipping"
                      defaultChecked={product?.requires_shipping ?? true}
                      className="size-4 accent-primary" />
                    نیازمند آدرس و ارسال
                  </label>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>نمایش و انتشار</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <p className="text-xs leading-6 text-muted-foreground">
                  فیلدهای پنهان‌شده به مشتری نمایش داده نمی‌شوند.
                </p>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm">تصاویر و فایل‌های محصول</span>
                  <FieldEye name="show_media" label="رسانه‌ها"
                    initial={product?.show_media ?? true} />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm">رضایت مشتریان</span>
                  <FieldEye name="show_reviews" label="رضایت مشتریان"
                    initial={product?.show_reviews ?? true} />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" name="is_published"
                    defaultChecked={product?.is_published ?? false}
                    className="size-4 accent-primary" />
                  محصول برای مشتریان منتشر شود
                </label>
                <Button type="submit" className="w-full" disabled={saving}>
                  {saving
                    ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                    : <Save className="size-4" aria-hidden="true" />}
                  {saving ? "در حال ذخیره..." : "ذخیره محصول"}
                </Button>
              </CardContent>
            </Card>
          </div>
        </fieldset>
      </form>

      {notice ? (
        <div role={notice.ok ? "status" : "alert"}
          className={notice.ok
            ? "flex gap-2 rounded-lg bg-accent p-3 text-sm"
            : "flex gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive"}>
          {notice.ok
            ? <CheckCircle2 aria-hidden="true" className="size-4" />
            : <TriangleAlert aria-hidden="true" className="size-4" />}
          <div>
            <p>{notice.message}</p>
            {notice.requestId ? <details className="mt-2 text-xs">
              <summary className="cursor-pointer">اطلاعات پیگیری</summary>
              <p dir="ltr" className="mt-1 break-all">{notice.requestId}</p>
            </details> : null}
          </div>
        </div>
      ) : null}

      {product && botAccess ? (
        <ProductBotMany2ManyPanel
          data={botAccess} query={botAccessQuery}
          saved={botAccessSaved} error={botAccessError}
        />
      ) : null}

      {product ? (
        <section id="media">
          <ProductMediaPanel productId={product.id} initial={media} />
        </section>
      ) : (
        <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
          پس از ذخیرهٔ محصول، همین صفحه بخش بارگذاری تصاویر، ویدیو،
          صدا و فایل‌های آن محصول را باز می‌کند.
        </p>
      )}
    </div>
  );
}
