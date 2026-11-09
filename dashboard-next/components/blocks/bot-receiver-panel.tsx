import Link from "next/link";
import { BotWebhookUrl } from "@/components/blocks/bot-webhook-url";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type {
  BotCredentialStatus, BotReceiverSnapshot, BotRecord,
} from "@/lib/bot-registry";
import {
  activateBotReceiver, checkBotReceiverLocal, stageBotReceiver,
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
  const stagedWebhook = isDraft && receiver.state === "staged" && receiver.mode === "webhook";

  return <Card id="bot-receiver" className="scroll-mt-6">
    <CardHeader><CardTitle>دریافت پیام و فعال‌سازی ربات</CardTitle></CardHeader>
    <CardContent className="space-y-5 text-sm">
      {isDraft && receiver.state !== "active" ? <p className="leading-7">
        برای وب‌هوک، اول مسیر را در همین برنامه بسازید و آزمایش کنید. بعد از انتشار مسیر با HTTPS، دریافت پیام را فعال کنید.
      </p> : null}
      <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2">
        <p>وضعیت: <strong>{receiver.configured ? ({ staged: "ثبت اولیه", applying: "در حال اعمال تغییر", active: "فعال", paused: "متوقف", disabled: "غیرفعال", needs_review: "نتیجه نامشخص؛ نیازمند بررسی" } as const)[receiver.state] : "راه‌اندازی نشده"}</strong></p>
        <p>نوع دریافت: <strong>{receiver.mode === "webhook" ? "Webhook" : receiver.mode === "polling" ? "Polling" : "—"}</strong></p>
        <p>نسخه: <strong>{receiver.version ?? "—"}</strong></p>
        <p>Offset بعدی: <strong>{receiver.next_update_id ?? "—"}</strong></p>
        <p>Runtime: <strong>{receiver.runtime_enabled ? "مجاز به اجرا" : "متوقف"}</strong></p>
        <p>Lease اجرایی: <strong>{receiver.worker_ready ? "در دسترس" : "در دسترس نیست"}</strong></p>
        {receiver.last_error_code ? <p className="sm:col-span-2">
          {receiver.last_error_code === "webhook_owned_elsewhere"
            ? "این توکن هنوز به اتصال قبلی در پیام‌رسان وصل است. آزمون مسیر محلی جداگانه در دسترس است."
            : <>کد آخرین خطا: <strong>{receiver.last_error_code}</strong></>}
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
          آماده‌سازی روش دریافت
        </Button>
      </form> : null}

      {isDraft && !pending?.verified_at ?
        <p className="text-muted-foreground">
          برای ثبت روش دریافت، ابتدا Token را با getMe تأیید کنید.
        </p> : null}

      {stagedWebhook ? <form action={checkBotReceiverLocal} className="space-y-3 rounded-lg border p-4">
        <p className="leading-7">
          مسیر وب‌هوک در همین برنامه ساخته شده است. برای این آزمون به تونل یا اتصال پیام‌رسان نیازی نیست.
        </p>
        <input type="hidden" name="id" value={bot.id} />
        <input type="hidden" name="expected_version" value={receiver.version ?? ""} />
        <Button type="submit" variant="outline">آزمون وب‌هوک محلی</Button>
      </form> : null}

      {canActivate ? <form action={activateBotReceiver} className="space-y-4 rounded-lg border p-4">
        <p className="leading-7">
          {stagedWebhook
            ? "پس از انتشار مسیر با HTTPS، آن را در پیام‌رسان ثبت کنید. برنامه ابتدا دسترسی محلی و اینترنتی را بررسی می‌کند."
            : "دریافت پیام با Polling برای همین ربات فعال می‌شود."}
        </p>
        <input type="hidden" name="id" value={bot.id} />
        <input type="hidden" name="expected_version" value={receiver.version ?? ""} />
        <Button type="submit">{stagedWebhook ? "ثبت وب‌هوک در پیام‌رسان" : "فعال‌سازی دریافت پیام"}</Button>
      </form> : null}

      {isDraft && receiver.state === "staged" && !canActivate ?
        <p className="rounded-lg border p-3 leading-7">
          برای فعال‌سازی، سرویس دریافت پیام باید آماده و توکن ربات تأیید شده باشد. <Link className="underline" href="/services">وضعیت سرویس‌ها را بررسی کنید</Link>.
        </p> : null}

      {ambiguous ? <p role="alert" className="rounded-lg border p-3 leading-7">
        نتیجهٔ آخرین تغییر اتصال مشخص نیست؛ اتصال قرنطینه شده و تا
        بررسی دستی، انتقال یا تلاش مجدد مجاز نیست.
      </p> : null}

      {receiver.state === "active" && receiver.mode === "webhook" ?
        <BotWebhookUrl key={`${bot.id}:${receiver.version}`} botId={bot.id} /> : null}

      {receiver.state === "active" ? <p className="leading-7">
        دریافت پیام فعال است؛ توقف فروش را از کنترل وضعیت ربات انجام دهید.
        رسید پرداخت‌های قبلی و درخواست‌های بازگشت وجه باید همچنان رسیدگی شوند.
      </p> : null}
    </CardContent>
  </Card>;
}
