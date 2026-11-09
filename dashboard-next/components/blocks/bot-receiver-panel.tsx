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

  const state = receiver.configured ? ({
    staged: "آمادهٔ فعال‌سازی", applying: "در حال اتصال", active: "متصل",
    paused: "متوقف", disabled: "غیرفعال", needs_review: "نیازمند بررسی",
  } as const)[receiver.state] : "راه‌اندازی نشده";
  return <Card id="bot-receiver" className="scroll-mt-24">
    <CardHeader><CardTitle>دریافت پیام</CardTitle></CardHeader>
    <CardContent className="space-y-5 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <strong>{state}</strong>
        {receiver.mode && <span className="text-muted-foreground">{receiver.mode === "webhook" ? "وب‌هوک" : "دریافت دوره‌ای"}</span>}
      </div>
      {receiver.last_error_code === "webhook_owned_elsewhere" && <p role="alert">
        این ربات هنوز به اتصال قبلی در پیام‌رسان وصل است. برای انتقال، ابتدا اتصال قبلی را قطع کنید.
      </p>}

      {canStage ? <form action={stageBotReceiver} className="flex flex-wrap items-end gap-3">
        <input type="hidden" name="id" value={bot.id} />
        <label className="block space-y-2">روش دریافت پیام
          <select name="mode" defaultValue={receiver.mode ?? "webhook"}
            className="block h-10 min-w-44 rounded-md border bg-background px-3">
            <option value="webhook">وب‌هوک (HTTPS)</option>
            <option value="polling">دریافت دوره‌ای</option>
          </select>
        </label>
        <Button type="submit" variant="outline" disabled={!pending?.verified_at}>
          آماده‌سازی روش دریافت
        </Button>
      </form> : null}

      {isDraft && !pending?.verified_at ?
        <p className="text-muted-foreground">
          ابتدا توکن ربات را تأیید کنید.
        </p> : null}

      {stagedWebhook ? <form action={checkBotReceiverLocal} className="space-y-3 rounded-lg border p-4">
        <input type="hidden" name="id" value={bot.id} />
        <input type="hidden" name="expected_version" value={receiver.version ?? ""} />
        <Button type="submit" variant="outline">آزمون وب‌هوک محلی</Button>
      </form> : null}

      {canActivate ? <form action={activateBotReceiver} className="space-y-4 rounded-lg border p-4">
        <p className="leading-7">
          {stagedWebhook
            ? "پس از انتشار مسیر با HTTPS، آن را در پیام‌رسان ثبت کنید. برنامه ابتدا دسترسی محلی و اینترنتی را بررسی می‌کند."
            : "دریافت دوره‌ای پیام برای همین ربات فعال می‌شود."}
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

      {receiver.configured && <details className="text-xs text-muted-foreground">
        <summary className="w-fit cursor-pointer hover:underline">اطلاعات اتصال برای پشتیبانی</summary>
        <dl className="mt-2 grid max-w-lg grid-cols-2 gap-2">
          <dt>نسخه</dt><dd>{receiver.version ?? "—"}</dd>
          <dt>شناسهٔ پیام بعدی</dt><dd>{receiver.next_update_id ?? "—"}</dd>
          <dt>سرویس دریافت</dt><dd>{receiver.runtime_enabled ? "روشن" : "متوقف"}</dd>
          <dt>پردازشگر</dt><dd>{receiver.worker_ready ? "در دسترس" : "در دسترس نیست"}</dd>
          {receiver.last_error_code && <><dt>آخرین خطا</dt><dd><bdi>{receiver.last_error_code}</bdi></dd></>}
        </dl>
      </details>}
    </CardContent>
  </Card>;
}
