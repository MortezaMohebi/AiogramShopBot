import Link from "next/link";
import { notFound } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { StaffSecurityPanel, type StaffInviteRecord, type StaffMember, type PasswordPolicy } from "@/components/blocks/staff-security-panel";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";

type Params = Promise<{ saved?: string; error?: string }>;
const errors: Record<string, string> = {
  reauthentication_required: "ابتدا در حساب من، تأیید مجدد هویت را انجام دهید.",
  staff_username_exists: "نام کاربری از قبل وجود دارد.",
  last_admin_protected: "آخرین مدیر اصلی فعال را نمی‌توان غیرفعال کرد.",
  use_my_account: "برای تغییر حساب خودتان به حساب من بروید.",
  mfa_enrollment_required: "ابتدا MFA حساب مدیر را فعال کنید.",
};

/** Secure lifecycle, password policy and an accessible searchable staff table. */
export default async function StaffPage({ searchParams }: { searchParams: Params }) {
  const operator = await currentStaff();
  if (operator.role !== "superadmin") notFound();
  const [members, invitations, policy, params] = await Promise.all([
    adminFetch<StaffMember[]>("/staff"),
    adminFetch<{ items: StaffInviteRecord[] }>("/staff/invitations"),
    adminFetch<PasswordPolicy>("/staff/password-policy"),
    searchParams,
  ]);
  return <div className="space-y-6">
    <PageHeading title="کارکنان و امنیت" description="دعوت امن، سیاست رمز قابل تنظیم، بازیابی یک‌بارمصرف و نظارت بر MFA کارکنان." />
    <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4 text-sm">
      <ShieldCheck className="size-5 text-primary" aria-hidden="true" />
      <span className="flex-1 leading-7">عملیات حساس به تأیید هویت پنج دقیقهٔ اخیر نیاز دارد؛ هیچ مدیر دیگری رمز کاربر را تعیین نمی‌کند.</span>
      <Button asChild variant="outline"><Link href="/account">تأیید هویت در حساب من</Link></Button>
      <Button asChild variant="outline"><Link href="/audit">گزارش Audit مدیران</Link></Button>
    </div>
    {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">تغییرات ثبت شد.</p> : null}
    {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{errors[params.error] ?? "ذخیره ممکن نشد؛ دسترسی، وضعیت نشست و داده‌ها را بررسی کنید."}</p> : null}
    <StaffSecurityPanel members={members} invites={invitations.items} initialPolicy={policy} currentId={operator.id} />
    <section aria-labelledby="store-access-title" className="space-y-3 rounded-xl border bg-card p-5">
      <h2 id="store-access-title" className="text-base font-semibold">
        دسترسی کاربران به فروشگاه‌ها
      </h2>
      <p className="text-sm leading-7 text-muted-foreground">
        Allowed Stores و Default Store هر کاربر مستقل از نقش سراسری او است.
        دسترسی مؤثر تنها در Storeهای مجاز و فعال نشست اعمال می‌شود.
      </p>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {members.map(member => <div key={member.id}
          className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
          <span className="min-w-0 truncate">{member.username} · {member.role}</span>
          <Button asChild size="sm" variant="outline">
            <Link href={`/staff/${member.id}/stores`}>Storeهای مجاز</Link>
          </Button>
        </div>)}
      </div>
    </section>
  </div>;
}
