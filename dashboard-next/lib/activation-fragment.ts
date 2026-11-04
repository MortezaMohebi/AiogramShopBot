/** Per-mount browser capability store; no token is serialized during SSR. */
export type ActivationClaim = Readonly<{ kind: "invite" | "reset"; token: string }>;

interface FragmentSource {
  location: { hash: string };
  history: { replaceState(data: unknown, unused: string, url: string): void };
  addEventListener(event: "hashchange", listener: () => void): void;
  removeEventListener(event: "hashchange", listener: () => void): void;
}

const FRAGMENT = /^#(invite|reset)=([A-Za-z0-9_-]{43})$/;

/** Capture an external URL once, scrub it, and retain only a private snapshot. */
export function createActivationStore(
  readSource: () => FragmentSource | undefined = () =>
    typeof window === "undefined" ? undefined : window,
) {
  let claim: ActivationClaim | null = null;
  const listeners = new Set<() => void>();
  const notify = () => { for (const listener of listeners) listener(); };
  const capture = () => {
    const source = readSource();
    if (!source) return;
    const match = FRAGMENT.exec(source.location.hash);
    if (!match) return;
    claim = { kind: match[1] as ActivationClaim["kind"], token: match[2] };
    // The capability stays in this component's memory, outside history/URLs.
    source.history.replaceState(null, "", "/activate");
    notify();
  };
  return {
    getSnapshot: () => claim,
    getServerSnapshot: (): null => null,
    subscribe(listener: () => void) {
      listeners.add(listener);
      const source = readSource();
      if (listeners.size === 1) {
        capture();
        source?.addEventListener("hashchange", capture);
      }
      return () => {
        listeners.delete(listener);
        if (!listeners.size) source?.removeEventListener("hashchange", capture);
      };
    },
    clear() { claim = null; notify(); },
  };
}
