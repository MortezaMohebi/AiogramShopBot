"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Download, Share, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  installSuggestion, mobileInstallPlatform,
} from "@/lib/pwa-install";

interface NativeInstallPrompt extends Event {
  prompt(): Promise<unknown>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const DISMISSED_KEY = "shop-admin:install-suggestion-dismissed";

function hasDismissed(): boolean {
  try { return localStorage.getItem(DISMISSED_KEY) === "1"; }
  catch { return false; }
}

function rememberDismissal(): void {
  try { localStorage.setItem(DISMISSED_KEY, "1"); }
  catch { /* Browser storage can be unavailable in private browsing. */ }
}

const standaloneQuery = "(display-mode: standalone)";

function inStandaloneMode(): boolean {
  const apple = (navigator as Navigator & { standalone?: boolean }).standalone;
  return window.matchMedia(standaloneQuery).matches || apple === true;
}

function eligiblePlatform() {
  if (!window.isSecureContext || window.self !== window.top) return null;
  const device = mobileInstallPlatform(navigator.userAgent, navigator.platform, navigator.maxTouchPoints);
  return installSuggestion(device, hasDismissed(), inStandaloneMode(), true);
}

function subscribeToEnvironment(listener: () => void): () => void {
  const mode = window.matchMedia(standaloneQuery);
  mode.addEventListener("change", listener);
  window.addEventListener("storage", listener);
  return () => {
    mode.removeEventListener("change", listener);
    window.removeEventListener("storage", listener);
  };
}

export function PwaInstallBanner() {
  const platform = useSyncExternalStore(subscribeToEnvironment, eligiblePlatform, () => null);
  const [dismissed, setDismissed] = useState(false);
  const [prompt, setPrompt] = useState<NativeInstallPrompt | null>(null);
  const [installing, setInstalling] = useState(false);
  const [showInstructions, setShowInstructions] = useState(false);
  const promptInFlight = useRef(false);

  useEffect(() => {
    if (!window.isSecureContext || window.self !== window.top) return;

    function capturePrompt(event: Event) {
      const native = event as Partial<NativeInstallPrompt>;
      if (typeof native.prompt !== "function" || !native.userChoice) return;
      // Install suggestions belong to this mobile control; the desktop
      // browser can still expose installation in its own menus.
      event.preventDefault();
      if (eligiblePlatform() === "android") setPrompt(event as NativeInstallPrompt);
    }

    function onInstalled() {
      rememberDismissal();
      setDismissed(true);
      setPrompt(null);
    }

    window.addEventListener("beforeinstallprompt", capturePrompt);
    window.addEventListener("appinstalled", onInstalled);
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      // A forwarded private HTTPS origin can register its own worker.
      // Failure must never block login or the authenticated dashboard.
      void navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" })
        .catch(() => undefined);
    }
    return () => {
      window.removeEventListener("beforeinstallprompt", capturePrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  function dismiss() {
    rememberDismissal();
    setDismissed(true);
    setPrompt(null);
  }

  async function install() {
    if (!prompt || promptInFlight.current) return;
    promptInFlight.current = true;
    setInstalling(true);
    try {
      // Must run directly from the button's user activation.
      await prompt.prompt();
      await prompt.userChoice;
      dismiss();
    } catch {
      // The browser can invalidate a captured event. It cannot be replayed.
      setPrompt(null);
    } finally {
      promptInFlight.current = false;
      setInstalling(false);
    }
  }

  const suggestion = installSuggestion(platform, dismissed, false, prompt !== null);
  if (!suggestion) return null;

  return <aside aria-label="نصب پنل روی گوشی" className="border-b border-border bg-card px-4 py-3 text-card-foreground">
    <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-2">
      <div className="min-w-0 flex-1 basis-40">
        <p className="text-sm font-semibold">پنل فروشگاه روی صفحهٔ اصلی</p>
        <p className="text-xs leading-6 text-muted-foreground">برای دسترسی سریع، پنل را به گوشی اضافه کنید.</p>
      </div>
      {suggestion === "android" ? <Button type="button" size="sm" disabled={installing} onClick={() => void install()}>
        <Download aria-hidden="true" />{installing ? "در حال باز کردن نصب…" : "نصب پنل"}
      </Button> : <Button type="button" size="sm" variant="outline" aria-controls="pwa-ios-install-help"
        aria-expanded={showInstructions} onClick={() => setShowInstructions((visible) => !visible)}>
        <Share aria-hidden="true" />راهنمای نصب
      </Button>}
      <Button type="button" size="icon" variant="ghost" aria-label="دیگر پیشنهاد نصب را نشان نده"
        onClick={dismiss}>
        <X aria-hidden="true" />
      </Button>
      {suggestion === "ios" ? <div id="pwa-ios-install-help" hidden={!showInstructions}
        className="w-full rounded-md bg-muted px-3 py-2 text-sm leading-7">
        در Safari، منوی اشتراک‌گذاری <bdi>Share</bdi> را باز کنید. سپس
        {" "}<bdi>Add to Home Screen</bdi> (افزودن به صفحهٔ اصلی) را بزنید.
        اگر گزینهٔ <bdi>Open as Web App</bdi> را می‌بینید، آن را روشن کنید و <bdi>Add</bdi> را بزنید.
      </div> : null}
    </div>
  </aside>;
}
