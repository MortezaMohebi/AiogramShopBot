import Link from "next/link";
import { notFound } from "next/navigation";
import { createStaff, updateStaff } from "@/app/(console)/staff/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";

const roles = [["viewer", "مشاهده"], ["sales", "فروش"], ["content", "محتوا"], ["finance", "مالی"], ["marketing", "بازاریابی"], ["superadmin", "مدیر اصلی"]] as const;
const errors: Record<string, string> = {
  reauthentication_required: "پیش از تغییر کارکنان، در حساب من رمز فعلی و کد دومرحله‌ای را تأیید کنید.",
  staff_username_exists: "نام کاربری تکراری است.", last_admin_protected: "آخرین مدیر اصلی فعال قابل غیرفعال‌سازی نیست.",
  use_my_account: "برای تغییر رمز شخصی از حساب من استفاده کنید.",
};
type Member = { id: number; username: string; role: string; is_active: boolean };

/** Account lifecycle controls with least-privilege defaults and clear reauthentication. */
export default async function StaffPage({ searchParams }: { searchParams: Promise<{ saved?: string; error?: string }> }) {
  const current = await currentStaff();
  if (current.role !== "superadmin") notFound();
  const [members, params] = await Promise.all([adminFetch<Member[]>("/staff"), searchParams]);
  return <div className="space-y-6">
    <PageHeading title="مدیران و دسترسی‌ها" description="تغییر دسترسی با ثبت رویداد و ابطال نشست‌های قبلی؛ پیش‌فرض حساب جدید فقط مشاهده است." />
    <p className="text-sm leading-7 text-muted-foreground">عملیات این صفحه به تأیید امنیتی پنج دقیقهٔ اخیر نیاز دارد. <Link className="underline" href="/account">حساب من و تأیید مجدد</Link> · <Link className="underline" href="/permissions">جدول مجوزهای نقش‌ها</Link></p>
    {params.saved ? <p role="status" className="rounded-lg bg-accent p-3">تغییرات ثبت شد.</p> : null}
    {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-destructive">{errors[params.error] ?? "ثبت انجام نشد. فیلدها، نشست و سطح دسترسی را بررسی کنید."}</p> : null}
    <Card><CardHeader><CardTitle>افزودن کاربر پنل</CardTitle></CardHeader><CardContent>
      <form action={createStaff} className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2 text-sm">نام کاربری<Input name="username" dir="ltr" minLength={3} maxLength={80} pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]{2,79}" required autoComplete="off" /></label>
        <label className="space-y-2 text-sm">نقش<select name="role" defaultValue="viewer" className="h-10 w-full rounded border bg-background px-3">{roles.map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
        <label className="space-y-2 text-sm">رمز اولیه (حداقل ۱۴ نویسه)<Input name="password" type="password" minLength={14} maxLength={256} required autoComplete="new-password" /></label>
        <label className="space-y-2 text-sm">تأیید ساخت: CREATE_STAFF<Input name="confirmation" dir="ltr" pattern="CREATE_STAFF" required /></label>
        <Button type="submit">ساخت حساب</Button>
      </form>
    </CardContent></Card>
    {members.map((member) => <Card key={member.id}><CardHeader><CardTitle><span dir="ltr">{member.username}</span> · {member.is_active ? "فعال" : "غیرفعال"}</CardTitle></CardHeader><CardContent>
      {member.id === current.id ? <p className="text-sm">حساب فعلی شما. <Link href="/account" className="underline">تغییر رمز، MFA و نشست‌ها در حساب من</Link></p> : <form action={updateStaff} className="grid gap-4 md:grid-cols-2">
        <input type="hidden" name="id" value={member.id} />
        <label className="space-y-2 text-sm">نقش<select name="role" defaultValue={member.role} className="h-10 w-full rounded border bg-background px-3">{roles.map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="is_active" defaultChecked={member.is_active} />حساب فعال باشد</label>
        <label className="space-y-2 text-sm">بازنشانی رمز (اختیاری)<Input name="password" type="password" minLength={14} maxLength={256} autoComplete="new-password" /></label>
        <label className="space-y-2 text-sm">تأیید تغییر: UPDATE_STAFF<Input name="confirmation" dir="ltr" pattern="UPDATE_STAFF" required /></label>
        <Button type="submit" variant="outline">ذخیره و ابطال نشست‌های قبلی</Button>
      </form>}
    </CardContent></Card>)}
  </div>;
}
