"use client";

import { useState } from "react";
import { LogOut, LoaderCircle } from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";

/** Log out through the same CSRF-protected BFF without a raw error page. */
export function LogoutControl() {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function logout() {
    if (working) return;
    setWorking(true);
    setError(null);

    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) {
        throw new Error("logout_failed");
      }
      const result: unknown = await response.json();
      if (
        !result ||
        typeof result !== "object" ||
        !("ok" in result) ||
        result.ok !== true
      ) {
        throw new Error("logout_failed");
      }

      // The server has removed the authenticated host-only cookie.
      window.location.assign("/login");
    } catch {
      setError("خروج امن انجام نشد. اتصال را بررسی و دوباره تلاش کنید.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={logout}
        disabled={working}
        aria-busy={working}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
      >
        {working
          ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
          : <LogOut aria-hidden="true" className="size-4" />}
        {working ? "در حال خروج..." : "خروج امن"}
      </button>
      {error ? <p role="alert" className="px-3 text-xs leading-6 text-destructive">{error}</p> : null}
    </div>
  );
}
