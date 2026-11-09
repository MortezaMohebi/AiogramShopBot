"use client";

import { useState } from "react";
import { DraftForm, type DraftReceipt } from "@/components/blocks/draft-form";
import { useRouter } from "next/navigation";
import { AccountSecurityWizard, type SecurityAction } from "@/components/blocks/account-security-wizard";
import { ReauthenticateButton } from "@/components/blocks/reauthentication";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type AccountData, controlAction, permissionLabels } from "@/lib/account-control";

const roleLabels: Record<string, string> = {
  superadmin: "مدیر اصلی", finance: "مالی", sales: "فروش", content: "محتوا",
  marketing: "بازاریابی", viewer: "مشاهده",
};
const eventLabels: Record<string, string> = {
  "staff.first_owner_created": "حساب مدیر اصلی ایجاد شد",
  "session.created": "ورود جدید", "session.revoked": "خروج از یک دستگاه",
  "session.others_revoked": "خروج از دستگاه‌های دیگر", "account.profile_changed": "ویرایش مشخصات",
  "account.password_changed": "تغییر رمز عبور", "account.username_changed": "تغییر نام کاربری",
  "account.reauthenticated": "تأیید مجدد هویت", "mfa.enabled": "فعال‌سازی احراز هویت دومرحله‌ای",
  "mfa.disabled": "غیرفعال‌سازی احراز هویت دومرحله‌ای", "mfa.recovery_used": "استفاده از کد بازیابی",
  "mfa.enrollment_started": "شروع فعال‌سازی احراز هویت دومرحله‌ای",
};
const permissionGroups = [
  { name: "مدیریت حساب و فروشگاه", prefixes: ["account", "dashboard", "settings", "staff", "audit"] },
  { name: "فروش و مشتریان", prefixes: ["catalog", "media", "customers", "orders", "shipping", "coupons"] },
  { name: "امور مالی و گزارش‌ها", prefixes: ["finance", "wallet", "refund", "reports"] },
  { name: "ربات‌ها و عملیات", prefixes: ["bots", "workflows", "actions", "campaigns", "broadcast"] },
];

/** Summarize browser identity without exposing the full user-agent string. */
function deviceLabel(agent: string): string {
  const browser = /Edg(?:e|A|iOS)?\//i.test(agent) ? "Edge"
    : /OPR\//i.test(agent) ? "Opera" : /Firefox|FxiOS/i.test(agent) ? "Firefox"
    : /Chrome|CriOS/i.test(agent) ? "Chrome" : /Safari/i.test(agent) ? "Safari" : "";
  const system = /Windows/i.test(agent) ? "Windows" : /Android/i.test(agent) ? "Android"
    : /iPhone|iPad|iPod/i.test(agent) ? "iOS" : /Macintosh|Mac OS/i.test(agent) ? "macOS"
    : /Linux/i.test(agent) ? "Linux" : "";
  return browser && system ? `${browser} در ${system}` : browser || system || "دستگاه ناشناس";
}

type SessionTarget = { action: "revoke-others" } | { action: "revoke-session"; id: string; current: boolean };

export function AccountPanel({ initial }: { initial: AccountData }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState({ display_name: initial.display_name, time_zone: initial.time_zone });
  const [preferences, setPreferences] = useState(initial.preferences);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [wizard, setWizard] = useState<SecurityAction | null>(null);
  const [sessionTarget, setSessionTarget] = useState<SessionTarget | null>(null);
  const [sessionError, setSessionError] = useState("");
  const zones = typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : ["Asia/Tehran", "Asia/Tokyo", "Europe/London", "UTC"];
  if (!zones.includes(profile.time_zone)) zones.push(profile.time_zone);
  zones.sort((a, b) => a.localeCompare(b));
  const calendarLocale =
    preferences.calendar === "gregorian" ? "fa-IR-u-ca-gregory" :
    preferences.calendar === "jalali" ? "fa-IR-u-ca-persian" :
    preferences.language === "en" ? "en-US-u-ca-gregory" : "fa-IR-u-ca-persian";
  const formatter = new Intl.DateTimeFormat(calendarLocale, {
    timeZone: profile.time_zone, dateStyle: "short", timeStyle: "short",
  });
  const date = (value: string) => formatter.format(new Date(value));

  async function perform(action: string, payload: unknown) {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setSessionError("");
    try {
      const result = await controlAction(action, payload);
      if (result.login_required) { window.location.replace("/login"); return; }
      setSessionTarget(null);
      const messages: Record<string, string> = {
        "revoke-others": "از دستگاه‌های دیگر خارج شدید.", "revoke-session": "نشست دستگاه بسته شد.",
      };
      setNotice({ ok: true, text: messages[action] ?? "تغییرات حساب ذخیره شد." });
      router.refresh();
    } catch (error) {
      const text = error instanceof Error ? error.message : "عملیات انجام نشد.";
      if (sessionTarget) setSessionError(text);
      else setNotice({ ok: false, text });
    } finally { setBusy(false); }
  }

  async function saveProfile(data: FormData) {
    const updated = {
      display_name: String(data.get("display_name") ?? "").trim(),
      time_zone: String(data.get("time_zone") ?? ""),
    };
    return savePreference("profile", updated, () => setProfile(updated));
  }

  async function savePreferences(data: FormData) {
    const language = data.get("language");
    const calendar = data.get("calendar");
    if ((language !== "fa" && language !== "en") ||
        (calendar !== "auto" && calendar !== "jalali" && calendar !== "gregorian")) {
      return { ok: false, code: "validation" } as const;
    }
    const updated: AccountData["preferences"] = {
      language, calendar,
      notify_orders: data.has("notify_orders"),
      notify_campaigns: data.has("notify_campaigns"),
      notify_finance: data.has("notify_finance"),
      notify_system: data.has("notify_system"),
    };
    return savePreference("preferences", updated, () => setPreferences(updated));
  }

  async function savePreference(action: string, data: unknown, confirm: () => void): Promise<DraftReceipt> {
    try {
      const result = await controlAction(action, data);
      if (result.login_required) return { ok: false, code: "session_expired" };
      confirm();
      router.refresh();
      return { ok: true, data: null };
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : "ذخیره تأیید نشد." };
    }
  }

  const needsEnrollment = initial.mfa_required_by_role && !initial.mfa_enabled;
  const sessions = [...initial.sessions].sort((a, b) =>
    Number(b.current) - Number(a.current) || Number(b.active) - Number(a.active));
  const mfaStatus = initial.mfa_enabled
    ? initial.mfa_required_by_role ? "فعال و الزامی برای نقش شما" : "فعال"
    : "غیرفعال";
  const mfaCard = <Card><CardHeader><CardTitle>احراز هویت دومرحله‌ای</CardTitle></CardHeader>
    <CardContent className="space-y-3">
      <Badge tone={initial.mfa_enabled ? "success" : "neutral"}>{mfaStatus}</Badge>
      {needsEnrollment ? <p className="text-sm leading-7 text-muted-foreground">برای ورود به داشبورد، احراز هویت دومرحله‌ای را فعال کنید.</p> : null}
      {!initial.mfa_enabled ? <div><Button type="button" onClick={() => setWizard("mfa-setup")}>فعال‌سازی</Button></div>
        : !initial.mfa_required_by_role ? <div><Button type="button" variant="outline" onClick={() => setWizard("mfa-disable")}>غیرفعال‌سازی</Button></div> : null}
    </CardContent>
  </Card>;

  return <div className="space-y-5" aria-busy={busy}>
    {wizard ? <AccountSecurityWizard key={wizard} action={wizard}
      reuseLoginProof={needsEnrollment}
      minimumPassword={initial.password_policy.min_length} onClose={() => setWizard(null)}
      onSuccess={text => setNotice({ ok: true, text })} /> : null}
    {notice ? <p role={notice.ok ? "status" : "alert"} className={notice.ok ? "rounded-lg bg-accent p-3 text-sm" : "rounded-lg bg-destructive/10 p-3 text-sm text-destructive"}>{notice.text}</p> : null}
    {needsEnrollment ? mfaCard : <>
    <nav aria-label="بخش‌های حساب" className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm"><a href="#account-profile">مشخصات و ترجیحات</a></Button>
      <Button asChild variant="outline" size="sm"><a href="#account-security">ورود و امنیت</a></Button>
      <Button asChild variant="outline" size="sm"><a href="#account-activity">فعالیت و دسترسی‌ها</a></Button>
    </nav>
    <section id="account-profile" aria-label="مشخصات و ترجیحات" className="scroll-mt-5 space-y-4">
    <Card><CardHeader><CardTitle>مشخصات من</CardTitle></CardHeader><CardContent>
      <p className="mb-4 text-sm">نام کاربری: <b dir="ltr">{initial.username}</b> · نقش: <b>{roleLabels[initial.role] ?? "کاربر"}</b></p>
      <DraftForm saveAction={saveProfile} className="grid gap-4 md:grid-cols-2" footerClassName="md:col-span-2">
        <label className="block space-y-2 text-sm">نام نمایشی<Input className="h-10 w-full" name="display_name" defaultValue={profile.display_name} maxLength={120} /></label>
        <label className="block space-y-2 text-sm">منطقهٔ زمانی
          <select name="time_zone" defaultValue={profile.time_zone} required dir="ltr" className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
            {zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
          </select>
        </label>
      </DraftForm>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>زبان، تقویم و اعلان‌های کاری</CardTitle></CardHeader><CardContent>
      <DraftForm saveAction={savePreferences} className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block space-y-2 text-sm">زبان ترجیحی پنل
            <select name="language" defaultValue={preferences.language}
              className="h-10 w-full rounded-md border bg-background px-3">
              <option value="fa">فارسی</option>
              <option value="en">English</option>
            </select>
          </label>
          <label className="block space-y-2 text-sm">نمایش تاریخ در حساب من
            <select name="calendar" defaultValue={preferences.calendar}
              className="h-10 w-full rounded-md border bg-background px-3">
              <option value="auto">خودکار</option>
              <option value="jalali">جلالی</option>
              <option value="gregorian">میلادی</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-muted-foreground">زبان ترجیحی ذخیره می‌شود؛ همهٔ صفحات پنل هنوز ترجمه نشده‌اند. انتخاب تقویم فقط تاریخ‌های حساب من را تغییر می‌دهد.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {([
            ["notify_orders", "اعلان سفارش‌ها"],
            ["notify_campaigns", "اعلان کمپین‌ها"],
            ["notify_finance", "اعلان مالی"],
            ["notify_system", "اعلان کارهای سیستمی"],
          ] as const).map(([field, title]) =>
            <label key={field} className="flex items-center gap-2 text-sm">
              <input type="checkbox" name={field} defaultChecked={preferences[field]}
                className="size-4 accent-primary" />{title}
            </label>
          )}
        </div>
        <p className="text-xs text-muted-foreground">اعلان‌های امنیتی ضروری از این تنظیمات تأثیر نمی‌گیرند.</p>
      </DraftForm>
    </CardContent></Card>
    </section>
    <section id="account-security" aria-label="ورود و امنیت" className="scroll-mt-5 space-y-4">
    <Card>
      <CardHeader><CardTitle>ورود و امنیت</CardTitle></CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={() => setWizard("username")}>تغییر نام کاربری</Button>
        <Button type="button" variant="outline" onClick={() => setWizard("password")}>تغییر رمز عبور</Button>
        <ReauthenticateButton />
      </CardContent>
    </Card>
    {mfaCard}
    <Card>
      <CardHeader><CardTitle>نشست‌ها و دستگاه‌ها</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">{sessions.filter(session => session.active).length.toLocaleString("fa-IR")} نشست فعال</p>
          {sessions.some(session => session.active && !session.current) ?
            <Button type="button" variant="outline" size="sm" disabled={busy}
              onClick={() => { setSessionError(""); setSessionTarget({ action: "revoke-others" }); }}>
              خروج از همهٔ دستگاه‌های دیگر
            </Button> : null}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {sessions.map(session => <article key={session.id}
            className={`min-w-0 space-y-1.5 rounded-lg border p-3 ${session.current ? "border-primary/50 bg-primary/5" : ""}`}>
            <div className="flex flex-wrap items-center gap-2">
              <strong className="text-sm"><bdi>{deviceLabel(session.label)}</bdi></strong>
              {session.current ? <Badge tone="success">این دستگاه</Badge>
                : !session.active ? <Badge tone="neutral">پایان‌یافته</Badge> : null}
            </div>
            <p className="text-xs text-muted-foreground">آخرین فعالیت {date(session.last_seen_at)}</p>
            {session.active ? <div className="flex flex-wrap items-center justify-between gap-1">
              <p className="text-xs text-muted-foreground">پایان اعتبار {date(session.expires_at)}</p>
              <Button type="button" variant="ghost" size="sm" disabled={busy}
                aria-label={session.current ? "خروج از این دستگاه" : `خروج از ${deviceLabel(session.label)}`} onClick={() => {
                setSessionError("");
                setSessionTarget({ action: "revoke-session", id: session.id, current: session.current });
              }}>خروج</Button>
            </div> : null}
          </article>)}
        </div>
        {!sessions.length ? <p className="text-sm text-muted-foreground">نشستی ثبت نشده است.</p> : null}
      </CardContent>
    </Card>
    </section>
    <section id="account-activity" aria-label="فعالیت و دسترسی‌ها" className="scroll-mt-5 space-y-4">
    <Card><CardHeader><CardTitle>دسترسی‌های حساب</CardTitle></CardHeader><CardContent>
      <details className="space-y-3">
        <summary className="cursor-pointer text-sm font-medium">مشاهدهٔ دسترسی‌های نقش {roleLabels[initial.role] ?? "کاربر"}</summary>
        <div className="grid gap-3 sm:grid-cols-2">
          {permissionGroups.map(group => {
            const entries = initial.permissions.filter(permission =>
              group.prefixes.some(prefix => permission.startsWith(prefix + ".")) && Object.hasOwn(permissionLabels, permission));
            return entries.length ? <div className="space-y-2 rounded-lg border p-3" key={group.name}>
              <h3 className="text-sm font-medium">{group.name}</h3>
              <ul className="list-inside list-disc space-y-1 text-xs text-muted-foreground">
                {entries.map(permission => <li key={permission}>{permissionLabels[permission]}</li>)}
              </ul>
            </div> : null;
          })}
        </div>
      </details>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>رویدادهای امنیتی اخیر</CardTitle></CardHeader><CardContent>
      {initial.events.length ? initial.events.map(event => <div key={event.id} className="flex flex-wrap justify-between gap-2 border-b py-2 text-sm">
        <span>{eventLabels[event.action] ?? "رویداد امنیتی حساب"}</span><time dateTime={event.created_at} className="text-xs text-muted-foreground">{date(event.created_at)}</time>
      </div>) : <p className="text-sm text-muted-foreground">رویدادی ثبت نشده است.</p>}
    </CardContent></Card>
    </section>
    </>}
    {sessionTarget ? <Dialog open label="تأیید خروج از دستگاه" onClose={() => { if (!busy) setSessionTarget(null); }}>
      <section className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">تأیید خروج از دستگاه</h2>
        <p className="text-sm leading-7">{sessionTarget.action === "revoke-others"
          ? "نشست دستگاه‌های دیگر بسته می‌شود. این دستگاه همچنان وارد می‌ماند."
          : sessionTarget.current ? "از حساب در همین دستگاه خارج می‌شوید." : "برای استفاده از پنل در آن دستگاه باید دوباره وارد شوید."}</p>
        {sessionError ? <p role="alert" className="text-sm text-destructive">{sessionError}</p> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="destructive" disabled={busy} onClick={() =>
            void perform(sessionTarget.action, sessionTarget.action === "revoke-others" ? {} : { session_id: sessionTarget.id })}>
            {busy ? "در حال خروج…" : "تأیید خروج"}
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => setSessionTarget(null)}>انصراف</Button>
        </div>
      </section>
    </Dialog> : null}
  </div>;
}
