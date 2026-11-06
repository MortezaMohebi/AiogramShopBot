import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";

type Filter = { actor?: string; action?: string; since?: string; until?: string; page?: string };
type AuditEntry = { id: string; actor: number; action: string; target: string; created_at: string };
type AuditResult = { items: AuditEntry[]; total: number; page: number; page_size: number };
type Member = { id: number; username: string };

/** Audit is restricted to superadmins and always read from PostgreSQL. */
export default async function AuditPage({ searchParams }: { searchParams: Promise<Filter> }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const query = await searchParams;
  const page = Math.max(1, Math.min(10000, Number.parseInt(query.page ?? "1", 10) || 1));
  const filters = new URLSearchParams({ page: String(page) });
  if (query.actor && /^[1-9][0-9]*$/.test(query.actor)) filters.set("actor", query.actor);
  if (query.action && /^[a-z._]{1,80}$/.test(query.action)) filters.set("action", query.action);
  if (query.since && /^\d{4}-\d{2}-\d{2}$/.test(query.since)) filters.set("since", `${query.since}T00:00:00Z`);
  if (query.until && /^\d{4}-\d{2}-\d{2}$/.test(query.until)) filters.set("until", `${query.until}T23:59:59Z`);
  const [history, members] = await Promise.all([
    adminFetch<AuditResult>(`/account/audit?${filters.toString()}`),
    adminFetch<Member[]>("/staff"),
  ]);
  const names = new Map(members.map((member) => [member.id, member.username]));
  const last = Math.max(1, Math.ceil(history.total / history.page_size));
  const pageLink = (target: number) => {
    const next = new URLSearchParams(filters);
    next.set("page", String(target));
    // The browser does not submit auth credentials or tokens through URLs.
    return `/audit?${next.toString()}`;
  };
  return <div className="space-y-6">
    <PageHeading title="گزارش تغییرات مدیران" />
    <div><Button asChild variant="outline"><Link href="/staff">بازگشت به کارکنان</Link></Button></div>
    <Card><CardContent className="pt-6">
      <form method="get" className="grid gap-3 md:grid-cols-4">
        <label className="space-y-2 text-sm">کاربر
          <select name="actor" defaultValue={query.actor ?? ""} className="h-10 w-full rounded-md border border-input bg-background px-2">
            <option value="">همه کاربران</option>
            {members.map((member) => <option key={member.id} value={member.id}>{member.username}</option>)}
          </select>
        </label>
        <label className="space-y-2 text-sm">نوع رویداد
          <Input name="action" dir="ltr" placeholder="staff.invitation_issued" defaultValue={query.action ?? ""} />
        </label>
        <label className="space-y-2 text-sm">از تاریخ
          <Input type="date" name="since" defaultValue={query.since ?? ""} />
        </label>
        <label className="space-y-2 text-sm">تا تاریخ
          <Input type="date" name="until" defaultValue={query.until ?? ""} />
        </label>
        <Button type="submit" className="md:col-span-4 md:justify-self-start">اعمال فیلترها</Button>
      </form>
    </CardContent></Card>
    <Card><CardContent className="overflow-x-auto pt-6">
      <p className="mb-4 text-sm text-muted-foreground">{history.total.toLocaleString("fa-IR")} رویداد یافت شد.</p>
      <table className="w-full min-w-[620px] text-right text-sm">
        <thead><tr className="border-b text-muted-foreground"><th className="p-3">زمان</th><th className="p-3">عامل</th><th className="p-3">عملیات</th><th className="p-3">هدف</th></tr></thead>
        <tbody>{history.items.map((entry) => <tr key={entry.id} className="border-b">
          <td className="p-3">{new Date(entry.created_at).toLocaleString("fa-IR")}</td>
          <td className="p-3" dir="ltr">{names.get(entry.actor) ?? `#${entry.actor}`}</td>
          <td className="p-3 font-mono text-xs" dir="ltr">{entry.action}</td>
          <td className="p-3 font-mono text-xs" dir="ltr">{entry.target || "—"}</td>
        </tr>)}</tbody>
      </table>
      {!history.items.length ? <p className="py-8 text-sm text-muted-foreground">{query.actor || query.action || query.since || query.until ? "رویدادی با این فیلترها پیدا نشد." : "هنوز رویدادی ثبت نشده است."}</p> : null}
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm">
        {page > 1 ? <Button asChild variant="outline"><Link href={pageLink(page - 1)}>قبلی</Link></Button> : <span />}
        <span>صفحه {page.toLocaleString("fa-IR")} از {last.toLocaleString("fa-IR")}</span>
        {page < last ? <Button asChild variant="outline"><Link href={pageLink(page + 1)}>بعدی</Link></Button> : <span />}
      </div>
    </CardContent></Card>
  </div>;
}
