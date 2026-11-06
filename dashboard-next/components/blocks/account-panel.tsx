"use client";
import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type AccountData, controlAction, permissionLabels } from "@/lib/account-control";

/** Each proof is entered by the owner; passwords are never trimmed or persisted. */
function ProofFields({ factor, disabled }: { factor: boolean; disabled: boolean }) {
  return <div className="grid gap-3 md:grid-cols-2">
    <label className={factor ? "space-y-2 text-sm" : "space-y-2 text-sm md:col-span-2"}>رمز فعلی
      <Input name="current_password" type="password" autoComplete="current-password" maxLength={256} required disabled={disabled} dir="ltr" />
    </label>
    {factor ? <label className="space-y-1 text-sm">کد احراز هویت یا بازیابی
      <Input name="second_factor" autoComplete="one-time-code" maxLength={64} required disabled={disabled} dir="ltr" />
    </label> : null}
  </div>;
}
const eventLabels: Record<string, string> = {
  "session.created": "ورود جدید", "session.revoked": "خروج از یک دستگاه", "session.others_revoked": "ابطال نشست‌های دیگر",
  "account.profile_changed": "ویرایش مشخصات", "account.password_changed": "تغییر رمز", "mfa.enabled": "فعال‌سازی MFA",
  "mfa.disabled": "غیرفعال‌سازی MFA", "mfa.recovery_used": "استفاده از کد بازیابی", "mfa.enrollment_started": "شروع فعال‌سازی MFA",
};
/** Self-service, revocable sessions and explicit security actions for every role. */
export function AccountPanel({ initial }: { initial: AccountData }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [enrollment, setEnrollment] = useState<{
    secret: string;
    qrDataUri: string;
  } | null>(null), [recovery, setRecovery] = useState<string[]>([]);
  // The browser supplies a searchable, official list of IANA time zones.
  const zones = typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : ["Asia/Tehran", "Asia/Tokyo", "Europe/London", "UTC"];
  if (!zones.includes(initial.time_zone)) zones.push(initial.time_zone);
  zones.sort((a, b) => a.localeCompare(b));
  const calendarLocale =
    initial.preferences.calendar === "gregorian" ? "fa-IR-u-ca-gregory" :
    initial.preferences.calendar === "jalali" ? "fa-IR-u-ca-persian" :
    initial.preferences.language === "en" ? "en-US-u-ca-gregory" :
    "fa-IR-u-ca-persian";
  function date(value: string) {
    return new Date(value).toLocaleString(calendarLocale, {
      timeZone: initial.time_zone,
    });
  }
  async function perform(action: string, payload: unknown, form?: HTMLFormElement) {
    if (busy) return;
    setBusy(true); setNotice(null);
    try {
      const result = await controlAction(action, payload);
      if (result.login_required) { router.replace("/login?expired=1"); router.refresh(); return; }
      if (action === "mfa-setup") {
        if (
          !result.secret ||
          !result.qr_data_uri?.startsWith("data:image/png;base64,")
        ) {
          throw new Error("کد QR دریافت نشد. دوباره فعال‌سازی را شروع کنید.");
        }
        setEnrollment({
          secret: result.secret,
          qrDataUri: result.qr_data_uri,
        });
      }
      if (result.recovery_codes) { setRecovery(result.recovery_codes); setEnrollment(null); }
      const successMessages: Record<string, string> = {
        profile: "مشخصات ذخیره شد.",
        preferences: "ترجیحات ذخیره شد.",
        username: "نام کاربری تغییر کرد.",
        password: "رمز عبور تغییر کرد.",
        "mfa-setup": "کد برنامهٔ احراز هویت را برای تکمیل فعال‌سازی وارد کنید.",
        "mfa-confirm": "احراز هویت دومرحله‌ای فعال شد.",
        "mfa-disable": "احراز هویت دومرحله‌ای غیرفعال شد.",
        reauthenticate: "هویت شما تأیید شد. این تأیید پنج دقیقه اعتبار دارد.",
        "revoke-others": "نشست‌های دستگاه‌های دیگر بسته شد.",
        "revoke-session": "نشست دستگاه بسته شد.",
      };
      setNotice({ ok: true, text: successMessages[action] ?? "تغییرات حساب ذخیره شد." });
      if (action !== "profile" && action !== "preferences") form?.reset();
      router.refresh();
    } catch (error) { setNotice({ ok: false, text: error instanceof Error ? error.message : "عملیات انجام نشد." }); }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>, action: string) {
    event.preventDefault(); const form = event.currentTarget, values = new FormData(form);
    const payload: Record<string, string> = {};
    for (const [key, value] of values) if (typeof value === "string") payload[key] = value;
    void perform(action, payload, form);
  }
  const noticeMessage = notice ? <p role={notice.ok ? "status" : "alert"} className={notice.ok ? "rounded-lg bg-accent p-3 text-sm" : "rounded-lg bg-destructive/10 p-3 text-sm text-destructive"}>{notice.text}</p> : null;
  const mfaCard = <Card><CardHeader><CardTitle>احراز هویت دومرحله‌ای</CardTitle></CardHeader><CardContent className="space-y-4">
      <p className="text-sm">وضعیت: <strong>{initial.mfa_enabled ? "فعال" : "غیرفعال"}</strong></p>
      {initial.mfa_required_by_role ? <p className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">برای نقش شما MFA اجباری است. تا زمان فعال‌سازی، دسترسی به امکانات مدیریتی محدود می‌ماند.</p> : null}
      {recovery.length ? <div role="status" className="space-y-3 rounded-lg border p-4">
        <p className="text-sm">این کدها فقط همین بار نمایش داده می‌شوند. در محلی امن ذخیره کنید؛ هر کد یک‌بار قابل استفاده است.</p>
        <pre dir="ltr" className="overflow-auto text-xs">{recovery.join("\n")}</pre>
        <Button type="button" variant="outline" onClick={() => setRecovery([])}>پنهان کردن کدها</Button>
      </div> : null}
      {enrollment ? <div className="space-y-4">
        <p className="text-sm leading-7">
          در برنامهٔ Authenticator گزینهٔ افزودن حساب و اسکن QR Code را
          انتخاب کنید. سپس کد شش‌رقمی برنامه را برای فعال‌سازی وارد کنید.
        </p>
        {/* QR generation happens in our Backend; the TOTP secret is never
            sent to a third-party image service or CDN. */}
        <div className="mx-auto w-fit max-w-full rounded-xl border bg-white p-3 shadow-sm">
          <Image
            src={enrollment.qrDataUri}
            alt="QR Code فعال‌سازی احراز هویت دومرحله‌ای"
            width={260}
            height={260}
            unoptimized
            className="h-auto w-full max-w-[260px]"
          />
        </div>
        <details className="rounded-lg border p-3 text-sm">
          <summary className="cursor-pointer font-medium">
            امکان اسکن ندارم؛ نمایش کلید برای ورود دستی
          </summary>
          <p className="mt-3 text-xs leading-6 text-muted-foreground">
            این کلید محرمانه است. آن را با دیگران به اشتراک نگذارید.
          </p>
          <code dir="ltr" className="mt-2 block select-all break-all rounded-md bg-muted p-3 text-xs">
            {enrollment.secret}
          </code>
        </details>
        <form onSubmit={(event) => submit(event, "mfa-confirm")} className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm">کد تأیید<Input name="code" pattern="[0-9]{6}" minLength={6} maxLength={6} autoComplete="one-time-code" inputMode="numeric" required dir="ltr" disabled={busy} /></label>
          <Button type="submit" disabled={busy}>تأیید و فعال‌سازی</Button>
        </form>
      </div> : <form onSubmit={(event) => submit(event, initial.mfa_enabled ? "mfa-disable" : "mfa-setup")} className="space-y-4">
        <ProofFields factor={initial.mfa_enabled} disabled={busy} />
        {!(initial.mfa_enabled && initial.mfa_required_by_role) ? <Button type="submit" variant={initial.mfa_enabled ? "destructive" : "default"} disabled={busy}>{initial.mfa_enabled ? "غیرفعال‌سازی MFA" : "شروع فعال‌سازی MFA"}</Button> : null}
      </form>}
    </CardContent></Card>;
  // Only enrollment actions are allowed until the role’s mandatory factor exists.
  if (initial.mfa_required_by_role && !initial.mfa_enabled) {
    return <div className="mx-auto max-w-2xl space-y-5" aria-busy={busy}>{noticeMessage}{mfaCard}</div>;
  }
  return <div className="space-y-5" aria-busy={busy}>
    {noticeMessage}
    <Card><CardHeader><CardTitle>مشخصات من</CardTitle></CardHeader><CardContent>
      <p className="mb-4 text-sm">نام کاربری: <b dir="ltr">{initial.username}</b> · نقش: <b>{({superadmin:"مدیر اصلی",finance:"مالی",sales:"فروش",content:"محتوا",marketing:"بازاریابی",viewer:"مشاهده"} as Record<string,string>)[initial.role] ?? initial.role}</b></p>
      <form onSubmit={(event) => submit(event, "profile")} className="grid gap-4 md:grid-cols-2">
        <label className="block space-y-2 text-sm">نام نمایشی<Input className="h-10 w-full" name="display_name" defaultValue={initial.display_name} maxLength={120} disabled={busy} /></label>
        <label className="block space-y-2 text-sm">منطقهٔ زمانی
          <select name="time_zone" defaultValue={initial.time_zone} required disabled={busy} dir="ltr" className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
            {zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
          </select>
        </label>
        <Button type="submit" disabled={busy}>ذخیره مشخصات</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>زبان، تقویم و اعلان‌های کاری</CardTitle></CardHeader><CardContent>
      <form onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        void perform("preferences", {
          language: String(data.get("language") ?? "fa"),
          calendar: String(data.get("calendar") ?? "auto"),
          notify_orders: data.has("notify_orders"),
          notify_campaigns: data.has("notify_campaigns"),
          notify_finance: data.has("notify_finance"),
          notify_system: data.has("notify_system"),
        }, form);
      }} className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block space-y-2 text-sm">زبان ترجیحی پنل
            <select name="language" defaultValue={initial.preferences.language} disabled={busy}
              className="h-10 w-full rounded-md border bg-background px-3">
              <option value="fa">فارسی</option>
              <option value="en">English</option>
            </select>
          </label>
          <label className="block space-y-2 text-sm">نمایش تاریخ در حساب من
            <select name="calendar" defaultValue={initial.preferences.calendar} disabled={busy}
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
              <input type="checkbox" name={field} defaultChecked={initial.preferences[field]}
                disabled={busy} className="size-4 accent-primary" />{title}
            </label>
          )}
        </div>
        <p className="text-xs text-muted-foreground">اعلان‌های امنیتی ضروری از این تنظیمات تأثیر نمی‌گیرند.</p>
        <Button type="submit" variant="outline" disabled={busy}>ذخیره ترجیحات</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>تغییر نام کاربری</CardTitle></CardHeader><CardContent>
      <form onSubmit={(event) => submit(event, "username")} className="space-y-4">
        <p className="text-xs text-muted-foreground">تغییر نام کاربری نیازمند رمز فعلی و MFA است. پس از تغییر، تمام دستگاه‌ها خارج خواهند شد.</p>
        <label className="block space-y-2 text-sm">نام کاربری جدید
          <Input name="username" dir="ltr" minLength={3} maxLength={80}
            pattern="[a-z0-9][a-z0-9_.-]{2,79}" required disabled={busy}
            autoCapitalize="none" autoCorrect="off" />
        </label>
        <ProofFields factor={initial.mfa_enabled} disabled={busy} />
        <Button type="submit" variant="outline" disabled={busy}>تغییر نام کاربری و خروج از نشست‌ها</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>تغییر رمز عبور</CardTitle></CardHeader><CardContent>
      <form onSubmit={(event) => submit(event, "password")} className="space-y-4">
        <ProofFields factor={initial.mfa_enabled} disabled={busy} />
        <label className="block space-y-1 text-sm">رمز تازه (حداقل {initial.password_policy.min_length} نویسه)<Input name="new_password" type="password" autoComplete="new-password" minLength={initial.password_policy.min_length} maxLength={256} dir="ltr" required disabled={busy} /></label>
        <p className="text-xs leading-6 text-muted-foreground">بعد از تغییر رمز، تمام نشست‌ها بسته می‌شوند و باید دوباره وارد شوید.</p>
        <Button type="submit" disabled={busy}>تغییر رمز و خروج از همه دستگاه‌ها</Button>
      </form>
    </CardContent></Card>
    {mfaCard}
    <Card><CardHeader><CardTitle>تأیید مجدد هویت برای عملیات حساس</CardTitle></CardHeader><CardContent>
      <form onSubmit={(event) => submit(event, "reauthenticate")} className="space-y-4">
        <ProofFields factor={initial.mfa_enabled} disabled={busy} />
        <Button type="submit" variant="outline" disabled={busy}>تأیید هویت برای پنج دقیقه</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>نشست‌ها و دستگاه‌ها</CardTitle></CardHeader><CardContent className="space-y-3">
      <p className="text-xs leading-6 text-muted-foreground">ورود عادی پس از ۳۰ دقیقه بی‌فعالیتی یا حداکثر ۸ ساعت پایان می‌یابد. با انتخاب «مرا به خاطر بسپار»، نشست تا ۳۰ روز اعتبار دارد. خروج از حساب یا تغییر رمز، نشست را زودتر می‌بندد.</p>
      <Button type="button" variant="outline" disabled={busy} onClick={() => void perform("revoke-others", {})}>خروج از همه دستگاه‌های دیگر</Button>
      {initial.sessions.map((session) => <div key={session.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-xs">
        <div className="min-w-0 space-y-1"><p dir="ltr" className="break-all">{session.label}</p><p>{session.current ? "این دستگاه · " : ""}{session.active ? "فعال" : "پایان‌یافته"} · آخرین فعالیت: {date(session.last_seen_at)}</p><p>پایان اعتبار: {date(session.expires_at)}</p></div>
        {session.active ? <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void perform("revoke-session", { session_id: session.id })}>خروج از دستگاه</Button> : null}
      </div>)}
    </CardContent></Card>
    <Card><CardHeader><CardTitle>دسترسی‌های مؤثر من</CardTitle></CardHeader><CardContent>
      <div className="grid gap-2 sm:grid-cols-2">{initial.permissions.map((permission) => <p key={permission} className="rounded-md bg-muted p-2 text-xs">{permissionLabels[permission] ?? permission}</p>)}</div>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>رویدادهای امنیتی اخیر</CardTitle></CardHeader><CardContent>
      {initial.events.length ? initial.events.map((event) => <div key={event.id} className="flex flex-wrap justify-between gap-4 border-b py-2 text-xs"><span>{eventLabels[event.action] ?? event.action}</span><time>{date(event.created_at)}</time></div>) : <p className="text-sm text-muted-foreground">رویدادی ثبت نشده است.</p>}
    </CardContent></Card>
  </div>;
}
