import { LockKeyhole, ShieldCheck, MessageSquareMore } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LoginForm } from "@/components/blocks/login-form";
import { publicCaptchaConfig } from "@/lib/captcha-config";

export const dynamic = "force-dynamic";

type Params = Promise<{ error?: string; expired?: string }>;

/**
 * Persian RTL sign-in page.
 *
 * Authentication is handled by a client form with an explicit CSRF challenge,
 * never by an unguarded native form POST exposing raw proxy/API errors.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Params;
}) {
  const params = await searchParams;
  const initialError = params.expired ? "session_expired" : params.error ?? null;

  return (
    <main className="grid min-h-screen lg:grid-cols-[1fr_0.9fr]">
      <section className="relative hidden overflow-hidden bg-[#0d272b] p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div aria-hidden="true" className="surface-grid absolute inset-0 opacity-10" />
        <div className="relative flex items-center gap-3 text-sm font-semibold">
          <div className="grid size-10 place-items-center rounded-xl bg-white/15">
            <MessageSquareMore className="size-5" />
          </div>
          فروشگاه مشترک
        </div>
        <div className="relative max-w-xl">
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs text-white/80">
            <ShieldCheck className="size-4" /> یک پایگاه داده، دو پیام‌رسان
          </div>
          <h1 className="text-4xl font-extrabold leading-[1.8]">
            مدیریت یکپارچه، بدون پیچیدگی.
          </h1>
          <p className="mt-5 max-w-md text-lg leading-9 text-white/65">
            محصولات، سفارش‌ها و کمپین‌های تلگرام و بله را در یک فضای امن و منظم مدیریت کنید.
          </p>
        </div>
        <p className="relative text-xs text-white/50">
          دسترسی به مدیریت با حساب اختصاصی و کنترل نقش
        </p>
      </section>

      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <div className="mb-3 grid size-12 place-items-center rounded-xl bg-primary text-primary-foreground">
              <MessageSquareMore aria-hidden="true" />
            </div>
            <h1 className="text-2xl font-bold">مدیریت فروشگاه</h1>
          </div>
          <Card className="border-border/70 shadow-xl shadow-black/5 dark:shadow-black/20">
            <CardHeader className="pb-6">
              <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-accent text-accent-foreground">
                <LockKeyhole aria-hidden="true" className="size-5" />
              </div>
              <CardTitle className="text-xl">ورود به داشبورد</CardTitle>
              <CardDescription>
                با حساب مدیریتی اختصاصی خود وارد شوید.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LoginForm initialError={initialError} captcha={publicCaptchaConfig()} />
              <p className="mt-5 text-xs leading-7 text-muted-foreground">
                ورود فقط برای کاربران مجاز امکان‌پذیر است.
                برای دریافت یا بازیابی اطلاعات حساب، با مدیر سامانه تماس بگیرید.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
