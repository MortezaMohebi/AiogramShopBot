import { randomUUID } from "node:crypto";
import { notFound } from "next/navigation";
import { adjustWallet, resolveRefund } from "@/app/(console)/finance/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { formatIrr, statusLabel } from "@/lib/utils";

type Wallet = { user_id: string; platform: string; balance_irr: string };
type Refund = {
  id: number; order_id: number; platform: string; provider: string;
  amount_irr: string; reason: string; status: string;
};
type Ledger = {
  id: number; platform: string; user_id: string; delta_irr: string;
  balance_after_irr: string; reason: string; actor: string; created_at: string;
};
type Capabilities = {
  wallet_adjustment_limit_irr: string; telegram_stars_refunds_enabled: boolean;
};
type Params = Promise<{ saved?: string; error?: string }>;

/** Financial actions never edit paid states directly or access Bale's wallet. */
export default async function FinancePage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "finance"].includes(staff.role)) notFound();
  const [wallets, refunds, ledger, capabilities, params] = await Promise.all([
    adminFetch<{items: Wallet[]; total: number}>("/wallets"),
    adminFetch<Refund[]>("/refunds"),
    adminFetch<Ledger[]>("/wallets/ledger"),
    adminFetch<Capabilities>("/capabilities"),
    searchParams,
  ]);
  const limit = BigInt(capabilities.wallet_adjustment_limit_irr);
  return (
    <div className="space-y-6">
      <PageHeading title="امور مالی" description="اعتبار داخلی فروشگاه مستقل از کیف پول بله است. تأیید پرداخت واقعی و بازپرداخت فقط توسط سرویس‌های مالی Python انجام می‌شود." />
      {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">عملیات مالی ثبت شد؛ برای رسید قطعی، وضعیت پرونده یا دفتر اعتبار را بررسی کنید.</p> : null}
      {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">درخواست انجام نشد. مبلغ، مدرک تأیید یا وضعیت پرونده را بررسی کنید؛ از تکرار بازپرداخت نامشخص خودداری کنید.</p> : null}
      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>حساب‌های اعتبار داخلی</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <p className="text-xs text-muted-foreground">{wallets.total} حساب · ۱۰۰ حساب اخیر</p>
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {wallets.items.map((item) => (
                <div key={item.platform + item.user_id} className="flex items-center justify-between gap-3 border-b border-border py-2 text-sm">
                  <span>{item.platform === "bale" ? "بله" : "تلگرام"} · <span dir="ltr">{item.user_id}</span></span>
                  <span>{formatIrr(item.balance_irr)}</span>
                </div>
              ))}
              {!wallets.items.length ? <p className="text-sm text-muted-foreground">حسابی ثبت نشده است.</p> : null}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>اصلاح اعتبار با سند</CardTitle></CardHeader>
          <CardContent>
            {limit > BigInt(0) ? (
              <form action={adjustWallet} className="space-y-3">
                <input type="hidden" name="operation_id" value={randomUUID()} />
                <p className="text-xs text-muted-foreground">سقف مجاز هر عملیات: {formatIrr(capabilities.wallet_adjustment_limit_irr)}. هر عملیات کلید مستقل و ثبت در Ledger دارد.</p>
                <label className="block space-y-1 text-sm">پیام‌رسان
                  <select name="platform" className="h-10 w-full rounded-md border border-input bg-background px-3">
                    <option value="bale">بله</option><option value="telegram">تلگرام</option>
                  </select>
                </label>
                <label className="block space-y-1 text-sm">شناسه عددی کاربر
                  <Input name="user_id" type="number" min={1} required />
                </label>
                <label className="block space-y-1 text-sm">نوع
                  <select name="direction" className="h-10 w-full rounded-md border border-input bg-background px-3">
                    <option value="credit">افزایش اعتبار</option><option value="debit">کاهش اعتبار</option>
                  </select>
                </label>
                <label className="block space-y-1 text-sm">مبلغ به ریال
                  <Input name="amount_irr" type="number" min={1} max={String(limit)} required />
                </label>
                <label className="block space-y-1 text-sm">شرح و سند (۱۲ تا ۲۰۰ نویسه)
                  <Textarea name="reason" minLength={12} maxLength={200} required rows={2} />
                </label>
                <label className="block space-y-1 text-sm">تأیید دستی
                  <Input name="confirmation" required dir="ltr" placeholder="CREDIT_CONFIRMED" />
                </label>
                <Button type="submit">ثبت تغییر در Ledger</Button>
              </form>
            ) : <p className="text-sm leading-7 text-muted-foreground">اصلاح دستی اعتبار به‌صورت پیش‌فرض غیرفعال است. سقف عملیات باید توسط تنظیمات امن سرور فعال شود.</p>}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>پرونده‌های بازپرداخت</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {refunds.map((refund) => (
            <div key={refund.id} className="grid gap-4 rounded-lg border border-border p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <div className="space-y-2 text-sm">
                <p className="font-semibold">سفارش #{refund.order_id} · پرونده #{refund.id}</p>
                <p>{refund.platform === "bale" ? "بله" : "تلگرام"} · {refund.provider} · {formatIrr(refund.amount_irr)}</p>
                <p className="break-words text-xs text-muted-foreground">{refund.reason}</p>
                <Badge tone={refund.status === "confirmed" ? "success" : "warning"}>{statusLabel(refund.status)}</Badge>
              </div>
              {["requested", "provider_pending"].includes(refund.status) ? (
                refund.provider === "telegram_stars" ? (
                  capabilities.telegram_stars_refunds_enabled && refund.status === "requested" ? (
                    <form action={resolveRefund} className="space-y-2">
                      <input type="hidden" name="case_id" value={refund.id} />
                      <input type="hidden" name="action" value="stars" />
                      <p className="text-xs text-muted-foreground">این دکمه تماس واقعی با API بازپرداخت Telegram Stars را اجرا می‌کند. در نتیجه نامشخص، تکرار نکنید.</p>
                      <Input name="confirmation" required dir="ltr" placeholder="REFUND_STARS_EXECUTE" />
                      <Button variant="destructive" type="submit">اجرای بازپرداخت Stars</Button>
                    </form>
                  ) : <p className="text-xs leading-6 text-muted-foreground">بازپرداخت Stars در حال حاضر قابل اجرا نیست؛ وضعیت را در پیام‌رسان بررسی کنید.</p>
                ) : (
                  <form action={resolveRefund} className="space-y-2">
                    <input type="hidden" name="case_id" value={refund.id} />
                    <input type="hidden" name="action" value={refund.provider === "store_credit" ? "store_credit" : "manual"} />
                    {refund.provider !== "store_credit" ? (
                      <label className="block space-y-1 text-xs">شناسه پیگیری بازپرداخت تأییدشده نزد ارائه‌دهنده
                        <Input name="provider_reference" minLength={8} maxLength={128} required dir="ltr" />
                      </label>
                    ) : <p className="text-xs text-muted-foreground">بازگشت فقط از دفتر اعتبار داخلی، بدون پرداخت خارجی.</p>}
                    <Input name="confirmation" required dir="ltr" placeholder="REFUND_VERIFIED" />
                    <Button size="sm" type="submit">ثبت بازپرداخت تأییدشده</Button>
                  </form>
                )
              ) : null}
            </div>
          ))}
          {!refunds.length ? <p className="py-8 text-center text-sm text-muted-foreground">پرونده‌ای وجود ندارد.</p> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>آخرین گردش‌های اعتبار</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {ledger.map((entry) => (
            <div key={entry.id} className="grid gap-2 border-b border-border py-3 text-xs md:grid-cols-[1fr_1fr_2fr]">
              <span>#{entry.id} · {entry.platform === "bale" ? "بله" : "تلگرام"} · {entry.user_id}</span>
              <span className="font-medium">{formatIrr(entry.delta_irr)} · مانده {formatIrr(entry.balance_after_irr)}</span>
              <span className="text-muted-foreground">{entry.reason} · {entry.actor} · {new Date(entry.created_at).toLocaleString("fa-IR")}</span>
            </div>
          ))}
          {!ledger.length ? <p className="text-sm text-muted-foreground">هنوز تراکنش داخلی ثبت نشده است.</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}
