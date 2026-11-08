"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";

const resultKeys = [
  "saved", "error", "acl_saved", "acl_error", "commerce_saved", "commerce_error",
  "ux_saved", "ux_error", "relay_saved", "relay_error",
];

export function ConsumeBotResult() {
  const pathname = usePathname();
  const params = useSearchParams();

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.pathname !== pathname || url.searchParams.toString() !== params.toString()) return;

    for (const key of resultKeys) {
      for (const value of url.searchParams.getAll(key)) {
        // The console still needs these markers to offer inline reauthentication.
        if (key.endsWith("error") && (value === "reauth" || value === "reauthentication_required")) continue;
        url.searchParams.delete(key, value);
      }
    }
    if (url.searchParams.toString() !== params.toString()) {
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  }, [pathname, params]);

  return null;
}
