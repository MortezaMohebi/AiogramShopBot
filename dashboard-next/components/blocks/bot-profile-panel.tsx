import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  saveBotProfile, verifyBotProfile,
} from "@/app/(console)/bot-connections/actions";

export interface BotProfile {
  platform: "telegram" | "bale";
  display_name: string;
  owner_staff_id: number | null;
  environment: "codespaces" | "staging" | "production";
  provider_bot_id: string | null;
  provider_username: string | null;
  maintenance_enabled: boolean;
  request_timeout_seconds: number;
  poll_timeout_seconds: number;
  allowed_updates: string[];
  verified_at: string | null;
  receiver_mode: string;
  receiver_version: number;
  transport_active: string;
  credential_configured: boolean;
}
export interface BotHealth {
  platform: string;
  credential_configured: boolean;
  provider_api_health: string;
  receiver_mode: string;
  receiver_last_verified_at: string | null;
  processing_last_seen_at: string | null;
  processing_inflight_last_hour: number;
  processing_needs_review_last_hour: number;
  receiver_pending_changes: number;
  broadcast_worker_last_seen_at: string | null;
}
const UPDATES: Array<[string, string]> = [
  ["message", "پیام‌ها"],
  ["callback_query", "دکمه‌های Inline"],
  ["pre_checkout_query", "درخواست تأیید پرداخت"],
  ["edited_message", "ویرایش پیام"],
  ["my_chat_member", "تغییر وضعیت عضویت ربات"],
];
const time = (value: string | null) =>
  value ? new Date(value).toLocaleString("fa-IR") : "هنوز ثبت نشده";

/** Explicit bot profile settings; deployed tokens never reach the browser. */
export function BotProfilePanel({
  initial, health, staff,
}: {
  initial: BotProfile[];
  health: BotHealth[];
  staff: { id: number; username: string }[];
}) {
  return <div className="grid gap-5 xl:grid-cols-2">
    {initial.map(profile => {
      const status = health.find(item => item.platform === profile.platform);
      return <Card key={profile.platform}>
        <CardHeader><CardTitle>{profile.platform === "telegram" ? "ربات تلگرام" : "ربات بله"}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 rounded-lg bg-muted/40 p-3 text-xs">
            <p>شناسهٔ ربات در پیام‌رسان: <strong dir="ltr">{profile.provider_bot_id || "هنوز تأیید نشده"}</strong></p>
            <p>نام کاربری ربات: <strong dir="ltr">{profile.provider_username || "—"}</strong></p>
            <p>روش دریافت: <strong>{profile.receiver_mode}</strong> · نسخه: {profile.receiver_version}</p>
            <p>مسیر خروجی فعال: <strong dir="ltr">{profile.transport_active}</strong></p>
            <p>Token سرور: {profile.credential_configured ? "تنظیم شده" : "تنظیم نشده"}</p>
            <p>آخرین تأیید هویت: {time(profile.verified_at)}</p>
          </div>
          <form action={verifyBotProfile} className="space-y-2">
            <input type="hidden" name="platform" value={profile.platform} />
            <Button type="submit" variant="outline">تأیید getMe با توکن فعلی</Button>
          </form>
          <form action={saveBotProfile} className="space-y-4">
            <input type="hidden" name="platform" value={profile.platform} />
            <label className="block space-y-2 text-sm">نام نمایشی ربات
              <Input name="display_name" defaultValue={profile.display_name} maxLength={120} />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-2 text-sm">مسئول
                <select name="owner_staff_id" defaultValue={profile.owner_staff_id ?? ""} className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="">تعیین نشده</option>
                  {staff.map(item => <option key={item.id} value={item.id}>{item.username}</option>)}
                </select>
              </label>
              <label className="block space-y-2 text-sm">محیط (برچسب مدیریتی)
                <select name="environment" defaultValue={profile.environment} className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="codespaces">Codespaces</option>
                  <option value="staging">Staging</option>
                  <option value="production">Production</option>
                </select>
              </label>
              <label className="block space-y-2 text-sm">مهلت درخواست (ثانیه)
                <Input name="request_timeout_seconds" type="number" min={5} max={60} defaultValue={profile.request_timeout_seconds} />
              </label>
              <label className="block space-y-2 text-sm">مهلت Polling (ثانیه)
                <Input name="poll_timeout_seconds" type="number" min={0} max={30} defaultValue={profile.poll_timeout_seconds} />
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="maintenance_enabled" defaultChecked={profile.maintenance_enabled} className="size-4 accent-primary" />
              حالت تعمیرات برای پیام‌های جدید فروشگاه
            </label>
            <fieldset className="space-y-2 rounded-lg border p-3">
              <legend className="px-2 text-sm font-medium">نوع رویدادهای مجاز</legend>
              <p className="text-xs text-muted-foreground">اگر هیچ گزینه‌ای انتخاب نشود، فیلتر محدودکننده‌ای اعمال نمی‌شود. تنظیمات Polling از دور بعدی اعمال می‌شوند.</p>
              {UPDATES.map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs">
                <input type="checkbox" name="allowed_updates" value={key} defaultChecked={profile.allowed_updates.includes(key)} className="size-4 accent-primary" />
                {label}
              </label>)}
            </fieldset>
            <Button type="submit">ذخیره تنظیمات این ربات</Button>
          </form>
          {status ? <div className="space-y-2 rounded-lg border p-4 text-xs">
            <strong>وضعیت اتصال و پردازش پیام‌ها</strong>
            <p>API Provider: {status.provider_api_health === "not_probed" ? "در این گزارش درخواست زنده زده نشده" : status.provider_api_health}</p>
            <p>Receiver: {status.receiver_mode} · آخرین تأیید: {time(status.receiver_last_verified_at)}</p>
            <p>آخرین Update: {time(status.processing_last_seen_at)}</p>
            <p>در حال پردازش (یک ساعت): {status.processing_inflight_last_hour}</p>
            <p>نیازمند بررسی (یک ساعت): {status.processing_needs_review_last_hour}</p>
            <p>تغییرات دریافتِ تعیین‌تکلیف‌نشده: {status.receiver_pending_changes}</p>
            <p>آخرین Heartbeat پخش همگانی: {time(status.broadcast_worker_last_seen_at)}</p>
          </div> : null}
        </CardContent>
      </Card>;
    })}
    <p className="text-xs leading-7 text-muted-foreground xl:col-span-2">
      توکن‌ها همچنان در Secretهای Deployment نگهداری می‌شوند و از این پنل قابل مشاهده نیستند.
      مسیر Telegram Direct / Proxy / Cloudflare Worker از بخش بعدی همین صفحه با مرحلهٔ ثبت، تست و تأیید هویت قابل تغییر است.
      <Link href="/account" className="ms-2 underline">تأیید مجدد هویت در حساب من</Link>
    </p>
  </div>;
}
