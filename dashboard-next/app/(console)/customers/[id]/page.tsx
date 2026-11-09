import { DraftForm } from "@/components/blocks/draft-form";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  addCustomerNote, restrictCustomer, saveCustomerProfile,
} from "@/app/(console)/customers/[id]/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PersianDatePicker } from "@/components/ui/persian-date-picker";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";

type Event = { actor?: number; action?: string; reason?: string | null; created_at?: string | null };
type Order = { id: number; status: string; provider: string; total_irr: string; created_at: string | null };
type Note = { id: number; actor: number; content: string; created_at: string | null };
type Consent = { allowed: boolean; source: string; topic: string; created_at: string | null };
type Ledger = { id: number; delta_irr: string; balance_after_irr: string; reason: string; created_at: string | null };
type CustomerDetail = {
  customer: {
    id: number; platform: string; user_id: string; name: string | null;
    username: string | null; is_blocked: boolean; allow_announcements: boolean;
    bot_blocked_by_customer: boolean | null; tags: string[];
    owner_staff_id: number | null; support_status: string;
    restriction_reason: string | null; restriction_until: string | null;
    registered_at: string | null;
  };
  verified_other_platform: { id: number; platform: string; user_id: string; approved_at: string | null } | null;
  wallet_balance_irr: string;
  orders: Order[];
  notes: Note[];
  consent: Consent[];
  activity: Event[];
  ledger: Ledger[];
};
type Search = Promise<{ saved?: string; error?: string }>;
const fmt = (value: string) => value ? new Date(value).toLocaleString("fa-IR") : "—";

/** Customer support case; all identifiers remain provider-scoped. */
export default async function CustomerDetailPage({
  params, searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Search;
}) {
  const actor = await currentStaff();
  if (!["superadmin", "sales"].includes(actor.role)) notFound();
  const { id } = await params;
  if (!/^[1-9][0-9]*$/.test(id)) notFound();
  const [data, assignees, query] = await Promise.all([
    adminFetch<CustomerDetail>(`/customers/${id}`),
    adminFetch<{ items: { id: number; username: string }[] }>("/customers/assignees"),
    searchParams,
  ]);
  const customer = data.customer;
  const names = new Map(assignees.items.map(item => [item.id, item.username]));
  return <div className="space-y-5">
    <div><Button asChild size="sm" variant="outline"><Link href="/customers">بازگشت به مشتریان</Link></Button></div>
    <PageHeading title={customer.name || `مشتری شماره ${id}`} description={`پروندهٔ ${customer.platform === "telegram" ? "تلگرام" : "بله"}، شناسهٔ ${customer.user_id}؛ داده‌های دو پیام‌رسان بدون اثبات مالکیت ادغام نمی‌شوند.`} />
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">تغییرات ثبت شد.</p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
      {query.error === "reauth" ? "هویت خود را در همین صفحه تأیید کنید." :
        query.error === "reason" ? "برای محدودسازی، دلیل حداقل هشت نویسه‌ای وارد کنید." :
        query.error === "permission" ? "مجوز لازم برای این عملیات را ندارید." :
        "ذخیره انجام نشد؛ داده‌ها و وضعیت حساب را بررسی کنید."}
    </p> : null}
    <div className="flex flex-wrap gap-2 text-sm">
      <Badge tone={customer.is_blocked ? "danger" : "success"}>{customer.is_blocked ? "محدود در فروشگاه" : "فعال در فروشگاه"}</Badge>
      <Badge tone={customer.allow_announcements ? "success" : "neutral"}>{customer.allow_announcements ? "رضایت تبلیغاتی" : "بدون رضایت تبلیغاتی"}</Badge>
      <Badge tone="neutral">مسدودکردن ربات توسط مشتری: {customer.bot_blocked_by_customer === null ? "نامشخص" : customer.bot_blocked_by_customer ? "تأیید شده" : "ثبت نشده"}</Badge>
      {actor.role === "superadmin" ? <Button asChild variant="outline" size="sm"><a href={`/api/admin/customers/${id}/export`}>خروجی JSON اطلاعات مشتری</a></Button> : null}
    </div>
    <Card><CardContent className="pt-5 text-sm">
      <strong>ارتباط هویت بین دو پیام‌رسان</strong>
      {data.verified_other_platform ? <p className="mt-2 leading-7">
        هویت متناظر با تأیید مالکیت در {data.verified_other_platform.platform === "telegram" ? "تلگرام" : "بله"}:
        <Link className="ms-2 font-medium underline" href={`/customers/${data.verified_other_platform.id}`}>
          شناسه {data.verified_other_platform.user_id}
        </Link>
        {" · "} زمان تأیید: {data.verified_other_platform.approved_at ? fmt(data.verified_other_platform.approved_at) : "—"}
      </p> : <p className="mt-2 text-muted-foreground">
        ارتباط تأییدشده‌ای ثبت نشده است. مشتری می‌تواند در بات نخست /linkstart و سپس /linkconfirm و /linkapprove را در دو پیام‌رسان اجرا کند.
      </p>}
      <p className="mt-1 text-xs text-muted-foreground">ارتباط هویت به معنای ادغام کیف پول، سفارش یا رضایت تبلیغاتی نیست.</p>
    </CardContent></Card>
    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>پرونده و پیگیری</CardTitle></CardHeader><CardContent>
        <DraftForm saveAction={saveCustomerProfile} className="space-y-4">
          <input type="hidden" name="customer_id" value={id} />
          <label className="block space-y-2 text-sm">برچسب‌ها (با کاما جدا شوند؛ حداکثر ۱۲ برچسب)
            <Input name="tags" defaultValue={customer.tags.join("، ").replaceAll("، ", ", ")} maxLength={500} />
          </label>
          <label className="block space-y-2 text-sm">مسئول پیگیری
            <select name="owner_staff_id" defaultValue={customer.owner_staff_id ?? ""} className="h-10 w-full rounded-md border bg-background px-3">
              <option value="">بدون مسئول</option>
              {assignees.items.map(item => <option key={item.id} value={item.id}>{item.username}</option>)}
            </select>
          </label>
          <label className="block space-y-2 text-sm">وضعیت پشتیبانی
            <select name="support_status" defaultValue={customer.support_status} className="h-10 w-full rounded-md border bg-background px-3">
              <option value="open">باز</option><option value="pending">در انتظار</option><option value="resolved">حل‌شده</option>
            </select>
          </label>
        </DraftForm>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>محدودسازی فروشگاه</CardTitle></CardHeader><CardContent className="space-y-4">
        <p className="text-xs leading-7 text-muted-foreground">این محدودیت فقط مربوط به فروشگاه است و به معنای مسدودشدن ربات توسط مشتری نیست. تأثیری روی سفارش‌های تسویه‌شده ندارد.</p>
        <p className="text-xs">دلیل فعلی: {customer.restriction_reason || "ثبت نشده"} · انقضا: {customer.restriction_until ? fmt(customer.restriction_until) : "بدون انقضا"}</p>
        <form action={restrictCustomer} className="space-y-3">
          <input type="hidden" name="customer_id" value={id} />
          <input type="hidden" name="blocked" value="true" />
          <label className="block space-y-2 text-sm">دلیل محدودسازی
            <Textarea name="reason" rows={3} minLength={8} maxLength={500} required />
          </label>
          <PersianDatePicker name="until" label="انقضا (اختیاری)" withTime />
          <Button type="submit" variant="destructive">ثبت محدودیت</Button>
        </form>
        {customer.is_blocked ? <form action={restrictCustomer}>
          <input type="hidden" name="customer_id" value={id} />
          <input type="hidden" name="blocked" value="false" />
          <Button type="submit" variant="outline">رفع محدودیت فروشگاه</Button>
        </form> : null}
      </CardContent></Card>
    </div>
    <Card><CardHeader><CardTitle>یادداشت‌های داخلی</CardTitle></CardHeader><CardContent className="space-y-4">
      <form action={addCustomerNote} className="space-y-3">
        <input type="hidden" name="customer_id" value={id} />
        <label className="block space-y-2 text-sm">یادداشت جدید
          <Textarea name="content" rows={3} minLength={1} maxLength={4000} required />
        </label>
        <Button type="submit">ثبت یادداشت</Button>
      </form>
      {data.notes.map(note => <div key={note.id} className="border-t py-3">
        <p className="whitespace-pre-wrap text-sm">{note.content}</p>
        <p className="mt-1 text-xs text-muted-foreground">{names.get(note.actor) || `#${note.actor}`} · {note.created_at ? fmt(note.created_at) : "—"}</p>
      </div>)}
      {!data.notes.length ? <p className="text-sm text-muted-foreground">یادداشتی وجود ندارد.</p> : null}
    </CardContent></Card>
    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>سفارش‌های اخیر</CardTitle></CardHeader><CardContent className="space-y-2">
        {data.orders.map(order => <div key={order.id} className="flex flex-wrap justify-between gap-2 border-b py-2 text-sm">
          <span>#{order.id} · {order.status} · {order.provider}</span>
          <span dir="ltr">{order.total_irr} IRR</span>
        </div>)}
        {!data.orders.length ? <p className="text-sm text-muted-foreground">سفارشی وجود ندارد.</p> : null}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>اعتبار و تراکنش‌ها</CardTitle></CardHeader><CardContent className="space-y-2">
        <p className="text-sm font-semibold" dir="ltr">{data.wallet_balance_irr} IRR</p>
        {data.ledger.map(entry => <div key={entry.id} className="flex flex-wrap justify-between gap-2 border-b py-2 text-xs">
          <span>{entry.reason}</span><span dir="ltr">{entry.delta_irr} IRR</span>
        </div>)}
        {!data.ledger.length ? <p className="text-sm text-muted-foreground">تراکنشی وجود ندارد.</p> : null}
      </CardContent></Card>
    </div>
    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>تاریخچهٔ رضایت تبلیغاتی</CardTitle></CardHeader><CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">رضایت فقط از درخواست خود مشتری ثبت می‌شود. مدیر نمی‌تواند آن را به‌جای مشتری فعال کند.</p>
        {data.consent.map((entry, idx) => <p key={idx} className="border-b py-2 text-xs">
          {entry.allowed ? "اعطای رضایت" : "لغو رضایت"} · {entry.source} · {entry.topic} · {entry.created_at ? fmt(entry.created_at) : "—"}
        </p>)}
        {!data.consent.length ? <p className="text-sm text-muted-foreground">اطلاعات تاریخی رضایت موجود نیست؛ وضعیت فعلی بالا نمایش داده شده است.</p> : null}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>سوابق تغییرات پرونده</CardTitle></CardHeader><CardContent className="space-y-2">
        {data.activity.map((entry, idx) => <p key={idx} className="border-b py-2 text-xs">
          {entry.action} · {entry.actor ? names.get(entry.actor) ?? entry.actor : "—"} · {entry.created_at ? fmt(entry.created_at) : "—"}
        </p>)}
        {!data.activity.length ? <p className="text-sm text-muted-foreground">رویدادی ثبت نشده است.</p> : null}
      </CardContent></Card>
    </div>
  </div>;
}
