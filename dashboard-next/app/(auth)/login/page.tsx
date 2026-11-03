import { ArrowLeft, LockKeyhole, ShieldCheck, MessageSquareMore } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Params = Promise<{ error?: string; expired?: string }>;

const errors: Record<string, string> = {
  credentials: "نام کاربری یا رمز عبور معتبر نیست.",
  locked: "تعداد تلاش‌ها بیش از حد مجاز است. بعداً دوباره امتحان کنید.",
  unavailable: "سرویس ورود موقتاً در دسترس نیست.",
};

/** Login-01-inspired RTL block; credentials are verified by FastAPI Argon2. */
export default async function LoginPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const message = params.expired
    ? "نشست قبلی پایان یافته یا دسترسی شما تغییر کرده است."
    : params.error
      ? errors[params.error] ?? errors.credentials
      : null;

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
            مدیریت یکپارچه،<br />بدون پیچیدگی.
          </h1>
          <p className="mt-5 max-w-md text-lg leading-9 text-white/65">
            محصولات، سفارش‌ها و کمپین‌های تلگرام و بله را در یک فضای امن و منظم مدیریت کنید.
          </p>
        </div>
        <p className="relative text-xs text-white/50">پنل مدیریتی خصوصی • دسترسی بر اساس نقش</p>
      </section>

      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <div className="mb-3 grid size-12 place-items-center rounded-xl bg-primary text-primary-foreground">
              <MessageSquareMore />
            </div>
            <h1 className="text-2xl font-bold">مدیریت فروشگاه</h1>
          </div>
          <Card className="border-border/70 shadow-xl shadow-black/5 dark:shadow-black/20">
            <CardHeader className="pb-6">
              <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-accent text-accent-foreground">
                <LockKeyhole className="size-5" />
              </div>
              <CardTitle className="text-xl">ورود به داشبورد</CardTitle>
              <CardDescription>با حساب مدیریتی اختصاصی خود وارد شوید.</CardDescription>
            </CardHeader>
            <CardContent>
              {message ? (
                <div role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-3 text-sm text-destructive">
                  {message}
                </div>
              ) : null}
              <form action="/api/auth/login" method="post" className="space-y-5">
                <div className="space-y-2">
                  <label htmlFor="username" className="text-sm font-medium">نام کاربری</label>
                  <Input
                    id="username" name="username" type="text" dir="ltr"
                    autoComplete="username" required minLength={3} maxLength={80}
                    className="text-start"
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="password" className="text-sm font-medium">رمز عبور</label>
                  <Input
                    id="password" name="password" type="password" dir="ltr"
                    autoComplete="current-password" required maxLength={256}
                    className="text-start"
                  />
                </div>
                <Button type="submit" size="lg" className="w-full">
                  ورود امن <ArrowLeft className="size-4" />
                </Button>
              </form>
              <p className="mt-5 text-xs leading-6 text-muted-foreground">
                حساب‌های مدیر از قبل در سرور تعریف می‌شوند؛ ثبت‌نام عمومی وجود ندارد.
                برای Codespaces، نام کاربری اولیه <code dir="ltr">shopadmin</code> است.
                رمز اولیه را فقط در ترمینال خصوصی با دستور
                <code dir="ltr">python3 scripts/codespace_setup.py credentials</code>
                مشاهده کنید.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
