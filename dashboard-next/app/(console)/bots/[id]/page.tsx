import Link from "next/link";
import { notFound } from "next/navigation";
import { KeyRound, ShieldAlert, ShieldCheck, Settings2 } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { BotCatalogAccessPanel } from "@/components/blocks/bot-catalog-access-panel";
import { BotReceiverPanel } from "@/components/blocks/bot-receiver-panel";
import { BotCommercePanel } from "@/components/blocks/bot-commerce-panel";
import { BotRelayRoutesPanel } from "@/components/blocks/bot-relay-routes-panel";
import type { BotCatalogRuleList } from "@/lib/bot-catalog-acl";
import type { BotRelaySnapshot, RelayWorkersSnapshot } from "@/lib/relay-pool";
import type { BotCommercePolicy, BotPaymentList } from "@/lib/store-commerce";
type CatalogAuditRow = {
  object_type: "product" | "category";
  object_id: number;
  old_effect: string;
  new_effect: string;
  actor_id: number;
  created_at: string | null;
};
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import {
  type BotRegistryDetail, type BotReceiverSnapshot,
  botPlatformLabel, botRuntimeLabel,
} from "@/lib/bot-registry";
import {
  changeBotState, revokeBotCredential, saveBotDetails,
  stageBotCredential, verifyBotCredential,
} from "@/app/(console)/bots/[id]/actions";

type Params = Promise<{ id: string }>;
type Query = Promise<{
  saved?: string; error?: string; acl_saved?: string;
  relay_saved?: string; relay_error?: string;
  commerce_saved?: string; commerce_error?: string;
  acl_error?: string; acl_q?: string;
  acl_kind?: string; acl_page?: string;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const errors: Record<string, string> = {
  validation: "فیلدها را بررسی کنید؛ دلیل توقف باید حداقل ۸ نویسه داشته باشد.",
  reauth: "برای این عملیات باید در «حساب من» هویت خود را دوباره تأیید کنید.",
  bot_runtime_not_ready: "ابتدا Token و Receiver مستقل این بات را تأیید کنید.",
  invalid_receiver_mode: "نوع دریافت پیام معتبر نیست.",
  receiver_worker_unavailable: "Lease یا سرویس Runtime چندباتی در دسترس نیست.",
  receiver_lease_lost: "مالکیت Receiver قطع شده است؛ وضعیت سرور را بررسی کنید.",
  multibot_runtime_disabled: "Runtime چندباتی از تنظیمات سرور غیرفعال است.",
  bot_credential_not_verified: "Token بات هنوز با getMe تأیید نشده است.",
  receiver_change_in_progress: "این Receiver در حال تغییر یا نیازمند بررسی است.",
  webhook_url_invalid: "آدرس عمومی HTTPS مربوط به Webhook پیکربندی نشده است.",
  webhook_owned_elsewhere: "Webhook این بات در مقصد دیگری ثبت شده؛ انتقال خودکار انجام نمی‌شود.",
  receiver_needs_review: "نتیجهٔ تغییر Receiver مشخص نیست؛ بررسی دستی ضروری است.",
  invalid_operation_state: "وضعیت فعلی بات برای عملیات مجاز نیست.",
  configuration_changed: "نسخهٔ تنظیمات تغییر کرده است؛ صفحه را دوباره بارگذاری کنید.",
  duplicate_provider_bot: "این حساب بات قبلاً در Registry یک بات دیگر ثبت شده است.",
  duplicate_bot_credential: "این Token قبلاً برای بات دیگری یا بات قدیمی ثبت شده است.",
  bot_identity_mismatch: "هویت Provider با بات ثبت‌شده مطابقت ندارد.",
  invalid_bot_token_format: "ساختار Token با نوع پیام‌رسان انتخاب‌شده سازگار نیست.",
  invalid_support_url: "آدرس پشتیبانی باید HTTPS عمومی و بدون نام کاربری یا رمز باشد.",
  invalid_credential_state: "نسخهٔ Token انتخاب‌شده دیگر برای تأیید یا تغییر معتبر نیست.",
  bot_state_reason_required: "برای توقف یا غیرفعال‌سازی دلیل حداقل ۸ نویسه‌ای وارد کنید.",
  bot_state_unchanged: "وضعیت بات با مقدار فعلی یکسان است.",
  provider_state_unavailable: "getMe در دسترس نبود؛ شبکه یا Token بات را بررسی کنید.",
  bot_secret_key_unavailable: "کلید رمزنگاری محرمانهٔ سرور موجود نیست.",
  bot_secret_unreadable: "Credential قابل رمزگشایی نیست؛ تنظیمات Secret را بررسی کنید.",
  legacy_bot_credential_locked: "Token بات قدیمی از Deployment مدیریت می‌شود و از این پنل تغییر نمی‌کند.",
  mfa_enrollment_required: "ابتدا MFA حساب مدیر را فعال کنید.",
  bot_credential_stage_requires_draft: "فقط بات Draft می‌تواند Token جدید ثبت کند.",
  permission_denied: "حساب فعلی اجازهٔ این عملیات را ندارد.",
  save: "عملیات ثبت نشد. اتصال Backend، سطح دسترسی و وضعیت بات را بررسی کنید.",
};
const date = (value: string | null) =>
  value ? new Date(value).toLocaleString("fa-IR") : "ثبت نشده";

/** Server-render a scoped bot console; never expose a token or Worker key. */
export default async function BotDetailPage({
  params, searchParams,
}: { params: Params; searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const { id } = await params;
  if (!UUID.test(id)) notFound();

  const query = await searchParams;
  const aclKind = query.acl_kind === "category" ? "category" : "product";
  const aclQ = (query.acl_q ?? "").trim().slice(0, 100);
  const aclPage = Math.min(
    100000, Math.max(1, Number.parseInt(query.acl_page ?? "1", 10) || 1),
  );
  const aclSearch = new URLSearchParams({
    kind: aclKind, q: aclQ, page: String(aclPage), page_size: "20",
  });
  const [
    detail, members, acl, aclAudit, receiver, workers, routes,
    commercePolicy, paymentAccounts,
  ] = await Promise.all([
    adminFetch<BotRegistryDetail>(`/bot-registry/${id}`),
    adminFetch<{ id: number; username: string; is_active: boolean }[]>("/staff"),
    adminFetch<BotCatalogRuleList>(`/bot-catalog/bots/${id}?${aclSearch}`),
    adminFetch<{ items: CatalogAuditRow[] }>(
      `/bot-catalog/bots/${id}/audit?page=1`,
    ),
    adminFetch<BotReceiverSnapshot>(`/bot-registry/${id}/receiver`),
    adminFetch<RelayWorkersSnapshot>("/relay-workers"),
    adminFetch<BotRelaySnapshot>(`/bot-registry/${id}/relay-routes`),
    adminFetch<BotCommercePolicy>(`/bot-registry/${id}/commerce`),
    adminFetch<BotPaymentList>(`/bot-registry/${id}/payment-accounts`),
  ]);
  const { bot, health, events, state_events } = detail;
  const legacy = bot.runtime_owner === "legacy";
  const pending = bot.credentials.find(item => item.state === "staged");
  const active = bot.operations.desired_state === "active";
  const receiverActive = receiver.configured && receiver.state === "active";
  const mayChangeState = legacy || (receiverActive && health.runtime_ready);
  return <div className="space-y-6">
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm"><Link href="/bots">بازگشت به بات‌ها</Link></Button>
      <Button asChild variant="outline" size="sm"><Link href="/bot-connections">زیرساخت اتصال</Link></Button>
      <Button asChild variant="outline" size="sm"><Link href="/account">تأیید مجدد هویت</Link></Button>
    </div>
    <PageHeading title={bot.name} description={`شناسهٔ داخلی: ${bot.slug} · ${botPlatformLabel(bot.platform)} · نسخهٔ تنظیمات ${bot.version}`} />
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      {query.saved === "verified" ? "getMe با Provider واقعی موفق بود؛ این به معنای فعال‌شدن Runtime نیست." :
        query.saved === "staged" ? "Token رمزنگاری و به حالت Staged ثبت شد؛ بات همچنان خاموش است." :
        query.saved === "state" ? "وضعیت فروش جدید بات ذخیره شد؛ Receiver و رسیدهای تسویه تغییر نکردند." :
        query.saved === "receiver_staged" ? "Receiver فقط Stage شد و هنوز Provider تغییری نکرده است." :
        query.saved === "receiver_active" ? "فعال‌سازی Receiver ثبت شد؛ برای وضعیت فعلی، گزارش سلامت را بررسی کنید." :
        "تغییرات بات ثبت شد."}
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{errors[query.error] ?? errors.save}</p> : null}

    <div className="grid gap-3 sm:grid-cols-3">
      <Card><CardContent className="space-y-2 pt-5">
        <p className="text-xs text-muted-foreground">وضعیت جاری</p>
        <Badge tone={active && (legacy || receiverActive) ? "success" : "neutral"}>{botRuntimeLabel(bot)}</Badge>
        <p className="text-xs leading-6 text-muted-foreground">
          {legacy ? "گیت فروش مستقل فعال است؛ رویدادهای تسویهٔ قدیمی ادامه دارند." :
            receiverActive ? "Receiver اختصاصی در Registry فعال ثبت شده است." :
            "این بات هنوز Receiver فعال ندارد و فروش آن خاموش است."}
        </p>
      </CardContent></Card>
      <Card><CardContent className="space-y-2 pt-5">
        <p className="text-xs text-muted-foreground">هویت تأییدشدهٔ Provider</p>
        <p dir="ltr" className="break-all font-semibold">{bot.provider_bot_id ?? "هنوز بررسی نشده"}</p>
        <p dir="ltr" className="text-xs text-muted-foreground">{bot.provider_username ? `@${bot.provider_username}` : "—"}</p>
        <p className="text-xs text-muted-foreground">{date(bot.verified_at)}</p>
      </CardContent></Card>
      <Card><CardContent className="space-y-2 pt-5">
        <p className="text-xs text-muted-foreground">Receiver</p>
        <p className="font-semibold">{legacy
          ? (health.receiver_status.includes("paused") ? "Legacy Receiver — فروش متوقف" : "Legacy Receiver")
          : receiverActive ? `فعال — ${receiver.mode === "polling" ? "Polling" : "Webhook"}`
          : receiver.configured ? `در انتظار: ${receiver.state}` : "هنوز راه‌اندازی نشده"}</p>
        <p className="text-xs text-muted-foreground">آخرین Update مشاهده‌شده: {date(health.received_last_at)}</p>
      </CardContent></Card>
    </div>

    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="size-5" /> مشخصات و پیام‌ها</CardTitle></CardHeader>
        <CardContent>
          <form action={saveBotDetails} className="space-y-4">
            <input type="hidden" name="id" value={bot.id} />
            <input type="hidden" name="expected_version" value={bot.version} />
            <label className="block space-y-2 text-sm">نام بات
              <Input name="name" defaultValue={bot.name} maxLength={160} required />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-2 text-sm">مسئول بات
                <select name="owner_staff_id" defaultValue={bot.operations.owner_staff_id ?? ""}
                  className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="">تعیین نشده</option>
                  {members.filter(item => item.is_active).map(item =>
                    <option key={item.id} value={item.id}>{item.username}</option>)}
                </select>
              </label>
              <label className="block space-y-2 text-sm">محیط اجرایی (برچسب)
                <select name="environment" defaultValue={bot.operations.environment}
                  className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="codespaces">Codespaces</option>
                  <option value="staging">Staging</option>
                  <option value="production">Production</option>
                </select>
              </label>
            </div>
            <label className="block space-y-2 text-sm">پیام خوش‌آمد اختصاصی
              <Textarea name="welcome_message" rows={3} maxLength={4096}
                defaultValue={bot.operations.welcome_message ?? ""}
                placeholder="خالی = استفاده از متن عمومی فروشگاه" />
            </label>
            <label className="block space-y-2 text-sm">پیام Maintenance
              <Textarea name="maintenance_message" rows={3} maxLength={4096}
                defaultValue={bot.operations.maintenance_message ?? ""}
                placeholder="خالی = متن پیش‌فرض نگهداری" />
            </label>
            <label className="block space-y-2 text-sm">لینک پشتیبانی HTTPS
              <Input name="support_url" type="url" dir="ltr"
                defaultValue={bot.operations.support_url ?? ""} maxLength={500}
                placeholder="https://example.com/support" />
            </label>
            <p className="text-xs leading-6 text-muted-foreground">
              تنظیمات پیام خوش‌آمد و پشتیبانی برای دو بات Legacy اکنون اعمال می‌شوند.
              برای بات‌های Draft این مقادیر تا اتصال Runtime محفوظ می‌مانند.
            </p>
            <Button type="submit">ذخیرهٔ مشخصات این بات</Button>
          </form>
        </CardContent>
      </Card>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-5" /> وضعیت و روشن/خاموش‌کردن</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {mayChangeState ? <>
            <p className="text-sm leading-7">این کنترل فقط فروش و پیام‌های عادی بات منتخب را تغییر می‌دهد. در حالت توقف، Webhook یا getUpdates حذف نمی‌شود تا رسید پرداخت‌های قبلی همچنان پردازش شود.</p>
            <form action={changeBotState} className="space-y-4">
              <input type="hidden" name="id" value={bot.id} />
              <input type="hidden" name="expected_version" value={bot.version} />
              <label className="block space-y-2 text-sm">وضعیت هدف
                <select name="state" defaultValue={bot.operations.desired_state}
                  className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="active">روشن — فروش و پیام عادی</option>
                  <option value="maintenance">Maintenance — پاسخ نگهداری</option>
                  <option value="paused">Paused — توقف موقت فروش و Broadcast</option>
                  <option value="disabled">Disabled — بدون پاسخ عادی؛ حفظ تسویه</option>
                </select>
              </label>
              <label className="block space-y-2 text-sm">دلیل تغییر (برای توقف یا غیرفعال‌سازی اجباری)
                <Textarea name="reason" rows={3} maxLength={500}
                  placeholder="دلیل حداقل هشت نویسه‌ای برای توقف…" />
              </label>
              <Button type="submit" variant="outline">ثبت وضعیت با Audit</Button>
            </form>
            {bot.operations.reason ? <p className="text-xs text-muted-foreground">دلیل ثبت‌شده: {bot.operations.reason}</p> : null}
          </> : <div className="space-y-4">
            <p className="flex items-start gap-2 rounded-lg border p-3 text-sm leading-7">
              <ShieldAlert className="mt-1 size-5 shrink-0 text-amber-600" />
              این بات هنوز Receiver فعال ندارد؛ تا تأیید هویت و اتصال مستقل، فروش جدید آن مسدود است.
            </p>
            <p className="text-xs leading-7 text-muted-foreground">از بخش Receiver مستقل در پایین، ابتدا Stage و سپس پس از تأیید محیط اجرا و MFA اقدام به فعال‌سازی کنید.</p>
          </div>}
        </CardContent>
      </Card>
    </div>

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-5" /> Credential و تأیید هویت بات</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm leading-7">توکن هیچ‌گاه از Backend خوانده یا در صفحه نمایش داده نمی‌شود. فقط نسخه، وضعیت و زمان تأیید قابل مشاهده است. تأیید getMe صرفاً احراز هویت بات است و آن را روشن نمی‌کند.</p>
        {legacy ? <div className="rounded-lg border bg-muted/40 p-3 text-sm">
          Token بات قدیمی فقط از Secretهای Deployment خوانده می‌شود. برای امنیت اتصال‌های فعال، تعویض Token آن در این فاز مجاز نیست.
        </div> : bot.status === "draft" ? <form action={stageBotCredential} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <input type="hidden" name="id" value={bot.id} />
          <label className="block space-y-2 text-sm">Token جدید برای بات Draft
            <Input type="password" name="token" dir="ltr" minLength={24} maxLength={512}
              autoComplete="new-password" required placeholder="رمز بات تنها یک بار وارد می‌شود" />
          </label>
          <Button type="submit">ثبت امن Token</Button>
        </form> : <p className="text-sm text-muted-foreground">Credential این بات فعال است و از این فرم تعویض نمی‌شود.</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[660px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">نسخه</th><th className="p-3">منبع / وضعیت</th>
              <th className="p-3">تأیید با getMe</th><th className="p-3">عملیات</th>
            </tr></thead>
            <tbody>{bot.credentials.map(credential => <tr key={credential.version} className="border-b">
              <td className="p-3">{credential.version}</td>
              <td className="p-3">{credential.source === "environment" ? "Deployment" : "Encrypted"} · {credential.state}</td>
              <td className="p-3 text-xs">{credential.verified_at ? `تأییدشده: ${date(credential.verified_at)}` : "هنوز تأیید نشده"}</td>
              <td className="flex flex-wrap gap-2 p-3">
                {(credential.state === "staged" || (legacy && credential.state === "active"))
                  ? <form action={verifyBotCredential}>
                    <input type="hidden" name="id" value={bot.id} />
                    <input type="hidden" name="version" value={credential.version} />
                    <Button size="sm" type="submit" variant="outline">تست getMe</Button>
                  </form> : null}
                {credential.state === "staged" ? <form action={revokeBotCredential}>
                  <input type="hidden" name="id" value={bot.id} />
                  <input type="hidden" name="version" value={credential.version} />
                  <Button size="sm" type="submit" variant="outline">لغو Token</Button>
                </form> : null}
              </td>
            </tr>)}</tbody>
          </table>
          {!bot.credentials.length ? <p className="py-5 text-center text-sm text-muted-foreground">برای این بات هنوز هیچ Credential ثبت نشده است.</p> : null}
        </div>
        {pending && !legacy ? <p className="text-xs text-muted-foreground">نسخهٔ Staged: {pending.version} · آخرین تأیید: {date(pending.verified_at)}</p> : null}
      </CardContent>
    </Card>

    <BotReceiverPanel bot={bot} receiver={receiver} pending={pending} />
    {query.commerce_saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      مجوزهای مستقل این بات ثبت شدند؛ موجودی و پرداخت‌های سابق تغییر نکردند.
    </p> : null}
    {query.commerce_error ? <p role="alert"
      className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      ذخیرهٔ تنظیمات مالی بات انجام نشد؛ نسخه، مجوزها و MFA را بررسی کنید.
    </p> : null}
    <BotCommercePanel bot={bot} policy={commercePolicy}
      paymentAccounts={paymentAccounts} />
    {query.relay_saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تغییر مسیر Relay ثبت شد؛ هیچ پیام یا پرداختی از این عملیات صادر نمی‌شود.
    </p> : null}
    {query.relay_error ? <p role="alert"
      className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      عملیات Relay انجام نشد: {query.relay_error === "reauth"
        ? "احراز هویت دوباره لازم است" : query.relay_error}
    </p> : null}
    <BotRelayRoutesPanel bot={bot} workers={workers} routes={routes} />

    {query.acl_saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      قانون دسترسی بات به محصولات/دسته‌بندی‌ها با ثبت Audit ذخیره شد.
    </p> : null}
    {query.acl_error ? <p role="alert"
      className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
      {query.acl_error === "reauth" ? "برای تغییر ACL در حساب من هویت خود را دوباره تأیید کنید." :
        query.acl_error === "version" ? "نسخهٔ تنظیمات تغییر کرده است؛ صفحه را تازه‌سازی کنید." :
        query.acl_error === "validation" ? "حداقل یک مورد را انتخاب کنید و قانون را بررسی کنید." :
        query.acl_error === "permission" ? "مجوز تغییر دسترسی محصولات را ندارید." :
        "ذخیرهٔ دسترسی انجام نشد."}
    </p> : null}
    <BotCatalogAccessPanel
      botId={bot.id} version={bot.version} data={acl} query={aclQ}
    />
    <Card><CardHeader><CardTitle>تاریخچهٔ قوانین دسترسی</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {aclAudit.items.slice(0, 12).map((row, index) =>
          <div key={`${row.object_type}-${row.object_id}-${row.created_at}-${index}`}
            className="flex flex-wrap justify-between gap-2 border-b py-2 text-xs">
            <span>
              {row.object_type === "product" ? "محصول" : "دسته‌بندی"} #{row.object_id}:
              {" "}{row.old_effect} ← {row.new_effect}
            </span>
            <span className="text-muted-foreground">
              مدیر #{row.actor_id} · {date(row.created_at)}
            </span>
          </div>)}
        {!aclAudit.items.length ? <p className="text-sm text-muted-foreground">
          هنوز تغییر مستقیمی برای این بات ثبت نشده است.
        </p> : null}
      </CardContent>
    </Card>

    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>سلامت و پردازش پیام‌ها</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>وضعیت API Provider: <strong>در این نما درخواست زنده زده نشده</strong></p>
          <p>آخرین Update: {date(health.received_last_at)}</p>
          <p>درحال پردازش در یک ساعت: {health.processing_last_hour}</p>
          <p>نیازمند بررسی در یک ساعت: {health.needs_review_last_hour}</p>
          <p>Runtime آماده: <strong>{health.runtime_ready ? (legacy ? "Legacy" : "Registry — Receiver فعال") : "هنوز متصل نشده"}</strong></p>
          <p className="text-xs leading-7 text-muted-foreground">تعداد پیام کم به معنای Offline بودن بات نیست. برای تأیید هویت زنده از getMe در بخش Credential استفاده کنید.</p>
        </CardContent>
      </Card>
      <Card><CardHeader><CardTitle>تاریخچهٔ Audit بات</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {state_events.map(entry => <div key={entry.id} className="rounded-lg border p-3 text-xs">
            <p className="font-semibold">{entry.previous_state} ← {entry.next_state}</p>
            <p className="mt-1 text-muted-foreground">{date(entry.created_at)} · مدیر #{entry.actor_id}</p>
            {entry.reason ? <p className="mt-2 text-muted-foreground">دلیل: {entry.reason}</p> : null}
          </div>)}
          {events.map(entry => <div key={entry.id} className="border-b py-2 text-xs">
            <p className="font-medium">{entry.action}</p>
            <p className="mt-1 text-muted-foreground">{date(entry.created_at)} · مدیر #{entry.actor_id ?? "سیستم"} {entry.credential_version ? `· نسخه ${entry.credential_version}` : ""}</p>
          </div>)}
          {!events.length ? <p className="text-sm text-muted-foreground">هنوز رویدادی ثبت نشده است.</p> : null}
        </CardContent>
      </Card>
    </div>
  </div>;
}
