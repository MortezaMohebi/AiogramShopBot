import { StoreScopeNotice } from "@/components/blocks/store-scope-notice";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  purgeCustomerNotes, saveRetentionPolicy,
} from "@/app/(console)/customers/retention/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { optionalStoreRead, currentStaff } from "@/lib/bridge";

type Policy = { note_retention_days: number; audit_retention_days: number };
type Query = Promise<{ saved?: string; error?: string; count?: string }>;

/** No unattended GDPR or ledger deletion: explicit, auditable case-note cleanup. */
export default async function CustomerRetentionPage({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [policy, query] = await Promise.all([
    optionalStoreRead<Policy>("/customer-retention"), searchParams,
  ]);
  if (!policy) return <StoreScopeNotice title="سیاست نگهداری اطلاعات مشتری" />;
  const count = query.count && /^(0|[1-9][0-9]{0,15})$/.test(query.count)
    && Number.isSafeInteger(Number(query.count))
    ? Number(query.count).toLocaleString("fa-IR") : null;
  return <div className="space-y-5">
    <Button asChild variant="outline" size="sm"><Link href="/customers">بازگشت به مشتریان</Link></Button>
    <PageHeading title="سیاست نگهداری اطلاعات مشتری" description="نگهداری داده‌های پشتیبانی بدون آسیب‌زدن به سفارش‌ها، اسناد مالی یا تاریخچهٔ رضایت." />
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      {query.saved === "purged" ? (count !== null
        ? `${count} یادداشت منقضی‌شده حذف شد و رویداد آن در سوابق ثبت شد.`
        : "یادداشت‌های منقضی‌شده مطابق سیاست حذف شدند و رویداد آن در سوابق ثبت شد.") :
        query.saved === "preview" ? (count !== null
          ? `${count} یادداشت قابل حذف است. در این بررسی هیچ یادداشتی حذف نشد.`
          : "بررسی بدون حذف انجام شد. هیچ یادداشتی حذف نشد.") : "سیاست نگهداری ذخیره شد."}
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
      {query.error === "reauth" ? "برای این عملیات، هویت خود را در همین صفحه تأیید کنید." :
        query.error === "receipt" ? "نتیجهٔ پاکسازی تأیید نشد. پیش از تکرار، سوابق و وضعیت یادداشت‌ها را بررسی کنید." :
          "عملیات کامل نشد؛ وضعیت سرویس و داده‌ها را بررسی کنید."}
    </p> : null}
    <Card><CardHeader><CardTitle>دوره‌های نگهداری</CardTitle></CardHeader><CardContent className="space-y-5">
      <form action={saveRetentionPolicy} className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2 text-sm">نگهداری یادداشت‌های داخلی (روز)
          <Input name="note_retention_days" type="number" min={30} max={3650} required defaultValue={policy.note_retention_days} />
        </label>
        <label className="space-y-2 text-sm">دورهٔ نگهداری سوابق پشتیبانی (روز)
          <Input name="audit_retention_days" type="number" min={365} max={3650} required defaultValue={policy.audit_retention_days} />
        </label>
        <p className="md:col-span-2 text-xs leading-7 text-muted-foreground">
          تغییر سیاست موجب پاکسازی خودکار نمی‌شود. سوابق پشتیبانی برای بررسی‌های بعدی محفوظ می‌ماند؛ پاکسازی زیر تنها یادداشت‌های داخلی قدیمی را دربر می‌گیرد.
        </p>
        <Button type="submit" className="md:justify-self-start">ذخیره سیاست</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>پاکسازی کنترل‌شدهٔ یادداشت‌ها</CardTitle></CardHeader><CardContent className="space-y-4">
      <p className="text-sm leading-7">فقط یادداشت‌های قدیمی‌تر از مدت تعیین‌شده حذف می‌شوند. هیچ سفارش، تراکنش کیف پول، رضایت تبلیغاتی یا پروندهٔ مشتری حذف نخواهد شد.</p>
      <form action={purgeCustomerNotes} className="space-y-4">
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" name="confirm" className="mt-1 size-4 accent-primary" />
          تأیید می‌کنم که درخواست پاکسازی واقعی یادداشت‌های منقضی‌شده است؛ برای بررسی صرف، این گزینه را خالی می‌گذارم.
        </label>
        <Button type="submit" variant="outline">اجرای بررسی یا پاکسازی طبق تأیید</Button>
      </form>
    </CardContent></Card>
  </div>;
}
