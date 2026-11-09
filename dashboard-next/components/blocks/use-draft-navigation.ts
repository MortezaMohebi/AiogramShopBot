"use client";

import { useEffect, useEffectEvent } from "react";
import { useRouter } from "next/navigation";
import { registerWorkflowGuard } from "@/lib/workflows/navigation";

const drafts = new Set<() => Promise<boolean>>();
let leaving = false;
let release: (() => void) | undefined;

/** Save mounted ordinary drafts before one same-origin navigation. */
export function useDraftNavigation(active: boolean, save: () => Promise<boolean>) {
  const router = useRouter();
  const saveLatest = useEffectEvent(save);

  useEffect(() => {
    if (!active) return;
    const flush = () => saveLatest();
    drafts.add(flush);
    if (drafts.size === 1) {
      const unregister = registerWorkflowGuard(() => drafts.size > 0, { historyOnly: true });
      async function leave(event: MouseEvent) {
        if (event.defaultPrevented || event.button !== 0 ||
            event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
            !(event.target instanceof Element)) return;
        const link = event.target.closest<HTMLAnchorElement>("a[href]");
        if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
        const url = new URL(link.href);
        if (url.origin !== location.origin || url.pathname.startsWith("/api/") ||
            (url.pathname === location.pathname && url.search === location.search)) return;
        event.preventDefault();
        event.stopPropagation();
        if (leaving) return;
        leaving = true;
        try {
          for (const saveDraft of [...drafts]) {
            if (drafts.has(saveDraft) && !(await saveDraft())) return;
          }
          router.push(url.pathname + url.search + url.hash);
        } finally {
          leaving = false;
        }
      }
      document.addEventListener("click", leave, true);
      release = () => {
        unregister();
        document.removeEventListener("click", leave, true);
      };
    }
    return () => {
      drafts.delete(flush);
      if (!drafts.size) {
        release?.();
        release = undefined;
      }
    };
  }, [active, router]);
}
