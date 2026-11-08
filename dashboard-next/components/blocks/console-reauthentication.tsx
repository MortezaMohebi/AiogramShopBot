"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { ReauthenticateButton } from "@/components/blocks/reauthentication";

/** Keep legacy form redirects on their originating page. */
export function ConsoleReauthentication() {
  const router = useRouter();
  const params = useSearchParams();
  const failures = [...params].filter(([key, value]) =>
    (key === "error" || key.endsWith("_error")) &&
    (value === "reauth" || value === "reauthentication_required"));
  if (!failures.length) return null;

  function clearFailure() {
    const url = new URL(window.location.href);
    for (const [key, value] of failures) url.searchParams.delete(key, value);
    router.replace(url.pathname + url.search + url.hash, { scroll: false });
  }

  return <aside className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
    <p>پس از تأیید هویت در همین صفحه، تغییر را دوباره ثبت کنید.</p>
    <ReauthenticateButton onVerified={clearFailure} />
  </aside>;
}
