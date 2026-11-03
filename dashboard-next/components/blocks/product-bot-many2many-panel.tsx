"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type ProductBotCatalogList, catalogEffectLabels,
  catalogBotLabel,
} from "@/lib/bot-catalog-acl";
import { setProductBotAccess } from "@/app/(console)/products/[id]/edit/bot-acl-actions";

interface Props {
  data: ProductBotCatalogList;
  query: string;
  saved: boolean;
  error: boolean;
}

/** Searchable Many2many editor: select multiple bots, then allow/deny/inherit. */
export function ProductBotMany2ManyPanel({
  data, query, saved, error,
}: Props) {
  const maxPage = Math.max(1, Math.ceil(data.total / data.page_size));
  function pageUrl(page: number, q = query): string {
    const params = new URLSearchParams({ bot_page: String(page) });
    if (q) params.set("bot_q", q);
    return `/products/${data.product_id}/edit?${params}#bot-access`;
  }
  return <Card>
    <CardHeader>
      <CardTitle id="bot-access">دسترسی محصول در بات‌ها (Many2many)</CardTitle>
    </CardHeader>
    <CardContent className="space-y-4">
      <p className="text-sm leading-7 text-muted-foreground">
        این محصول برای کدام بات‌ها قابل نمایش باشد؟ چند بات را انتخاب کنید و
        وضعیت صریح Allow / Deny یا ارث‌بری از دسته‌بندی را اعمال کنید.
        تغییرات محصول و قوانین بات در دو عملیات جدا ذخیره می‌شوند.
      </p>
      {saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
        قوانین دسترسی بات‌ها ذخیره و Audit شدند.
      </p> : null}
      {error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
        ذخیرهٔ دسترسی انجام نشد؛ مجوز حساب، نسخه و انتخاب‌ها را بررسی کنید.
      </p> : null}
      <form method="get" action={`/products/${data.product_id}/edit`}
        className="flex flex-wrap items-end gap-2">
        <label className="min-w-52 flex-1 space-y-2 text-sm">جست‌وجوی بات
          <Input name="bot_q" defaultValue={query} maxLength={100}
            placeholder="نام بات تلگرام یا بله…" />
        </label>
        <Button type="submit" variant="outline">جست‌وجو</Button>
        <Button asChild variant="outline">
          <Link href={pageUrl(1, "")}>پاک‌کردن</Link>
        </Button>
      </form>
      <form action={setProductBotAccess} className="space-y-4">
        <input type="hidden" name="product_id" value={data.product_id} />
        <div className="max-h-[360px] overflow-y-auto rounded-lg border">
          {data.bots.map(bot => <label key={bot.id}
            className="flex cursor-pointer flex-wrap items-center gap-3 border-b p-3 text-sm hover:bg-muted/40">
            <input type="checkbox" name="bot_ids" value={bot.id}
              className="size-4 accent-primary" />
            <input type="hidden" name={`version_${bot.id}`} value={bot.version} />
            <span className="min-w-[130px] flex-1">
              <strong>{bot.name}</strong>
              <span className="ms-2 text-xs text-muted-foreground">
                {catalogBotLabel(bot.platform)}
              </span>
            </span>
            <span className="text-xs text-muted-foreground">
              {bot.effect === "inherit"
                ? `ارث‌بری (پیش‌فرض ${catalogEffectLabels[bot.default_effect]})`
                : `صریح: ${catalogEffectLabels[bot.effect]}`}
            </span>
            <span className="text-xs text-muted-foreground">
              {bot.status === "draft" ? "Draft" : ""}
            </span>
          </label>)}
          {!data.bots.length ? <p className="p-7 text-center text-sm text-muted-foreground">
            باتی یافت نشد.
          </p> : null}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-2 text-sm">وضعیت برای بات‌های انتخاب‌شده
            <select name="effect" defaultValue="allow"
              className="block h-10 min-w-44 rounded-md border bg-background px-3">
              <option value="allow">Allow — مجاز</option>
              <option value="deny">Deny — ممنوع</option>
              <option value="inherit">Inherit — حذف قانون صریح</option>
            </select>
          </label>
          <Button type="submit" disabled={!data.bots.length}>ذخیره دسترسی بات‌ها</Button>
        </div>
      </form>
      <nav className="flex items-center justify-between gap-3 text-sm" aria-label="صفحه‌بندی بات‌ها">
        {data.page > 1
          ? <Button asChild size="sm" variant="outline"><Link href={pageUrl(data.page - 1)}>قبلی</Link></Button>
          : <span />}
        <span>صفحهٔ {data.page.toLocaleString("fa-IR")} از {maxPage.toLocaleString("fa-IR")}</span>
        {data.page < maxPage
          ? <Button asChild size="sm" variant="outline"><Link href={pageUrl(data.page + 1)}>بعدی</Link></Button>
          : <span />}
      </nav>
      <p className="text-xs leading-6 text-muted-foreground">
        بات تازه به‌طور پیش‌فرض به هیچ محصولی دسترسی ندارد.
        Deny صریح محصول از همهٔ قوانین دسته‌بندی قوی‌تر است و
        Product Allow از Category Deny اولویت بالاتری دارد.
      </p>
    </CardContent>
  </Card>;
}
