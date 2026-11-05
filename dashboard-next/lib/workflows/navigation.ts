/** Protect transient drafts and receipts before App Router processes history events. */
export function createNavigationGuard(host: Window) {
  const blockers = new Set<() => boolean>();
  const existing = host.history.state?.__shopWorkflowPosition as
    | { scope?: unknown; index?: unknown }
    | undefined;
  const previousPosition =
    typeof existing?.scope === "string" && Number.isSafeInteger(existing.index)
      ? { scope: existing.scope, index: existing.index as number }
      : null;
  let scope =
    previousPosition?.scope ??
    host.crypto?.randomUUID?.() ??
    `workflow-${Date.now()}`;
  const nativePush = host.history.pushState.bind(host.history);
  const nativeReplace = host.history.replaceState.bind(host.history);
  let index = previousPosition?.index ?? 0,
    restoring = false,
    approvedLeave = false;
  const blocked = () => [...blockers].some((fn) => fn());
  const confirm = () =>
    !blocked() ||
    host.confirm(
      "تغییر ذخیره‌نشده یا عملیات تأییدنشده دارید. پیش از خروج JSON و رسید عملیات را بررسی کنید. خروج از صفحه؟",
    );
  const stamped = (state: unknown, position: number) => ({
    ...(state && typeof state === "object" ? state : {}),
    __shopWorkflowPosition: { scope, index: position },
  });
  nativeReplace(stamped(host.history.state, index), "", host.location.href);
  let previous = { url: host.location.href, state: host.history.state };
  // Next's internal history data is preserved. Observing push/replace also
  // covers history entries created while no editor is currently mounted.
  host.history.pushState = (state, unused, url) => {
    nativePush(stamped(state, index + 1), unused, url);
    index++;
    previous = { url: host.location.href, state: host.history.state };
  };
  host.history.replaceState = (state, unused, url) => {
    nativeReplace(stamped(state, index), unused, url);
    previous = { url: host.location.href, state: host.history.state };
  };
  host.addEventListener(
    "popstate",
    (event) => {
      if (restoring) {
        event.stopImmediatePropagation();
        restoring = false;
        return;
      }
      const target = event.state?.__shopWorkflowPosition as
        | { scope?: string; index?: number }
        | undefined;
      if (blocked() && !confirm()) {
        // Capture runs before Next's bubble listener, preserving the mounted
        // graph/receipt. Rewind a known traversal without deleting forward history.
        event.stopImmediatePropagation();
        if (
          target?.scope === scope &&
          typeof target.index === "number" &&
          target.index !== index
        ) {
          restoring = true;
          host.history.go(index - target.index);
        } else {
          // The physical rewind distance is unknown. A new checkpoint must
          // have a fresh epoch; reusing its old index would create duplicates.
          scope = `${host.crypto?.randomUUID?.() ?? Math.random().toString(36)}-${Date.now()}`;
          index = 0;
          nativePush(stamped(previous.state, index), "", previous.url);
          previous = { url: host.location.href, state: host.history.state };
        }
        return;
      }
      if (blocked()) approvedLeave = true;
      if (target?.scope === scope && typeof target.index === "number") {
        index = target.index;
      } else {
        // Entries from before this guard have no known physical distance. Start
        // a new epoch so a later replaceState cannot assign them a stale index.
        scope = `${host.crypto?.randomUUID?.() ?? Math.random().toString(36)}-${Date.now()}`;
        index = 0;
        nativeReplace(
          stamped(host.history.state, index),
          "",
          host.location.href,
        );
      }
      previous = { url: host.location.href, state: host.history.state };
    },
    true,
  );
  host.addEventListener("beforeunload", (event) => {
    if (blocked() && !approvedLeave) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  host.document.addEventListener(
    "click",
    (event) => {
      if (
        !blocked() ||
        event.defaultPrevented ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const anchor =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !(anchor instanceof HTMLAnchorElement) ||
        anchor.target === "_blank" ||
        anchor.hasAttribute("download")
      )
        return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || anchor.href === host.location.href)
        return;
      if (!confirm()) {
        event.preventDefault();
        event.stopPropagation();
      } else approvedLeave = true;
    },
    true,
  );
  return {
    register(fn: () => boolean) {
      approvedLeave = false;
      blockers.add(fn);
      return () => {
        blockers.delete(fn);
      };
    },
    confirm,
  };
}
// Console client modules load before route transitions, allowing all entries in
// this application session to carry a position. No draft content enters history.
let current: ReturnType<typeof createNavigationGuard> | null =
  typeof window !== "undefined" ? createNavigationGuard(window) : null;
export function registerWorkflowGuard(blocker: () => boolean): () => void {
  current ??= createNavigationGuard(window);
  return current.register(blocker);
}
/** Store switching refreshes the route without an anchor or traversal event. */
export function confirmWorkflowNavigation(): boolean {
  return current?.confirm() ?? true;
}
