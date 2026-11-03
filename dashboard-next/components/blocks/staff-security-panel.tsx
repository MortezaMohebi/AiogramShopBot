"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Copy, KeyRound, Link2, Search, ShieldCheck, UserPlus, X } from "lucide-react";
import { updateStaff } from "@/app/(console)/staff/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { controlAction } from "@/lib/account-control";

export interface StaffMember {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  mfa_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}
export interface StaffInviteRecord {
  id: string;
  username: string;
  role: string;
  status: "pending" | "accepted" | "cancelled" | "expired";
  expires_at: string;
}
export interface PasswordPolicy {
  min_length: number;
  require_upper: boolean;
  require_lower: boolean;
  require_digit: boolean;
  require_symbol: boolean;
}
const roles: Array<[string, string]> = [
  ["viewer", "مشاهده"], ["sales", "فروش"], ["content", "محتوا"],
  ["finance", "مالی"], ["marketing", "بازاریابی"], ["superadmin", "مدیر اصلی"],
];
const roleName = (role: string) => roles.find(([key]) => key === role)?.[1] ?? role;
const stateName: Record<string, string> = {
  pending: "منتظر پذیرش", accepted: "پذیرفته‌شده",
  cancelled: "لغوشده", expired: "منقضی‌شده",
};

/**
 * Sensitive operations use a revocable, recently authenticated backend
 * session. Raw invitation links are held in React memory only and disappear
 * on navigation; the backend stores only their SHA-256 digests.
 */
export function StaffSecurityPanel({
  members, invites, initialPolicy, currentId,
}: {
  members: StaffMember[];
  invites: StaffInviteRecord[];
  initialPolicy: PasswordPolicy;
  currentId: number;
}) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [policy, setPolicy] = useState(initialPolicy);
  const filtered = useMemo(
    () => members.filter((member) => member.username.toLowerCase().includes(search.toLowerCase())),
    [members, search],
  );
  async function perform(action: string, data: unknown, linkKind?: "invite" | "reset") {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setLink(null);
    try {
      const result = await controlAction(action, data);
      if (linkKind) {
        if (!result.token || !/^[A-Za-z0-9_-]{43}$/.test(result.token)) throw new Error("لینک امنیتی دریافت نشد.");
        // Fragment identifiers are never sent to the server in URL requests.
        setLink(`${window.location.origin}/activate#${linkKind}=${result.token}`);
        setNotice("لینک فقط یک‌بار نمایش داده می‌شود. آن را از کانالی امن به صاحب حساب برسانید.");
      } else {
        setNotice("تغییرات ثبت شد.");
      }
      router.refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "انجام عملیات ممکن نشد.");
    } finally {
      setBusy(false);
    }
  }
  function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget, data = new FormData(form);
    const username = String(data.get("username") ?? "").trim().toLowerCase();
    const role = String(data.get("role") ?? "viewer");
    if (!/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username)) {
      setNotice("نام کاربری معتبر نیست.");
      return;
    }
    void perform("staff-invite", { username, role }, "invite");
    form.reset();
  }
  function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void perform("password-policy", policy);
  }
  async function copyLink() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setNotice("لینک در حافظهٔ موقت کپی شد؛ در مکانی عمومی قرار ندهید.");
    } catch {
      setNotice("مرورگر اجازهٔ کپی نداد؛ لینک را به‌صورت دستی انتخاب کنید.");
    }
  }
  return <div className="space-y-6" aria-busy={busy}>
    {notice ? <p role="status" className="rounded-lg border bg-muted/60 p-3 text-sm leading-7">{notice}</p> : null}
    {link ? <Card>
      <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Link2 className="size-5" /> لینک یک‌بارمصرف</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs leading-7 text-muted-foreground">این لینک مانند رمز عبور محرمانه است. لینک دعوت ۴۸ ساعت و لینک بازیابی ۳۰ دقیقه اعتبار دارد.</p>
        <Input value={link} readOnly dir="ltr" aria-label="لینک یک‌بارمصرف" className="font-mono text-xs" onFocus={(event) => event.target.select()} />
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => void copyLink()}><Copy className="size-4" /> کپی لینک امن</Button>
          <Button type="button" variant="outline" onClick={() => setLink(null)}><X className="size-4" /> پنهان‌کردن</Button>
        </div>
      </CardContent>
    </Card> : null}
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><UserPlus className="size-5" /> دعوت کارمند</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={invite} className="space-y-4">
            <label className="block space-y-2 text-sm">نام کاربری
              <Input name="username" dir="ltr" minLength={3} maxLength={80} required placeholder="newoperator" autoComplete="off" />
            </label>
            <label className="block space-y-2 text-sm">نقش
              <select name="role" defaultValue="viewer" className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
                {roles.map(([value, title]) => <option key={value} value={value}>{title}</option>)}
              </select>
            </label>
            <p className="text-xs leading-7 text-muted-foreground">کارمند خودش رمز انتخاب می‌کند؛ مدیر رمز او را نمی‌بیند. برای نقش مدیر اصلی و مالی، MFA اجباری است.</p>
            <Button type="submit" disabled={busy}><UserPlus className="size-4" /> ساخت لینک دعوت</Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-5" /> سیاست رمز عبور</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={savePolicy} className="space-y-3">
            <label className="block space-y-2 text-sm">حداقل طول
              <Input type="number" min={12} max={64} required value={policy.min_length}
                onChange={(event) => setPolicy((previous) => ({ ...previous, min_length: Number(event.target.value) }))} />
            </label>
            {([
              ["require_upper", "حداقل یک حرف بزرگ"],
              ["require_lower", "حداقل یک حرف کوچک"],
              ["require_digit", "حداقل یک رقم"],
              ["require_symbol", "حداقل یک نماد ویژه"],
            ] as const).map(([field, title]) => <label key={field} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={policy[field]} onChange={(event) => setPolicy((previous) => ({ ...previous, [field]: event.target.checked }))} className="size-4 accent-primary" />
              {title}
            </label>)}
            <p className="text-xs text-muted-foreground">این سیاست برای رمزهای جدید و تغییر رمز اعمال می‌شود، نه با تغییر اجباری رمزهای فعلی.</p>
            <Button type="submit" variant="outline" disabled={busy}><ShieldCheck className="size-4" /> ذخیره سیاست</Button>
          </form>
        </CardContent>
      </Card>
    </div>
    <Card>
      <CardHeader><CardTitle>فهرست کارکنان</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="relative max-w-md">
          <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label="جست‌وجوی نام کاربری کارکنان" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="جست‌وجوی نام کاربری…" className="ps-10" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[690px] border-collapse text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3 font-medium">نام کاربری</th><th className="p-3 font-medium">نقش و وضعیت</th>
              <th className="p-3 font-medium">MFA</th><th className="p-3 font-medium">آخرین ورود</th>
              <th className="p-3 font-medium">عملیات</th>
            </tr></thead>
            <tbody>{filtered.map((member) => <tr key={member.id} className="border-b align-top">
              <td className="p-3 font-medium" dir="ltr">{member.username}</td>
              <td className="p-3">
                {member.id === currentId ? <span>حساب شما · {roleName(member.role)}</span> :
                  <form id={`member-${member.id}`} action={updateStaff} className="space-y-2">
                    <input name="id" type="hidden" value={member.id} />
                    <select name="role" defaultValue={member.role} aria-label={`نقش ${member.username}`} className="h-9 w-full rounded-md border border-input bg-background px-2">
                      {roles.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                    </select>
                    <label className="flex items-center gap-2 text-xs"><input name="is_active" type="checkbox" defaultChecked={member.is_active} /> حساب فعال</label>
                  </form>}
                <p className="mt-1 text-xs text-muted-foreground">{member.is_active ? "فعال" : "غیرفعال"}</p>
              </td>
              <td className="p-3">{member.mfa_enabled ? "فعال" : ["superadmin", "finance"].includes(member.role) ? "الزامی؛ در انتظار فعال‌سازی" : "غیرفعال"}</td>
              <td className="p-3 text-xs">{member.last_login_at ? new Date(member.last_login_at).toLocaleString("fa-IR") : "هنوز وارد نشده"}</td>
              <td className="space-y-2 p-3">
                {member.id === currentId ? <span className="text-xs text-muted-foreground">از حساب من ویرایش کنید</span> : <>
                  <Button size="sm" variant="outline" type="submit" form={`member-${member.id}`}>ذخیره</Button>
                  <Button size="sm" type="button" variant="outline" disabled={busy || !member.is_active}
                    onClick={() => void perform("staff-reset", { staff_id: member.id }, "reset")}>لینک بازیابی</Button>
                </>}
              </td>
            </tr>)}</tbody>
          </table>
        </div>
        {!filtered.length ? <p className="py-5 text-sm text-muted-foreground">حسابی مطابق جست‌وجو نیست.</p> : null}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>دعوت‌نامه‌های اخیر</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {invites.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-b py-3 text-sm">
          <div><strong dir="ltr">{item.username}</strong><p className="mt-1 text-xs text-muted-foreground">{roleName(item.role)} · {stateName[item.status]} · اعتبار تا {new Date(item.expires_at).toLocaleString("fa-IR")}</p></div>
          {item.status === "pending" ? <Button type="button" variant="outline" size="sm" disabled={busy}
            onClick={() => void perform("staff-invite-cancel", { invitation_id: item.id })}>لغو دعوت</Button> : null}
        </div>)}
        {!invites.length ? <p className="text-sm text-muted-foreground">هنوز دعوت‌نامه‌ای ایجاد نشده است.</p> : null}
      </CardContent>
    </Card>
  </div>;
}
