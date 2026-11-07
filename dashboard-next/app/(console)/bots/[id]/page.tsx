import Link from "next/link";
import { notFound } from "next/navigation";
import { KeyRound, ShieldAlert, ShieldCheck, Settings2 } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { BotCatalogAccessPanel } from "@/components/blocks/bot-catalog-access-panel";
import { BotReceiverPanel } from "@/components/blocks/bot-receiver-panel";
import { BotCommercePanel } from "@/components/blocks/bot-commerce-panel";
import { CustomerExperiencePolicyPanel } from "@/components/blocks/customer-experience-policy-panel";
import type { CustomerMenuPolicy, CheckoutPolicy } from "@/lib/customer-experience";
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
  ux_saved?: string; ux_error?: string;
  acl_error?: string; acl_q?: string;
  acl_kind?: string; acl_page?: string;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const errors: Record<string, string> = {
  validation: "فیلدها را بررسی کنید؛ دلیل توقف باید حداقل ۸ نویسه داشته باشد.",
  reauth: "برای این عملیات باید در «حساب من» هویت خود را دوباره تأیید کنید.",
  bot_runtime_not_ready: "ابتدا Token ربات را تأیید و دریافت پیام را تنظیم کنید.",
  invalid_receiver_mode: "نوع دریافت پیام معتبر نیست.",
  receiver_worker_unavailable: "سرویس دریافت پیام در دسترس نیست؛ وضعیت سرور را بررسی کنید.",
  receiver_lease_lost: "اتصال سرویس دریافت پیام قطع شده است؛ وضعیت سرور را بررسی کنید.",
  multibot_runtime_disabled: "سرویس چندرباتی در سرور غیرفعال است.",
  bot_credential_not_verified: "Token ربات هنوز با getMe تأیید نشده است.",
  receiver_change_in_progress: "دریافت پیام در حال تغییر یا نیازمند بررسی است.",
  webhook_url_invalid: "آدرس عمومی HTTPS مربوط به Webhook پیکربندی نشده است.",
  webhook_owned_elsewhere: "Webhook این ربات در مقصد دیگری ثبت شده؛ انتقال خودکار انجام نمی‌شود.",
  receiver_needs_review: "نتیجهٔ تغییر روش دریافت پیام مشخص نیست؛ بررسی دستی لازم است.",
  invalid_operation_state: "وضعیت فعلی ربات برای عملیات مجاز نیست.",
  configuration_changed: "نسخهٔ تنظیمات تغییر کرده است؛ صفحه را دوباره بارگذاری کنید.",
  duplicate_provider_bot: "این حساب پیام‌رسان قبلاً برای ربات دیگری ثبت شده است.",
  duplicate_bot_credential: "این Token قبلاً برای ربات دیگری یا ربات قدیمی ثبت شده است.",
  bot_identity_mismatch: "شناسهٔ پیام‌رسان با ربات ثبت‌شده مطابقت ندارد.",
  invalid_bot_token_format: "ساختار Token با نوع پیام‌رسان انتخاب‌شده سازگار نیست.",
  invalid_support_url: "آدرس پشتیبانی باید HTTPS عمومی و بدون نام کاربری یا رمز باشد.",
  invalid_credential_state: "نسخهٔ Token انتخاب‌شده دیگر برای تأیید یا تغییر معتبر نیست.",
  bot_state_reason_required: "برای توقف یا غیرفعال‌سازی دلیل حداقل ۸ نویسه‌ای وارد کنید.",
  bot_state_unchanged: "وضعیت ربات با مقدار فعلی یکسان است.",
  provider_state_unavailable: "getMe در دسترس نبود؛ شبکه یا Token ربات را بررسی کنید.",
  bot_secret_key_unavailable: "کلید رمزنگاری محرمانهٔ سرور موجود نیست.",
  bot_secret_unreadable: "Token ذخیره‌شده قابل خواندن نیست؛ تنظیمات کلید محرمانهٔ سرور را بررسی کنید.",
  legacy_bot_credential_locked: "Token ربات قدیمی در تنظیمات سرور مدیریت می‌شود و از این پنل تغییر نمی‌کند.",
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
    commercePolicy, paymentAccounts, customerMenu, checkoutPolicy,
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
    adminFetch<CustomerMenuPolicy>(`/bot-registry/${id}/customer-menu`),
    adminFetch<CheckoutPolicy>(`/bot-registry/${id}/checkout-policy`),
  ]);
  const { bot, health, events, state_events } = detail;
  const legacy = bot.runtime_owner === "legacy";
  const pending = bot.credentials.find(item => item.state === "staged");
  const active = bot.operations.desired_state === "active";
  const receiverActive = receiver.configured && receiver.state === "active";
  const mayChangeState = legacy || (receiverActive && health.runtime_ready);
  return <div className="space-y-6">
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm"><Link href="/bots">بازگشت به ربات‌ها</Link></Button>
      <Button asChild variant="outline" size="sm"><Link href="/bot-connections">زیرساخت اتصال</Link></Button>
      <Button asChild variant="outline" size="sm"><Link href="/account">تأیید مجدد هویت</Link></Button>
    </div>
    <PageHeading title={bot.name} description={`شناسهٔ داخلی: ${bot.slug} · ${botPlatformLabel(bot.platform)} · نسخهٔ تنظیمات ${bot.version}`} />
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      {query.saved === "verified" ? "هویت ربات با getMe تأیید شد؛ تأیید هویت، وضعیت فعال‌بودن ربات را تغییر نمی‌دهد." :
        query.saved === "staged" ? "Token برای بررسی ثبت شد؛ ربات همچنان غیرفعال است." :
        query.saved === "state" ? "وضعیت فروش ربات ذخیره شد؛ دریافت پیام و رسیدهای تسویه تغییر نکردند." :
        query.saved === "receiver_staged" ? "روش دریافت پیام ثبت شد؛ اتصال هنوز تغییر نکرده است." :
        query.saved === "receiver_active" ? "درخواست فعال‌سازی دریافت پیام ثبت شد؛ وضعیت فعلی را در گزارش سلامت بررسی کنید." :
        "تغییرات ربات ثبت شد."}
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{errors[query.error] ?? errors.save}</p> : null}

    <div className="grid gap-3 sm:grid-cols-3">
      <Card><CardContent className="space-y-2 pt-5">
        <p className="text-xs text-muted-foreground">وضعیت جاری</p>
        <Badge tone={active && (legacy || receiverActive) ? "success" : "neutral"}>{botRuntimeLabel(bot)}</Badge>
        <p className="text-xs leading-6 text-muted-foreground">
          {legacy ? "کنترل فروش فعال است؛ رسیدگی به تسویه‌های قبلی ادامه دارد." :
            receiverActive ? "دریافت پیام این ربات فعال است." :
            "دریافت پیام این ربات فعال نیست و فروش آن متوقف است."}
        </p>
      </CardContent></Card>
      <Card><CardContent className="space-y-2 pt-5">
        <p className="text-xs text-muted-foreground">شناسهٔ تأییدشده در پیام‌رسان</p>
        <p dir="ltr" className="break-all font-semibold">{bot.provider_bot_id ?? "هنوز بررسی نشده"}</p>
        <p dir="ltr" className="text-xs text-muted-foreground">{bot.provider_username ? `@${bot.provider_username}` : "—"}</p>
        <p className="text-xs text-muted-foreground">{date(bot.verified_at)}</p>
      </CardContent></Card>
      <Card><CardContent className="space-y-2 pt-5">
        <p className="text-xs text-muted-foreground">دریافت پیام</p>
        <p className="font-semibold">{legacy
          ? (health.receiver_status.includes("paused") ? "اتصال قدیمی — فروش متوقف" : "اتصال قدیمی")
          : receiverActive ? `فعال — ${receiver.mode === "polling" ? "Polling" : "Webhook"}`
          : receiver.configured ? ({ staged: "ثبت اولیه", applying: "در حال اعمال تغییر", active: "فعال", paused: "متوقف", disabled: "غیرفعال", needs_review: "نتیجه نامشخص؛ نیازمند بررسی" } as const)[receiver.state] : "هنوز راه‌اندازی نشده"}</p>
        <p className="text-xs text-muted-foreground">آخرین Update مشاهده‌شده: {date(health.received_last_at)}</p>
      </CardContent></Card>
    </div>

    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="size-5" /> مشخصات و پیام‌ها</CardTitle></CardHeader>
        <CardContent>
          <form action={saveBotDetails} className="space-y-4">
            <input type="hidden" name="id" value={bot.id} />
            <input type="hidden" name="expected_version" value={bot.version} />
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
              تنظیمات پیام خوش‌آمد و پشتیبانی برای دو ربات Legacy اکنون اعمال می‌شوند.
              برای ربات‌های پیش‌نویس، این متن‌ها پس از فعال‌سازی استفاده می‌شوند.
            </p>
            <Button type="submit">ذخیرهٔ مشخصات این ربات</Button>
          </form>
        </CardContent>
      </Card>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-5" /> وضعیت و روشن/خاموش‌کردن</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {mayChangeState ? <>
            <p className="text-sm leading-7">این کنترل فقط فروش و پیام‌های عادی ربات منتخب را تغییر می‌دهد. در حالت توقف، Webhook یا getUpdates حذف نمی‌شود تا رسید پرداخت‌های قبلی همچنان پردازش شود.</p>
            <form action={changeBotState} className="space-y-4">
              <input type="hidden" name="id" value={bot.id} />
              <input type="hidden" name="expected_version" value={bot.version} />
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
              <Button type="submit" variant="outline">ذخیره وضعیت فروش</Button>
            </form>
            {bot.operations.reason ? <p className="text-xs text-muted-foreground">دلیل ثبت‌شده: {bot.operations.reason}</p> : null}
          </> : <div className="space-y-4">
            <p className="flex items-start gap-2 rounded-lg border p-3 text-sm leading-7">
              <ShieldAlert className="mt-1 size-5 shrink-0 text-amber-600" />
              دریافت پیام این ربات فعال نیست؛ فروش جدید تا تأیید هویت و اتصال متوقف می‌ماند.
            </p>
            <p className="text-xs leading-7 text-muted-foreground">در بخش «دریافت پیام و فعال‌سازی ربات»، روش دریافت را ثبت و سپس آن را با MFA فعال کنید.</p>
          </div>}
        </CardContent>
      </Card>
    </div>

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-5" /> Token و تأیید هویت ربات</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm leading-7">Token ذخیره‌شده قابل نمایش نیست. تأیید getMe فقط هویت ربات را بررسی می‌کند و آن را فعال نمی‌کند.</p>
        {legacy ? <div className="rounded-lg border bg-muted/40 p-3 text-sm">
          Token ربات قدیمی در تنظیمات سرور مدیریت می‌شود و از این صفحه قابل تغییر نیست.
        </div> : bot.status === "draft" ? <form action={stageBotCredential} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <input type="hidden" name="id" value={bot.id} />
          <label className="block space-y-2 text-sm">Token ربات پیش‌نویس
            <Input type="password" name="token" dir="ltr" minLength={24} maxLength={512}
              autoComplete="new-password" required placeholder="رمز ربات تنها یک بار وارد می‌شود" />
          </label>
          <Button type="submit">ثبت Token</Button>
        </form> : <p className="text-sm text-muted-foreground">Token این ربات فعال است و از این فرم قابل تعویض نیست.</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[660px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">نسخه</th><th className="p-3">منبع / وضعیت</th>
              <th className="p-3">تأیید با getMe</th><th className="p-3">عملیات</th>
            </tr></thead>
            <tbody>{bot.credentials.map(credential => <tr key={credential.version} className="border-b">
              <td className="p-3">{credential.version}</td>
              <td className="p-3">{credential.source === "environment" ? "تنظیمات سرور" : "ثبت‌شده در پنل"} · {({ staged: "در انتظار تأیید", active: "فعال", revoked: "لغوشده", retiring: "در حال جایگزینی" } as Record<string, string>)[credential.state] ?? credential.state}</td>
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
          {!bot.credentials.length ? <p className="py-5 text-center text-sm text-muted-foreground">هنوز Token ثبت نشده است.</p> : null}
        </div>
        {pending && !legacy ? <p className="text-xs text-muted-foreground">نسخهٔ در انتظار تأیید: {pending.version} · آخرین تأیید: {date(pending.verified_at)}</p> : null}
      </CardContent>
    </Card>

    <BotReceiverPanel bot={bot} receiver={receiver} pending={pending} />
    {query.commerce_saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      مجوزهای مستقل این ربات ثبت شدند؛ موجودی و پرداخت‌های سابق تغییر نکردند.
    </p> : null}
    {query.commerce_error ? <p role="alert"
      className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      ذخیرهٔ تنظیمات مالی ربات انجام نشد؛ نسخه، مجوزها و MFA را بررسی کنید.
    </p> : null}
    <BotCommercePanel bot={bot} policy={commercePolicy}
      paymentAccounts={paymentAccounts} />
    {query.ux_saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تنظیمات منو و خرید ربات ذخیره شد.
    </p> : null}
    {query.ux_error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      تنظیمات خرید ذخیره نشد؛ دسترسی فروشگاه، نسخهٔ تنظیمات و MFA را بررسی کنید.
    </p> : null}
    <CustomerExperiencePolicyPanel
      scope="bot" id={bot.id} menu={customerMenu} checkout={checkoutPolicy}
    />
    {query.relay_saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تغییر مسیر Relay ثبت شد.
    </p> : null}
    {query.relay_error ? <p role="alert"
      className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      عملیات Relay انجام نشد: {query.relay_error === "reauth"
        ? "در حساب من هویت خود را دوباره تأیید کنید." : "مسیر، نسخهٔ تنظیمات و دسترسی خود را بررسی کنید."}
    </p> : null}
    <BotRelayRoutesPanel bot={bot} workers={workers} routes={routes} />

    {query.acl_saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
      دسترسی ربات به محصولات و دسته‌بندی‌ها ذخیره شد.
    </p> : null}
    {query.acl_error ? <p role="alert"
      className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
      {query.acl_error === "reauth" ? "برای تغییر دسترسی محصولات، در حساب من هویت خود را دوباره تأیید کنید." :
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
          هنوز تغییر مستقیمی برای این ربات ثبت نشده است.
        </p> : null}
      </CardContent>
    </Card>

    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>سلامت و پردازش پیام‌ها</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>وضعیت API پیام‌رسان: <strong>در این نما درخواست زنده زده نشده</strong></p>
          <p>آخرین پیام دریافتی: {date(health.received_last_at)}</p>
          <p>درحال پردازش در یک ساعت: {health.processing_last_hour}</p>
          <p>نیازمند بررسی در یک ساعت: {health.needs_review_last_hour}</p>
          <p>آمادگی دریافت پیام: <strong>{health.runtime_ready ? (legacy ? "اتصال قدیمی" : "فعال") : "هنوز متصل نشده"}</strong></p>
          <p className="text-xs leading-7 text-muted-foreground">تعداد پیام کم به معنای قطع اتصال ربات نیست. برای تأیید هویت زنده از getMe در بخش Token استفاده کنید.</p>
        </CardContent>
      </Card>
      <Card><CardHeader><CardTitle>تاریخچهٔ تغییرات ربات</CardTitle></CardHeader>
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
          {!events.length && !state_events.length ? <p className="text-sm text-muted-foreground">هنوز رویدادی ثبت نشده است.</p> : null}
        </CardContent>
      </Card>
    </div>
  </div>;
}
