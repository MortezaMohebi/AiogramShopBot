import { MessageSquareMore } from "lucide-react";
import { LoginForm } from "@/components/blocks/login-form";
import { publicCaptchaConfig } from "@/lib/captcha-config";

export const dynamic = "force-dynamic";
type Params = Promise<{ error?: string; expired?: string }>;

/** Focused sign-in surface; the existing form owns challenge, MFA and CAPTCHA. */
export default async function LoginPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const initialError = params.expired ? "session_expired" : params.error ?? null;
  return (
    <main className="flex min-h-dvh items-center justify-center px-5 py-10 sm:px-8">
      <section aria-labelledby="login-title" className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
            <MessageSquareMore aria-hidden="true" className="size-5" />
          </span>
          <span className="text-sm font-semibold">مدیریت فروشگاه</span>
        </div>
        <h1 id="login-title" className="mb-7 text-2xl font-bold">ورود به پنل مدیریت</h1>
        <LoginForm initialError={initialError} captcha={publicCaptchaConfig()} />
      </section>
    </main>
  );
}
