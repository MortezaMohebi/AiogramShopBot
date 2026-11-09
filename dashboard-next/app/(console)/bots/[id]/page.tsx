import { DraftForm } from "@/components/blocks/draft-form";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { ConsumeBotResult } from "./consume-bot-result";
import { VerifyBotSubmitButton } from "./verify-bot-submit-button";
import { PasswordActionForm } from "@/components/blocks/password-action-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { BotCatalogAccessPanel } from "@/components/blocks/bot-catalog-access-panel";
import { BotConfigVersionField, BotConfigVersionProvider } from "@/components/blocks/bot-config-version";
import { BotReceiverPanel } from "@/components/blocks/bot-receiver-panel";
import { BotChangeHistory } from "@/components/blocks/bot-change-history";
import { BotCommercePanel } from "@/components/blocks/bot-commerce-panel";
import { CustomerExperiencePolicyPanel } from "@/components/blocks/customer-experience-policy-panel";
import type { CustomerMenuPolicy, CheckoutPolicy } from "@/lib/customer-experience";
import { BotRelayRoutesPanel } from "@/components/blocks/bot-relay-routes-panel";
import { botCatalogQuery, catalogListParams, type BotCatalogRuleList, type CatalogAuditRow } from "@/lib/bot-catalog-acl";
import type { BotRelaySnapshot, RelayWorkersSnapshot } from "@/lib/relay-pool";
import type { BotCommercePolicy, BotPaymentList } from "@/lib/store-commerce";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import {
  type BotRegistryDetail, type BotReceiverSnapshot,
  botCredentialLabel, botPlatformLabel, botRuntimeLabel,
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
  ux_saved?: string; ux_error?: string;
  acl_error?: string; acl_q?: string;
  acl_kind?: string; acl_page?: string; acl_effect?: string;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const errors: Record<string, string> = {
  validation: "فیلدها را بررسی کنید؛ دلیل توقف باید حداقل ۸ نویسه داشته باشد.",
  reauth: "برای این عملیات باید هویت خود را دوباره تأیید کنید.",
  bot_runtime_not_ready: "ابتدا Token ربات را تأیید و دریافت پیام را تنظیم کنید.",
  invalid_receiver_mode: "نوع دریافت پیام معتبر نیست.",
  receiver_worker_unavailable: "سرویس دریافت پیام در دسترس نیست؛ وضعیت سرور را بررسی کنید.",
  receiver_lease_lost: "اتصال سرویس دریافت پیام قطع شده است؛ وضعیت سرور را بررسی کنید.",
  multibot_runtime_disabled: "سرویس چندرباتی در سرور غیرفعال است.",
  bot_credential_not_verified: "Token ربات هنوز با getMe تأیید نشده است.",
  receiver_change_in_progress: "دریافت پیام در حال تغییر یا نیازمند بررسی است.",
  webhook_url_invalid: "برای ثبت در پیام‌رسان، مسیر وب‌هوک را با یک آدرس عمومی HTTPS در دسترس قرار دهید.",
  webhook_local_unreachable: "آزمون مسیر وب‌هوک در این سرور موفق نبود. سرویس دریافت پیام را بررسی کنید.",
  webhook_public_unreachable: "مسیر وب‌هوک از اینترنت پاسخ معتبر نداد. آدرس HTTPS و تونل را بررسی کنید.",
  webhook_owned_elsewhere: "پیام‌رسان هنوز پیام‌های این توکن را به اتصال قبلی می‌فرستد. اگر قصد جابه‌جایی دارید، ابتدا اتصال قبلی را از همان سرویس قطع کنید.",
  receiver_needs_review: "نتیجهٔ تغییر روش دریافت پیام مشخص نیست؛ بررسی دستی لازم است.",
  invalid_operation_state: "وضعیت فعلی ربات برای عملیات مجاز نیست.",
  configuration_changed: "نسخهٔ تنظیمات تغییر کرده است؛ صفحه را دوباره بارگذاری کنید.",
  duplicate_provider_bot: "این حساب پیام‌رسان قبلاً برای ربات دیگری ثبت شده است.",
  duplicate_bot_credential: "این Token قبلاً برای ربات دیگری ثبت شده است.",
  bot_identity_mismatch: "شناسهٔ پیام‌رسان با ربات ثبت‌شده مطابقت ندارد.",
  invalid_bot_token_format: "ساختار Token با نوع پیام‌رسان انتخاب‌شده سازگار نیست.",
  invalid_support_url: "آدرس پشتیبانی باید HTTPS عمومی و بدون نام کاربری یا رمز باشد.",
  invalid_credential_state: "نسخهٔ Token انتخاب‌شده دیگر برای تأیید یا تغییر معتبر نیست.",
  bot_state_reason_required: "برای توقف یا غیرفعال‌سازی دلیل حداقل ۸ نویسه‌ای وارد کنید.",
  bot_state_unchanged: "وضعیت ربات با مقدار فعلی یکسان است.",
  provider_state_unavailable: "بررسی وضعیت ربات در پیام‌رسان کامل نشد. اتصال را بررسی کنید و دوباره تلاش کنید.",
  bot_secret_key_unavailable: "کلید رمزنگاری محرمانهٔ سرور موجود نیست.",
  bot_secret_unreadable: "Token ذخیره‌شده قابل خواندن نیست؛ تنظیمات کلید محرمانهٔ سرور را بررسی کنید.",
  mfa_enrollment_required: "ابتدا MFA حساب مدیر را فعال کنید.",
  bot_credential_stage_requires_draft: "فقط ربات پیش‌نویس می‌تواند Token جدید ثبت کند.",
  permission_denied: "حساب فعلی اجازهٔ این عملیات را ندارد.",
  save: "تغییرات ثبت نشد. اتصال، دسترسی حساب و وضعیت ربات را بررسی کنید.",
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
  const aclQuery = botCatalogQuery.read({
    get(name) {
      const value = query[name as keyof typeof query];
      return typeof value === "string" ? value : null;
    },
  });
  const aclSearch = catalogListParams(aclQuery);
  const detail = await adminFetch<BotRegistryDetail>(`/bot-registry/${id}`);
  const telegram = detail.bot.platform === "telegram";
  const [
    members, acl, aclAudit, receiver, workers, routes,
    commercePolicy, paymentAccounts, customerMenu, checkoutPolicy,
  ] = await Promise.all([
    adminFetch<{ id: number; username: string; is_active: boolean }[]>("/staff"),
    adminFetch<BotCatalogRuleList>(`/bot-catalog/bots/${id}?${aclSearch}`),
    adminFetch<{ items: CatalogAuditRow[] }>(
      `/bot-catalog/bots/${id}/audit?page=1`,
    ),
    adminFetch<BotReceiverSnapshot>(`/bot-registry/${id}/receiver`),
    telegram ? adminFetch<RelayWorkersSnapshot>(`/bot-registry/${id}/relay-workers`) : null,
    telegram ? adminFetch<BotRelaySnapshot>(`/bot-registry/${id}/relay-routes`) : null,
    adminFetch<BotCommercePolicy>(`/bot-registry/${id}/commerce`),
    adminFetch<BotPaymentList>(`/bot-registry/${id}/payment-accounts`),
    adminFetch<CustomerMenuPolicy>(`/bot-registry/${id}/customer-menu`),
    adminFetch<CheckoutPolicy>(`/bot-registry/${id}/checkout-policy`),
  ]);
  const { bot, health, events, state_events } = detail;
  const pending = bot.credentials.find(item => item.state === "staged");
  const receiverActive = receiver.configured && receiver.state === "active";
  const mayChangeState = receiverActive && health.runtime_ready;
  return <BotConfigVersionProvider key={bot.id} initialVersion={bot.version}>
  <div className="space-y-6">
    <Suspense fallback={null}><ConsumeBotResult /></Suspense>
    <PageHeading title={bot.name} action={<Button asChild variant="outline" size="sm"><Link href="/bots">بازگشت به فهرست</Link></Button>} />
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Badge tone="neutral">{botPlatformLabel(bot.platform)}</Badge>
      <Badge tone={receiverActive && bot.operations.desired_state === "active" ? "success" : "neutral"}>{botRuntimeLabel(bot)}</Badge>
      {bot.provider_username && <bdi dir="ltr">@{bot.provider_username}</bdi>}
      <span className="text-muted-foreground">{receiverActive ? "دریافت پیام فعال" : "دریافت پیام آماده نیست"}</span>
      {bot.platform === "telegram" && <Link href="#bot-relays" className="text-primary underline">مسیرهای Relay</Link>}
    </div>
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      {query.saved === "verified" ? "هویت ربات با getMe تأیید شد. مرحلهٔ بعد تنظیم و فعال‌سازی دریافت پیام است." :
        query.saved === "staged" ? "Token برای بررسی ثبت شد؛ ربات همچنان غیرفعال است." :
        query.saved === "state" ? "وضعیت فروش ربات ذخیره شد؛ دریافت پیام و رسیدهای تسویه تغییر نکردند." :
        query.saved === "receiver_staged" ? "روش دریافت پیام آماده شد." :
        query.saved === "receiver_local" ? "مسیر وب‌هوک در همین سرور پاسخ داد. حالا می‌توانید آن را با HTTPS منتشر کنید." :
        query.saved === "receiver_active" ? "درخواست فعال‌سازی دریافت پیام ثبت شد؛ وضعیت فعلی را در گزارش سلامت بررسی کنید." :
        "تغییرات ربات ثبت شد."}
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{errors[query.error] ?? errors.save}</p> : null}

    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>مشخصات و پیام‌ها</CardTitle></CardHeader>
        <CardContent>
          <DraftForm saveAction={saveBotDetails} className="space-y-4">
            <input type="hidden" name="id" value={bot.id} />
            <BotConfigVersionField />
            <label className="block space-y-2 text-sm">نام ربات
              <Input name="name" defaultValue={bot.name} maxLength={160} required />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-2 text-sm">مسئول ربات
                <select name="owner_staff_id" defaultValue={bot.operations.owner_staff_id ?? ""}
                  className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="">تعیین نشده</option>
                  {members.filter(item => item.is_active).map(item =>
                    <option key={item.id} value={item.id}>{item.username}</option>)}
                </select>
              </label>
              <label className="block space-y-2 text-sm">محیط
                <select name="environment" defaultValue={bot.operations.environment}
                  className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="staging">آزمایشی</option>
                  <option value="production">عملیاتی</option>
                </select>
              </label>
            </div>
            <label className="block space-y-2 text-sm">پیام خوش‌آمد اختصاصی
              <Textarea name="welcome_message" rows={3} maxLength={4096}
                defaultValue={bot.operations.welcome_message ?? ""}
                placeholder="خالی = استفاده از متن عمومی فروشگاه" />
            </label>
            <label className="block space-y-2 text-sm">پیام تعمیرات
              <Textarea name="maintenance_message" rows={3} maxLength={4096}
                defaultValue={bot.operations.maintenance_message ?? ""}
                placeholder="خالی = متن پیش‌فرض نگهداری" />
            </label>
            <label className="block space-y-2 text-sm">لینک پشتیبانی HTTPS
              <Input name="support_url" type="url" dir="ltr"
                defaultValue={bot.operations.support_url ?? ""} maxLength={500}
                placeholder="https://example.com/support" />
            </label>
          </DraftForm>
        </CardContent>
      </Card>

      <Card><CardHeader><CardTitle>وضعیت فروش</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {mayChangeState ? <>
            <PasswordActionForm action={changeBotState} when="required" includePassword={false} className="space-y-4">
              <input type="hidden" name="id" value={bot.id} />
              <BotConfigVersionField />
              <label className="block space-y-2 text-sm">وضعیت هدف
                <select name="state" defaultValue={bot.operations.desired_state}
                  className="h-10 w-full rounded-md border bg-background px-3">
                  <option value="active">روشن — فروش و پیام عادی</option>
                  <option value="maintenance">تعمیرات — نمایش پیام نگهداری</option>
                  <option value="paused">متوقف — توقف فروش و ارسال همگانی</option>
                  <option value="disabled">غیرفعال — بدون پاسخ عادی؛ حفظ تسویه</option>
                </select>
              </label>
              <label className="block space-y-2 text-sm">دلیل تغییر (برای توقف یا غیرفعال‌سازی اجباری)
                <Textarea name="reason" rows={3} maxLength={500}
                  placeholder="دلیل حداقل هشت نویسه‌ای برای توقف…" />
              </label>
              <Button type="submit" variant="outline">اعمال وضعیت</Button>
            </PasswordActionForm>
            {bot.operations.reason ? <p className="text-xs text-muted-foreground">دلیل ثبت‌شده: {bot.operations.reason}</p> : null}
          </> : <p className="text-sm">برای شروع فروش، <Link href="#bot-receiver" className="text-primary underline">دریافت پیام را راه‌اندازی کنید</Link>.</p>}
        </CardContent>
      </Card>
    </div>

    <BotSettingsDisclosure title="توکن و هویت ربات" open={bot.status === "draft"}>
      <div className="space-y-4">
        {bot.status === "draft" ? <form action={stageBotCredential} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <input type="hidden" name="id" value={bot.id} />
          <label className="block space-y-2 text-sm">توکن ربات
            <Input type="password" name="token" dir="ltr" minLength={24} maxLength={512}
              autoComplete="new-password" required placeholder="رمز ربات تنها یک بار وارد می‌شود" />
          </label>
          <Button type="submit">ثبت توکن</Button>
        </form> : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[660px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">نسخه</th><th className="p-3">وضعیت</th>
              <th className="p-3">تأیید با getMe</th><th className="p-3">عملیات</th>
            </tr></thead>
            <tbody>{bot.credentials.map(credential => <tr key={credential.version} className="border-b">
              <td className="p-3">{credential.version}</td>
              <td className="p-3">{botCredentialLabel(credential)}</td>
              <td className="p-3 text-xs">{credential.verified_at ? `تأییدشده: ${date(credential.verified_at)}` : "هنوز تأیید نشده"}</td>
              <td className="flex flex-wrap gap-2 p-3">
                {credential.state === "staged"
                  ? <form action={verifyBotCredential}>
                    <input type="hidden" name="id" value={bot.id} />
                    <input type="hidden" name="version" value={credential.version} />
                    <VerifyBotSubmitButton verified={Boolean(credential.verified_at)} />
                  </form> : null}
                {credential.state === "staged" ? <PasswordActionForm action={revokeBotCredential} when="required" includePassword={false}>
                  <input type="hidden" name="id" value={bot.id} />
                  <input type="hidden" name="version" value={credential.version} />
                  <Button size="sm" type="submit" variant="outline">لغو توکن</Button>
                </PasswordActionForm> : null}
              </td>
            </tr>)}</tbody>
          </table>
          {!bot.credentials.length ? <p className="py-5 text-center text-sm text-muted-foreground">هنوز Token ثبت نشده است.</p> : null}
        </div>
        {pending?.verified_at ? <Button asChild size="sm" variant="outline">
          <Link href="#bot-receiver">تنظیم دریافت پیام</Link>
        </Button> : null}
      </div>
    </BotSettingsDisclosure>

    <BotReceiverPanel bot={bot} receiver={receiver} pending={pending} />
    {workers && routes && <BotRelayRoutesPanel bot={bot} workers={workers} routes={routes}
      error={query.relay_error} saved={query.relay_saved} />}
    <BotSettingsDisclosure title="پرداخت و فروش" open={Boolean(query.commerce_saved || query.commerce_error)}>
      {query.commerce_saved && <p role="status" className="mb-3 text-sm">تنظیمات پرداخت ربات ذخیره شد.</p>}
      {query.commerce_error && <p role="alert" className="mb-3 text-sm text-destructive">تنظیمات پرداخت ذخیره نشد. دسترسی و وضعیت فعلی را بررسی کنید.</p>}
      <BotCommercePanel bot={bot} policy={commercePolicy} paymentAccounts={paymentAccounts} />
    </BotSettingsDisclosure>
    <BotSettingsDisclosure title="منو و فرایند خرید" open={Boolean(query.ux_saved || query.ux_error)}>
      {query.ux_saved && <p role="status" className="mb-3 text-sm">تنظیمات خرید ربات ذخیره شد.</p>}
      {query.ux_error && <p role="alert" className="mb-3 text-sm text-destructive">تنظیمات خرید ذخیره نشد. دسترسی و نسخهٔ تنظیمات را بررسی کنید.</p>}
      <CustomerExperiencePolicyPanel scope="bot" id={bot.id} menu={customerMenu} checkout={checkoutPolicy} />
    </BotSettingsDisclosure>
    <BotSettingsDisclosure title="دسترسی به محصولات و دسته‌بندی‌ها" open={Boolean(query.acl_saved || query.acl_error || query.acl_q || query.acl_kind || query.acl_effect || query.acl_page)}>
    {query.acl_saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      دسترسی ربات به محصولات و دسته‌بندی‌ها ذخیره شد.
    </p> : null}
    {query.acl_error ? <p role="alert"
      className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
      {query.acl_error === "reauth" ? "برای تغییر دسترسی محصولات، هویت خود را در همین صفحه تأیید کنید." :
        query.acl_error === "version" ? "نسخهٔ تنظیمات تغییر کرده است؛ صفحه را تازه‌سازی کنید." :
        query.acl_error === "validation" ? "حداقل یک مورد را انتخاب کنید و قانون را بررسی کنید." :
        query.acl_error === "permission" ? "مجوز تغییر دسترسی محصولات را ندارید." :
        "ذخیرهٔ دسترسی انجام نشد."}
    </p> : null}
    <Suspense fallback={null}>
      <BotCatalogAccessPanel botId={bot.id} initialData={acl} initialQuery={aclQuery} initialAudit={aclAudit.items} />
    </Suspense>
    </BotSettingsDisclosure>

    <BotSettingsDisclosure title="سلامت و تاریخچه">
    <div className="grid items-start gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>سلامت و پردازش پیام‌ها</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>شناسهٔ ربات در پیام‌رسان: <bdi>{bot.provider_bot_id ?? "تأیید نشده"}</bdi></p>
          <p>آخرین پیام دریافتی: {date(health.received_last_at)}</p>
          <p>درحال پردازش در یک ساعت: {health.processing_last_hour}</p>
          <p>نیازمند بررسی در یک ساعت: {health.needs_review_last_hour}</p>
          <p>آمادگی دریافت پیام: <strong>{health.runtime_ready ? "فعال" : "هنوز متصل نشده"}</strong></p>
        </CardContent>
      </Card>
      <BotChangeHistory events={events} state_events={state_events} />
    </div>
    </BotSettingsDisclosure>
  </div></BotConfigVersionProvider>;
}

function BotSettingsDisclosure({ title, open, children }: { title: string; open?: boolean; children: ReactNode }) {
  return <details open={open || undefined} className="group rounded-xl border bg-card">
    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-5 py-3 font-medium [&::-webkit-details-marker]:hidden">
      {title}<ChevronDown aria-hidden className="size-4 shrink-0 group-open:rotate-180" />
    </summary>
    <div className="border-t p-4 sm:p-5">{children}</div>
  </details>;
}
