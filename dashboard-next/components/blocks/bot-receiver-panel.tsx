import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  BotCredentialStatus, BotReceiverSnapshot, BotRecord,
} from "@/lib/bot-registry";
import {
  activateBotReceiver, stageBotReceiver,
} from "@/app/(console)/bots/[id]/actions";

interface Props {
  bot: BotRecord;
  receiver: BotReceiverSnapshot;
  pending: BotCredentialStatus | undefined;
}

/** Explicitly separate staging a receiver from changing the live provider. */
export function BotReceiverPanel({ bot, receiver, pending }: Props) {
  const isDraft = bot.status === "draft";
  const canStage = isDraft && (!receiver.configured || receiver.state === "staged");
  const canActivate = isDraft && receiver.state === "staged" &&
    receiver.runtime_enabled && receiver.worker_ready && Boolean(pending?.verified_at);
  const ambiguous = receiver.state === "needs_review" || receiver.state === "applying";

  return <Card>
    <CardHeader><CardTitle>دریافت پیام و فعال‌سازی ربات</CardTitle></CardHeader>
    <CardContent className="space-y-5 text-sm">
      <p className="leading-7">
        روش دریافت پیام هر ربات را جداگانه تنظیم کنید. ثبت اولیه، اتصال را فعال نمی‌کند.
      </p>
      <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2">
        <p>وضعیت: <strong>{receiver.configured ? ({ staged: "ثبت اولیه", applying: "در حال اعمال تغییر", active: "فعال", paused: "متوقف", disabled: "غیرفعال", needs_review: "نتیجه نامشخص؛ نیازمند بررسی" } as const)[receiver.state] : "راه‌اندازی نشده"}</strong></p>
        <p>نوع دریافت: <strong>{receiver.mode === "webhook" ? "Webhook" : receiver.mode === "polling" ? "Polling" : "—"}</strong></p>
        <p>نسخه: <strong>{receiver.version ?? "—"}</strong></p>
        <p>Offset بعدی: <strong>{receiver.next_update_id ?? "—"}</strong></p>
        <p>Runtime: <strong>{receiver.runtime_enabled ? "در سرور مجاز" : "در سرور غیرفعال"}</strong></p>
        <p>Lease اجرایی: <strong>{receiver.worker_ready ? "در دسترس" : "در دسترس نیست"}</strong></p>
        {receiver.last_error_code ? <p className="sm:col-span-2">
          کد آخرین خطا: <strong>{receiver.last_error_code}</strong>
        </p> : null}
      </div>

      {canStage ? <form action={stageBotReceiver} className="flex flex-wrap items-end gap-3">
        <input type="hidden" name="id" value={bot.id} />
        <label className="block space-y-2">روش دریافت پیام
          <select name="mode" defaultValue={receiver.mode ?? "webhook"}
            className="block h-10 min-w-44 rounded-md border bg-background px-3">
            <option value="webhook">Webhook (HTTPS)</option>
            <option value="polling">Polling</option>
          </select>
        </label>
        <Button type="submit" variant="outline" disabled={!pending?.verified_at}>
          ثبت اولیهٔ روش دریافت
        </Button>
      </form> : null}

      {isDraft && !pending?.verified_at ?
        <p className="text-muted-foreground">
          برای ثبت روش دریافت، ابتدا Token را با getMe تأیید کنید.
        </p> : null}

      {canActivate ? <form action={activateBotReceiver} className="space-y-4 rounded-lg border p-4">
        <p className="leading-7">
          این اقدام Webhook یا Polling واقعی را برای همین ربات فعال می‌کند. اگر نتیجهٔ فعال‌سازی مشخص نشد، پیش از تلاش دوباره وضعیت را بررسی کنید.
        </p>
        <input type="hidden" name="id" value={bot.id} />
        <input type="hidden" name="expected_version" value={receiver.version ?? ""} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-2">رمز فعلی مدیر
            <Input type="password" name="current_password" required minLength={1}
              maxLength={256} autoComplete="current-password" />
          </label>
          <label className="block space-y-2">کد شش‌رقمی MFA
            <Input name="second_factor" dir="ltr" inputMode="numeric" pattern="[0-9]{6}"
              maxLength={6} autoComplete="one-time-code" required />
          </label>
        </div>
        <Button type="submit">فعال‌سازی دریافت پیام</Button>
      </form> : null}

      {isDraft && receiver.state === "staged" && !canActivate ?
        <p className="rounded-lg border p-3 leading-7">
          فعال‌سازی در دسترس نیست؛ سرویس دریافت پیام باید در سرور آماده و Token همین ربات تأیید شده باشد. ثبت اولیه، فروش را فعال نمی‌کند.
        </p> : null}

      {ambiguous ? <p role="alert" className="rounded-lg border p-3 leading-7">
        نتیجهٔ آخرین تغییر اتصال مشخص نیست؛ اتصال قرنطینه شده و تا
        بررسی دستی، انتقال یا تلاش مجدد مجاز نیست.
      </p> : null}

      {receiver.state === "active" ? <p className="leading-7">
        دریافت پیام فعال است؛ توقف فروش را از کنترل وضعیت ربات انجام دهید.
        رسید پرداخت‌های قبلی و درخواست‌های بازگشت وجه باید همچنان رسیدگی شوند.
      </p> : null}
    </CardContent>
  </Card>;
}
