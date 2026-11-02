import { notFound } from "next/navigation";
import { createStaff, updateStaff } from "@/app/(console)/staff/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";

type StaffMember = {
  id: number; username: string; role: string; is_active: boolean; created_at: string;
};
type Params = Promise<{saved?: string; error?: string}>;
const roles = [
  ["superadmin", "مدیر اصلی"], ["sales", "فروش"], ["content", "محتوا"],
  ["finance", "مالی"], ["marketing", "بازاریابی"], ["viewer", "مشاهده"],
] as const;

/** Superadmin-only database staff management with session revocation. */
export default async function StaffPage({ searchParams }: { searchParams: Params }) {
  const current = await currentStaff();
  if (current.role !== "superadmin") notFound();
  const [members, params] = await Promise.all([
    adminFetch<StaffMember[]>("/staff"), searchParams,
  ]);
  return (
    <div className="space-y-6">
      <PageHeading title="مدیران و دسترسی‌ها" description="حساب‌های واقعی کارکنان؛ ویرایش نقش، غیرفعال‌سازی و تغییر رمز، نشست‌های قدیمی را باطل می‌کند." />
      {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">تغییرات حساب مدیریتی ثبت شد.</p> : null}
      {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">عملیات انجام نشد. تکراری‌نبودن نام، رمز حداقل ۱۴ نویسه و محدودیت آخرین مدیر اصلی را بررسی کنید.</p> : null}
      <Card>
        <CardHeader><CardTitle>افزودن مدیر</CardTitle></CardHeader>
        <CardContent>
          <form action={createStaff} className="grid gap-4 lg:grid-cols-2">
            <label className="space-y-2 text-sm">نام کاربری انگلیسی
              <Input name="username" pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]{2,79}" minLength={3} maxLength={80} required autoComplete="off" dir="ltr" />
            </label>
            <label className="space-y-2 text-sm">نقش
              <select name="role" className="h-10 w-full rounded-md border border-input bg-background px-3">
                {roles.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
              </select>
            </label>
            <label className="space-y-2 text-sm">رمز جدید (حداقل ۱۴ نویسه)
              <Input name="password" type="password" minLength={14} maxLength={256} required autoComplete="new-password" />
            </label>
            <label className="space-y-2 text-sm">تأیید عملیات
              <Input name="confirmation" required placeholder="CREATE_STAFF" dir="ltr" />
            </label>
            <div className="lg:col-span-2"><Button type="submit">ساخت حساب</Button></div>
          </form>
        </CardContent>
      </Card>
      <div className="grid gap-4">
        {members.map((member) => (
          <Card key={member.id}>
            <CardContent className="space-y-4 py-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <strong dir="ltr">{member.username}</strong>
                  <p className="mt-1 text-xs text-muted-foreground">شناسه #{member.id} · عضویت {new Date(member.created_at).toLocaleDateString("fa-IR")}</p>
                </div>
                <Badge tone={member.is_active ? "success" : "danger"}>{member.is_active ? "فعال" : "غیرفعال"}</Badge>
              </div>
              <form action={updateStaff} className="grid gap-3 md:grid-cols-2">
                <input type="hidden" name="id" value={member.id} />
                <input type="hidden" name="self" value={member.id === current.id ? "1" : "0"} />
                {member.id !== current.id ? (
                  <>
                    <label className="space-y-1 text-sm">نقش
                      <select name="role" defaultValue={member.role} className="h-10 w-full rounded-md border border-input bg-background px-3">
                        {roles.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input name="is_active" type="checkbox" defaultChecked={member.is_active} className="size-4 accent-primary" />
                      حساب فعال باشد
                    </label>
                  </>
                ) : <p className="text-sm text-muted-foreground md:col-span-2">برای جلوگیری از قفل‌شدن پنل، نمی‌توانید نقش یا وضعیت حساب خود را تغییر دهید؛ تغییر رمز مجاز است.</p>}
                <label className="space-y-1 text-sm">رمز تازه (اختیاری)
                  <Input name="password" type="password" minLength={14} maxLength={256} autoComplete="new-password" placeholder="اگر تغییر ندارد، خالی بماند" />
                </label>
                <label className="space-y-1 text-sm">تأیید تغییر
                  <Input name="confirmation" required dir="ltr" placeholder="UPDATE_STAFF" />
                </label>
                <div className="md:col-span-2"><Button type="submit" size="sm">ذخیره و ابطال نشست‌های قبلی</Button></div>
              </form>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
