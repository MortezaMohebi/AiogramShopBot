import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type BotCatalogRuleList, catalogEffectLabels,
  type CatalogRuleKind,
} from "@/lib/bot-catalog-acl";
import { setBotCatalogRules } from "@/app/(console)/bots/[id]/catalog-actions";

interface Props {
  botId: string;
  version: number;
  data: BotCatalogRuleList;
  query: string;
}

/**
 * Searchable, paginated product/category Many2many controls for one bot.
 * The same backend predicate is applied to Catalog, Callback and Checkout.
 */
export function BotCatalogAccessPanel({
  botId, version, data, query,
}: Props) {
  const category = data.kind === "category";
  const maxPage = Math.max(1, Math.ceil(data.total / data.page_size));

  function href(page: number, kind: CatalogRuleKind = data.kind): string {
    const params = new URLSearchParams({
      acl_kind: kind,
      acl_page: String(page),
      ...(query ? { acl_q: query } : {}),
    });
    return `/bots/${botId}?${params.toString()}#catalog-access`;
  }

  return <Card>
    <CardHeader>
      <CardTitle id="catalog-access">دسترسی محصولات و دسته‌بندی‌ها به این بات</CardTitle>
    </CardHeader>
    <CardContent className="space-y-5">
      <p className="text-sm leading-7 text-muted-foreground">
        اولویت تصمیم: ممنوعیت صریح محصول، مجوز صریح محصول، قانون دسته‌بندی و سپس پیش‌فرض بات.
        پیش‌فرض این بات <strong>{catalogEffectLabels[data.default_effect]}</strong> است.
        {data.policy_ready ? null : " این فروشگاه هنوز کاتالوگ عملیاتی ندارد."}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm" variant={category ? "outline" : "default"}>
          <Link href={href(1, "product")}>محصولات</Link>
        </Button>
        <Button asChild size="sm" variant={category ? "default" : "outline"}>
          <Link href={href(1, "category")}>دسته‌بندی‌ها</Link>
        </Button>
      </div>
      <form method="get" action={`/bots/${botId}`} className="flex flex-wrap items-end gap-3">
        <input type="hidden" name="acl_kind" value={data.kind} />
        <label className="min-w-52 flex-1 space-y-2 text-sm">
          جست‌وجوی {category ? "دسته‌بندی" : "محصول"}
          <Input name="acl_q" maxLength={100} defaultValue={query}
            placeholder={category ? "نام دسته‌بندی…" : "نام محصول…"} />
        </label>
        <Button type="submit" variant="outline">جست‌وجو</Button>
        <Button asChild variant="outline">
          <Link href={`/bots/${botId}?acl_kind=${data.kind}#catalog-access`}>
            پاک‌کردن
          </Link>
        </Button>
      </form>

      <form action={setBotCatalogRules} className="space-y-4">
        <input type="hidden" name="bot_id" value={botId} />
        <input type="hidden" name="expected_version" value={version} />
        <input type="hidden" name="kind" value={data.kind} />
        <p className="text-xs text-muted-foreground">
          {data.total.toLocaleString("fa-IR")} مورد؛ چند ردیف را انتخاب کنید و یک قانون مشترک به آن‌ها بدهید.
          حذف قانون (ارث‌بری) ردیف قدیمی را پاک می‌کند و Audit آن باقی می‌ماند.
        </p>
        <div className="max-h-[420px] overflow-auto rounded-lg border">
          {data.items.map(item => <label
            key={item.id}
            className="flex cursor-pointer flex-wrap items-center gap-3 border-b p-3 text-sm hover:bg-muted/40"
          >
            <input type="checkbox" name="target_ids" value={item.id}
              className="size-4 accent-primary" />
            <span className="min-w-[130px] flex-1 font-medium">{item.name}</span>
            <span className="text-xs text-muted-foreground">
              {item.effect === "inherit" ? "ارث‌بری" :
                `قانون صریح: ${catalogEffectLabels[item.effect]}`}
            </span>
            {!category ? <span className="text-xs text-muted-foreground">
              {item.effective_access ? "قابل نمایش" : "غیرقابل نمایش"}
            </span> : null}
            {!item.is_published ? <span className="text-xs text-muted-foreground">
              منتشرنشده
            </span> : null}
          </label>)}
          {!data.items.length ? <p className="p-8 text-center text-sm text-muted-foreground">
            موردی مطابق فیلتر یافت نشد.
          </p> : null}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-2 text-sm">قانون انتخاب‌شده‌ها
            <select name="effect" defaultValue="allow"
              className="block h-10 min-w-44 rounded-md border bg-background px-3">
              <option value="allow">مجاز — Allow</option>
              <option value="deny">ممنوع — Deny</option>
              <option value="inherit">حذف قانون — Inherit</option>
            </select>
          </label>
          <Button type="submit" disabled={!data.policy_ready || !data.items.length}>
            اعمال به موارد انتخاب‌شده
          </Button>
        </div>
      </form>
      <nav aria-label="صفحه‌بندی قوانین بات"
        className="flex flex-wrap items-center justify-between gap-2 text-sm">
        {data.page > 1
          ? <Button asChild variant="outline" size="sm"><Link href={href(data.page - 1)}>قبلی</Link></Button>
          : <span />}
        <span>صفحهٔ {data.page.toLocaleString("fa-IR")} از {maxPage.toLocaleString("fa-IR")}</span>
        {data.page < maxPage
          ? <Button asChild variant="outline" size="sm"><Link href={href(data.page + 1)}>بعدی</Link></Button>
          : <span />}
      </nav>
    </CardContent>
  </Card>;
}
