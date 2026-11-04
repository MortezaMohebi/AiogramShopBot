/** Protect transient drafts and unknown operation receipts from SPA navigation. */
export function createNavigationGuard(host: Window) {
  const blockers = new Set<() => boolean>();
  let guardedUrl = "",
    bypass = false,
    approvedLeave = false;
  const blocked = () => [...blockers].some((fn) => fn());
  const confirm = () =>
    !blocked() ||
    host.confirm(
      "تغییر ذخیره‌نشده یا عملیات تأییدنشده دارید. پیش از خروج JSON و رسید عملیات را بررسی کنید. خروج از صفحه؟",
    );
  const marker = () =>
    host.history.pushState(
      { ...host.history.state, __shopWorkflowGuard: host.location.href },
      "",
      host.location.href,
    );
  host.addEventListener("popstate", () => {
    if (bypass) {
      bypass = false;
      return;
    }
    if (!blockers.size || host.location.href !== guardedUrl) return;
    // The first traversal reaches the identical URL's sentinel, preserving the
    // mounted App Router tree while the user decides whether to leave.
    if (!confirm()) {
      marker();
      return;
    }
    approvedLeave = true;
    bypass = true;
    host.history.back();
  });
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
      if (!blockers.size) {
        guardedUrl = host.location.href;
        if (host.history.state?.__shopWorkflowGuard !== guardedUrl) marker();
      }
      blockers.add(fn);
      return () => {
        blockers.delete(fn);
      };
    },
    confirm,
  };
}
let current: ReturnType<typeof createNavigationGuard> | null = null;
export function registerWorkflowGuard(blocker: () => boolean): () => void {
  current ??= createNavigationGuard(window);
  return current.register(blocker);
}
/** Store switching refreshes the route without an anchor or history event. */
export function confirmWorkflowNavigation(): boolean {
  return current?.confirm() ?? true;
}
