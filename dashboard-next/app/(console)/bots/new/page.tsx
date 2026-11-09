import Link from "next/link";
import { notFound } from "next/navigation";
import { PasswordActionForm } from "@/components/blocks/password-action-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { BotRegistrySnapshot } from "@/lib/bot-registry";
import { createBot } from "../actions";

export default async function NewBotPage({ searchParams }: {
  searchParams: Promise<{ error?: string }>;
}) {
  if ((await currentStaff()).role !== "superadmin") notFound();
  const [result, { error }] = await Promise.all([
    adminFetch<BotRegistrySnapshot>("/bot-registry?page_size=1"), searchParams,
  ]);
  return <>
    <PageHeading title="ربات جدید" action={<Button asChild variant="outline" size="sm"><Link href="/bots">بازگشت به فهرست</Link></Button>} />
    <Card><CardContent className="space-y-4 pt-5">
      {error && <p role="alert" className="text-sm text-destructive">{error === "conflict" ? "این شناسه قبلاً ثبت شده است." : "ثبت ربات انجام نشد. اطلاعات و دسترسی را بررسی کنید."}</p>}
      <PasswordActionForm action={createBot} when="required" includePassword={false} className="space-y-4">
        <label className="block space-y-2 text-sm">فروشگاه
          <select name="store_id" defaultValue={result.default_store_id} required className="h-10 w-full rounded-md border bg-background px-3">
            {result.stores.map(store => <option key={store.id} value={store.id}>{store.name} ({({ active: "فعال", paused: "متوقف", disabled: "غیرفعال", draft: "پیش‌نویس", archived: "بایگانی‌شده" } as Record<string, string>)[store.state] ?? store.state})</option>)}
          </select>
        </label>
        <label className="block space-y-2 text-sm">نام ربات
          <Input name="name" maxLength={160} required placeholder="مثلاً ربات فروش محصولات صنعتی" />
        </label>
        <label className="block space-y-2 text-sm">شناسهٔ داخلی (اختیاری)
          <Input name="slug" dir="ltr" pattern="[a-z][a-z0-9\-]{2,63}" minLength={3} maxLength={64}
            aria-describedby="bot-slug-hint" placeholder="industrial-telegram" />
        </label>
        <p id="bot-slug-hint" className="text-xs text-muted-foreground">اگر خالی بماند، شناسه به‌صورت خودکار ساخته می‌شود.</p>
        <label className="block space-y-2 text-sm">نوع پیام‌رسان
          <select name="platform" className="h-10 w-full rounded-md border bg-background px-3">
            <option value="telegram">تلگرام</option><option value="bale">بله</option>
          </select>
        </label>
        <p className="text-xs text-muted-foreground">ایجاد پیش‌نویس، ربات را فعال نمی‌کند.</p>
        <Button type="submit">ایجاد ربات پیش‌نویس</Button>
      </PasswordActionForm>
    </CardContent></Card>
  </>;
}
