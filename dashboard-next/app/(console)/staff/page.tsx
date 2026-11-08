import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { ReauthenticateButton } from "@/components/blocks/reauthentication";
import { notFound } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { StaffSecurityPanel, type StaffInviteRecord, type StaffMember, type PasswordPolicy } from "@/components/blocks/staff-security-panel";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";

type Params = Promise<{ saved?: string; error?: string }>;
const errors: Record<string, string> = {
  reauthentication_required: "هویت خود را در همین صفحه تأیید کنید.",
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
    <PageHeading title="کارکنان" />
    <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4 text-sm">
      <ShieldCheck className="size-5 text-primary" aria-hidden="true" />
      <span className="min-w-0 flex-1 leading-7">تأیید هویت برای تغییر دسترسی‌ها پنج دقیقه اعتبار دارد.</span>
      <ReauthenticateButton />
      <Button asChild variant="outline"><Link href="/audit">گزارش تغییرات مدیران</Link></Button>
    </div>
    {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">تغییرات ثبت شد.</p> : null}
    {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{errors[params.error] ?? "ذخیره ممکن نشد؛ دسترسی، وضعیت نشست و داده‌ها را بررسی کنید."}</p> : null}
    <StaffSecurityPanel members={members} invites={invitations.items} initialPolicy={policy} currentId={operator.id} />
    <section aria-labelledby="store-access-title" className="space-y-3 rounded-xl border bg-card p-5">
      <h2 id="store-access-title" className="text-base font-semibold">
        دسترسی کاربران به فروشگاه‌ها
      </h2>
      <p className="text-sm leading-7 text-muted-foreground">
        فروشگاه‌های مجاز و فروشگاه پیش‌فرض هر کاربر را جداگانه تعیین کنید. نقش کاربر، سطح دسترسی او را محدود می‌کند.
      </p>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {members.map(member => <RecordClickArea as="div" key={member.id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border p-3 text-sm">
          <RecordLink href={`/staff/${member.id}/stores`} className="min-w-0 break-words"><bdi>{member.username}</bdi></RecordLink>
          <span className="text-muted-foreground">{({ viewer: "مشاهده‌گر", sales: "فروش", content: "محتوا", finance: "مالی", marketing: "بازاریابی", superadmin: "مدیر اصلی" } as Record<string, string>)[member.role] ?? member.role}</span>
        </RecordClickArea>)}
      </div>
    </section>
  </div>;
}
