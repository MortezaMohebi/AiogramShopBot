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
  if (bot.runtime_owner === "legacy") return null;
  const isDraft = bot.status === "draft";
  const canStage = isDraft && (!receiver.configured || receiver.state === "staged");
  const canActivate = isDraft && receiver.state === "staged" &&
    receiver.runtime_enabled && receiver.worker_ready && Boolean(pending?.verified_at);
  const ambiguous = receiver.state === "needs_review" || receiver.state === "applying";

  return <Card>
    <CardHeader><CardTitle>Receiver مستقل و فعال‌سازی بات</CardTitle></CardHeader>
    <CardContent className="space-y-5 text-sm">
      <p className="leading-7">
        Webhook یا Polling هر بات مستقل است. Secret و آدرس محرمانهٔ Receiver هیچ‌گاه
        به مرورگر برنمی‌گردد؛ مرحلهٔ Stage هیچ درخواست خارجی ارسال نمی‌کند.
      </p>
      <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2">
        <p>وضعیت: <strong>{receiver.configured ? receiver.state : "نصب نشده"}</strong></p>
        <p>نوع دریافت: <strong>{receiver.mode ?? "—"}</strong></p>
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
          Stage بدون تغییر Provider
        </Button>
      </form> : null}

      {isDraft && !pending?.verified_at ?
        <p className="text-muted-foreground">
          برای Stage ابتدا Token را با getMe تأیید کنید.
        </p> : null}

      {canActivate ? <form action={activateBotReceiver} className="space-y-4 rounded-lg border p-4">
        <p className="leading-7">
          این اقدام Webhook یا Polling واقعی را برای همین بات فعال می‌کند. پس از
          Timeout نامشخص، فراخوانی خودکار تکرار نمی‌شود و بررسی دستی لازم است.
        </p>
        <input type="hidden" name="id" value={bot.id} />
        <input type="hidden" name="expected_version" value={receiver.version ?? ""} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-2">رمز فعلی مدیر
            <Input type="password" name="current_password" required minLength={1}
              maxLength={256} autoComplete="current-password" />
          </label>
          <label className="block space-y-2">کد شش‌رقمی MFA
            <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
              maxLength={6} autoComplete="one-time-code" required />
          </label>
        </div>
        <Button type="submit">فعال‌سازی واقعی Receiver همین بات</Button>
      </form> : null}

      {isDraft && receiver.state === "staged" && !canActivate ?
        <p className="rounded-lg border p-3 leading-7">
          فعال‌سازی قفل است؛ Runtime و Lease باید در سرور فعال باشند و Token
          همین بات باید تأیید شده باشد. Stage‌کردن به‌تنهایی باعث فروش نمی‌شود.
        </p> : null}

      {ambiguous ? <p role="alert" className="rounded-lg border p-3 leading-7">
        آخرین تغییر Provider نتیجهٔ قطعی ندارد؛ Receiver قرنطینه شده و تا
        بررسی دستی، انتقال یا تلاش مجدد مجاز نیست.
      </p> : null}

      {receiver.state === "active" ? <p className="leading-7">
        Receiver فعال است؛ توقف فروش را از کنترل وضعیت بات انجام دهید.
        رسید پرداخت‌های قبلی و درخواست‌های بازگشت وجه باید همچنان رسیدگی شوند.
      </p> : null}
    </CardContent>
  </Card>;
}
