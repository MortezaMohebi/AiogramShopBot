"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import Script from "next/script";
import type { PublicCaptchaConfig } from "@/lib/captcha-types";

type WidgetCallbacks = {
  callback: (token: string) => void;
  "expired-callback": () => void;
  "error-callback": () => void;
};

interface TurnstileAPI {
  render: (
    target: HTMLElement,
    options: WidgetCallbacks & {
      sitekey: string;
      action: string;
      theme: "auto";
    },
  ) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}

interface RecaptchaAPI {
  ready: (callback: () => void) => void;
  render: (
    target: HTMLElement,
    options: WidgetCallbacks & { sitekey: string },
  ) => number;
  reset: (widgetId: number) => void;
  execute: (siteKey: string, options: { action: string }) => Promise<string>;
}

declare global {
  interface Window {
    turnstile?: TurnstileAPI;
    grecaptcha?: RecaptchaAPI;
  }
}

export interface CaptchaChallengeHandle {
  getToken: () => Promise<string | null>;
  reset: () => void;
}

interface CaptchaChallengeProps {
  config: PublicCaptchaConfig;
}

/** Return a fresh v3 token for each login attempt, bounded by a timeout. */
function executeRecaptchaV3(siteKey: string): Promise<string> {
  const api = window.grecaptcha;
  if (!api) return Promise.reject(new Error("captcha_unavailable"));

  return new Promise<string>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error("captcha_unavailable"));
    }, 12_000);

    try {
      api.ready(() => {
        try {
          api.execute(siteKey, { action: "login" }).then(
            (token) => {
              window.clearTimeout(timeout);
              if (token) resolve(token);
              else reject(new Error("captcha_required"));
            },
            () => {
              window.clearTimeout(timeout);
              reject(new Error("captcha_unavailable"));
            },
          );
        } catch {
          window.clearTimeout(timeout);
          reject(new Error("captcha_unavailable"));
        }
      });
    } catch {
      window.clearTimeout(timeout);
      reject(new Error("captcha_unavailable"));
    }
  });
}

/**
 * Render one selected provider with no additional CAPTCHA npm dependencies.
 *
 * The parent owns submissions. This widget only supplies the token and resets
 * used/expired tokens; the server is always responsible for verification.
 */
export const CaptchaChallenge = forwardRef<
  CaptchaChallengeHandle,
  CaptchaChallengeProps
>(function CaptchaChallenge({ config }, ref) {
  const provider = config.provider;
  const siteKey = "siteKey" in config ? config.siteKey : "";
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetRef = useRef<string | number | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [token, setToken] = useState("");

  useEffect(() => {
    if (
      !ready ||
      (provider !== "turnstile" && provider !== "recaptcha_v2") ||
      !containerRef.current
    ) return;

    const container = containerRef.current;
    const target = document.createElement("div");
    container.replaceChildren(target);
    let disposed = false;
    const callbacks: WidgetCallbacks = {
      callback: (value) => {
        if (!disposed) {
          setToken(value);
          setFailed(false);
        }
      },
      "expired-callback": () => {
        if (!disposed) setToken("");
      },
      "error-callback": () => {
        if (!disposed) {
          setToken("");
          setFailed(true);
        }
      },
    };

    if (provider === "turnstile") {
      try {
        if (!window.turnstile) throw new Error("captcha_unavailable");
        widgetRef.current = window.turnstile.render(target, {
          sitekey: siteKey,
          action: "login",
          theme: "auto",
          ...callbacks,
        });
      } catch {
        setFailed(true);
      }
    } else {
      const api = window.grecaptcha;
      if (!api) {
        setFailed(true);
      } else {
        api.ready(() => {
          if (disposed) return;
          try {
            widgetRef.current = api.render(target, {
              sitekey: siteKey,
              ...callbacks,
            });
          } catch {
            setFailed(true);
          }
        });
      }
    }

    return () => {
      disposed = true;
      if (provider === "turnstile" && typeof widgetRef.current === "string") {
        try {
          window.turnstile?.remove(widgetRef.current);
        } catch {
          // The provider may already have removed its iframe.
        }
      }
      widgetRef.current = null;
      target.remove();
    };
  }, [provider, ready, siteKey]);

  useImperativeHandle(ref, () => ({
    async getToken() {
      if (provider === "none") return null;
      if (provider === "unavailable" || failed || !ready) {
        throw new Error("captcha_unavailable");
      }
      if (provider === "recaptcha_v3") return executeRecaptchaV3(siteKey);
      if (!token) throw new Error("captcha_required");
      return token;
    },
    reset() {
      setToken("");
      if (provider === "turnstile" && typeof widgetRef.current === "string") {
        try {
          window.turnstile?.reset(widgetRef.current);
        } catch {
          setFailed(true);
        }
      } else if (
        provider === "recaptcha_v2" &&
        typeof widgetRef.current === "number"
      ) {
        try {
          window.grecaptcha?.reset(widgetRef.current);
        } catch {
          setFailed(true);
        }
      }
    },
  }), [failed, provider, ready, siteKey, token]);

  if (provider === "none") return null;
  if (provider === "unavailable") {
    return (
      <p role="alert" className="text-sm leading-7 text-destructive">
        تنظیمات بررسی امنیتی ورود کامل نیست. با مدیر سامانه تماس بگیرید.
      </p>
    );
  }

  const scriptUrl = provider === "turnstile"
    ? "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
    : provider === "recaptcha_v2"
      ? "https://www.google.com/recaptcha/api.js?render=explicit"
      : "https://www.google.com/recaptcha/api.js?render=" +
        encodeURIComponent(siteKey);

  return (
    <div aria-label="بررسی امنیتی ورود" className="space-y-2">
      <Script
        src={scriptUrl}
        strategy="afterInteractive"
        onReady={() => setReady(true)}
        onError={() => setFailed(true)}
      />
      {provider === "recaptcha_v3" ? (
        <p className="text-xs leading-6 text-muted-foreground">
          هنگام ورود، ارزیابی امنیتی Google reCAPTCHA انجام می‌شود.
        </p>
      ) : (
        <div ref={containerRef} className="min-h-16" />
      )}
      {!ready && !failed ? (
        <p role="status" className="text-xs text-muted-foreground">
          در حال بارگذاری بررسی امنیتی…
        </p>
      ) : null}
      {failed ? (
        <p role="alert" className="text-xs leading-6 text-destructive">
          بررسی امنیتی بارگذاری نشد. اتصال خود را بررسی و صفحه را تازه‌سازی کنید.
        </p>
      ) : null}
    </div>
  );
});
