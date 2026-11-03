"use client";

import { useState } from "react";
import { Save } from "lucide-react";
import { saveProduct } from "@/app/(console)/products/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { CategoryPicker } from "@/components/blocks/category-picker";
import { ProductMediaManager, type ProductAsset } from "@/components/blocks/product-media-manager";
import { Textarea } from "@/components/ui/textarea";
import type { Category, Product } from "@/lib/types";

/** Product form block backed by Python validation and existing order snapshots. */
export function ProductEditor({
  product,
  categories,
  media = [],
}: {
  product?: Product;
  categories: Category[];
  media?: ProductAsset[];
}) {
  const [kind, setKind] = useState<"physical" | "digital">(product?.product_type ?? "physical");
  return (
    <div>
    <form action={saveProduct} className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
      <input type="hidden" name="id" value={product?.id ?? ""} />
      <Card>
        <CardHeader>
          <CardTitle>اطلاعات اصلی محصول</CardTitle>
          <CardDescription>این اطلاعات بدون تغییر سورس در هر دو ربات نمایش داده می‌شوند.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-2 text-sm font-medium">
              نام محصول
              <Input name="name" required maxLength={255} defaultValue={product?.name ?? ""} />
            </label>
            <label className="space-y-2 text-sm font-medium">
              کد SKU (اختیاری؛ در صورت خالی بودن خودکار ساخته می‌شود)
              <Input name="sku" dir="ltr" maxLength={64} className="text-start" defaultValue={product?.sku ?? ""} />
            </label>
          </div>
          <label className="block space-y-2 text-sm font-medium">
            توضیحات
            <Textarea name="description" maxLength={40000} rows={8} defaultValue={product?.description ?? ""} />
          </label>
          <CategoryPicker initial={categories} selectedId={product?.category_id ?? null} />
        </CardContent>
      </Card>
      <div className="space-y-5">
        <Card>
          <CardHeader><CardTitle>قیمت و موجودی</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-2 text-sm font-medium">
              قیمت به ریال (عدد صحیح)
              <Input type="number" dir="ltr" name="price_irr" min={0} step={1} max={9999999999999999} required defaultValue={product?.price_irr ?? "0"} className="text-start" />
            </label>
            <label className="block space-y-2 text-sm font-medium">
              موجودی
              <Input type="number" dir="ltr" name="stock_quantity" min={0} max={100000000} required defaultValue={product?.stock_quantity ?? 0} className="text-start" />
            </label>
            <label className="block space-y-2 text-sm font-medium">
              نوع کالا
              <select
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                name="product_type"
                value={kind}
                onChange={(event) => setKind(event.target.value as "physical" | "digital")}
              >
                <option value="physical">فیزیکی</option>
                <option value="digital">دیجیتال</option>
              </select>
            </label>
            {kind === "digital" ? (
              <label className="block space-y-2 text-sm font-medium">
                قیمت مستقل Telegram Stars
                <Input type="number" dir="ltr" name="price_stars" min={1} step={1} defaultValue={product?.price_stars ?? ""} className="text-start" placeholder="در صورت فروش دیجیتال در تلگرام" />
              </label>
            ) : (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name="requires_shipping" defaultChecked={product?.requires_shipping ?? true} className="size-4 accent-primary" />
                نیازمند آدرس و ارسال
              </label>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>انتشار</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-2 text-sm font-medium">
              ترتیب نمایش
              <Input type="number" name="position" min={0} max={1000000} defaultValue={product?.position ?? 0} required dir="ltr" />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="is_published" defaultChecked={product?.is_published ?? false} className="size-4 accent-primary" />
              محصول برای مشتریان منتشر شود
            </label>
            <p className="text-xs leading-6 text-muted-foreground">محصول جدید ابتدا منتشرنشده است؛ پرداخت و موجودی در سرویس اصلی مدیریت می‌شوند.</p>
            <Button type="submit" className="w-full"><Save /> ذخیره محصول</Button>
          </CardContent>
        </Card>
      </div>
    </form>
    {product?.id ? <div className="mt-5">
        <Card><CardHeader><CardTitle>تصاویر و فایل‌های محصول</CardTitle>
          <CardDescription>آپلود چندگانه، Drag & Drop و تأیید انتشار هر فایل؛ فایل‌های اصلی به‌صورت خصوصی نگهداری می‌شوند.</CardDescription>
        </CardHeader><CardContent><ProductMediaManager productId={product.id} initial={media} /></CardContent></Card>
      </div> : <div className="mt-5 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
        پس از ذخیرهٔ محصول، بدون ورود به بخش جداگانه، تصاویر و فایل‌ها را در همین صفحه اضافه کنید.
      </div>}
    </div>
  );
}
