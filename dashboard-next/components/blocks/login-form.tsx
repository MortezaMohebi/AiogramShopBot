"use client";

import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { AlertCircle, ArrowLeft, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  CaptchaChallenge,
  type CaptchaChallengeHandle,
} from "@/components/blocks/captcha-challenge";
import type { PublicCaptchaConfig } from "@/lib/captcha-types";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Input } from "@/components/ui/input";
import {
  type LoginErrorCode,
  loginErrorMessages,
  normalizeLoginError,
} from "@/lib/login-errors";

interface LoginFormProps {
  initialError?: string | null;
  captcha: PublicCaptchaConfig;
}

interface LoginIssue {
  code: LoginErrorCode;
  requestId?: string;
}

interface LoginResponse {
  ok?: boolean;
  code?: string;
  requestId?: string;
  redirect?: string;
  challenge?: string;
}

/** Safely parse JSON; an intermediary may return an HTML sign-in page. */
async function readJson(response: Response): Promise<LoginResponse> {
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
    throw new Error("network_unavailable");
  }
  try {
    const value: unknown = await response.json();
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("service_unavailable");
    }
    return value as LoginResponse;
  } catch {
    throw new Error("service_unavailable");
  }
}

/** Format a backend error without displaying raw exception details. */
function loginIssue(data: LoginResponse, status: number): LoginIssue {
  const code = typeof data.code === "string"
    ? normalizeLoginError(data.code)
    : status === 401 ? "invalid_credentials"
      : status === 429 ? "temporarily_locked"
        : status === 403 ? "security_check_failed"
          : "service_unavailable";

  const requestId = typeof data.requestId === "string"
    && /^[a-f0-9-]{36}$/i.test(data.requestId)
    ? data.requestId : undefined;
  return { code, requestId };
}

/** Persian, accessible login with host-bound CSRF and inline errors. */
export function LoginForm({ initialError, captcha }: LoginFormProps) {
  const [issue, setIssue] = useState<LoginIssue | null>(
    initialError ? { code: normalizeLoginError(initialError) } : null,
  );
  const [working, setWorking] = useState(false);
  const [phase, setPhase] = useState<"security" | "login">("security");
  const [showPassword, setShowPassword] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const captchaRef = useRef<CaptchaChallengeHandle>(null);

  useEffect(() => {
    if (issue) errorRef.current?.focus();
  }, [issue]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working) return;

    const form = event.currentTarget;
    const formData = new FormData(form);
    const username = String(formData.get("username") ?? "").trim().toLowerCase();
    const password = String(formData.get("password") ?? "");

    if (
      !/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username) ||
      password.length < 1 ||
      password.length > 256
    ) {
      setIssue({ code: "invalid_request" });
      return;
    }

    setIssue(null);
    setWorking(true);
    setPhase("security");

    try {
      // Browser GET sets a host-only HttpOnly cookie before submitting.
      const challenge = await requestBrowserChallenge();
      const captchaToken = await captchaRef.current?.getToken();
      if (captcha.provider !== "none" && !captchaToken) {
        throw new Error("captcha_unavailable");
      }

      setPhase("login");
      const response = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify({ username, password, captchaToken }),
        signal: AbortSignal.timeout(25_000),
      });

      const result = await readJson(response);
      if (!response.ok || result.ok !== true) {
        setIssue(loginIssue(result, response.status));
        // Single-use CAPTCHA tokens must be refreshed after a failed request.
        captchaRef.current?.reset();
        // Never keep a rejected password in the rendered form.
        if (response.status === 401) {
          const input = form.elements.namedItem("password");
          if (input instanceof HTMLInputElement) input.value = "";
        }
        return;
      }

      // Only a fixed, local dashboard destination is valid.
      if (result.redirect !== "/dashboard") {
        throw new Error("service_unavailable");
      }
      // A full navigation reliably observes the new HttpOnly cookie, even
      // when the App Router has a cached unauthenticated server component.
      window.location.replace("/dashboard");
    } catch (error) {
      captchaRef.current?.reset();
      const knownFailures: readonly LoginErrorCode[] = [
        "captcha_required",
        "captcha_unavailable",
        "security_check_failed",
        "service_unavailable",
      ];
      const code = error instanceof Error &&
        knownFailures.some((value) => value === error.message)
        ? (error.message as LoginErrorCode)
        : "network_unavailable";
      setIssue({ code });
    } finally {
      setWorking(false);
    }
  }

  const message = issue ? loginErrorMessages[issue.code] : null;

  return (
    <form
      action="/api/auth/login"
      method="post"
      onSubmit={handleSubmit}
      className="space-y-5"
      aria-busy={working}
    >
      {message ? (
        <div
          ref={errorRef}
          tabIndex={-1}
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive focus:outline-none"
        >
          <div className="flex items-start gap-2">
            <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold">{message.title}</p>
              <p className="leading-7">{message.description}</p>
              {issue?.requestId ? (
                <p dir="ltr" className="pt-1 text-xs opacity-75">
                  Request ID: {issue.requestId}
                </p>
              ) : null}
              {issue?.code === "security_check_failed" ? (
                <a
                  href="/login"
                  className="inline-block pt-1 font-medium underline underline-offset-4"
                >
                  بازکردن دوبارهٔ صفحهٔ ورود
                </a>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <label htmlFor="username" className="text-sm font-medium">
          نام کاربری
        </label>
        <Input
          id="username"
          name="username"
          type="text"
          dir="ltr"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          minLength={3}
          maxLength={80}
          className="text-start"
          disabled={working}
          required
        />
      </div>

      <div className="space-y-2">
        <label htmlFor="password" className="text-sm font-medium">
          رمز عبور
        </label>
        {/* Keep LTR password text and the reveal control in one direction,
            while the surrounding form remains Persian RTL. */}
        <div className="relative" dir="ltr">
          <Input
            id="password"
            name="password"
            type={showPassword ? "text" : "password"}
            dir="ltr"
            autoComplete="current-password"
            minLength={1}
            maxLength={256}
            className="ps-12 text-start"
            disabled={working}
            required
          />
          <button
            type="button"
            aria-label={showPassword ? "مخفی‌کردن رمز عبور" : "نمایش رمز عبور"}
            aria-pressed={showPassword}
            className="absolute start-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
            onClick={() => setShowPassword((value) => !value)}
            disabled={working}
          >
            {showPassword ? <EyeOff aria-hidden="true" className="size-4" />
              : <Eye aria-hidden="true" className="size-4" />}
          </button>
        </div>
      </div>

      <CaptchaChallenge ref={captchaRef} config={captcha} />

      <Button
        type="submit"
        size="lg"
        className="w-full"
        disabled={working || captcha.provider === "unavailable"}
      >
        {working ? (
          <>
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
            {phase === "security" ? "در حال بررسی امنیت ورود..." : "در حال ورود..."}
          </>
        ) : (
          <>ورود امن <ArrowLeft aria-hidden="true" className="size-4" /></>
        )}
      </Button>

      <p className="text-center text-xs leading-6 text-muted-foreground">
        اطلاعات ورود فقط از مسیر HTTPS به سرویس مدیریت ارسال می‌شوند.
      </p>
    </form>
  );
}
