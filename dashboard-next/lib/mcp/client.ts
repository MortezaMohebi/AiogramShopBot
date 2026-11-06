import { requestBrowserChallenge } from "@/lib/browser-challenge";

/** Send one exact consent or withdrawal request through the normal CSRF gate. */
async function dispatch(path: string): Promise<Response> {
  const challenge = await requestBrowserChallenge();
  return fetch("/api/admin/mcp" + path, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "x-shop-login-challenge": challenge,
    },
    body: "{}",
    signal: AbortSignal.timeout(25000),
  });
}

let localQueue: Promise<unknown> = Promise.resolve();

/** Share the existing cross-tab challenge lock; never retry an unknown write. */
export async function mcpMutation(path: string): Promise<Response> {
  if (typeof navigator !== "undefined" && navigator.locks)
    return navigator.locks.request("shop-admin-workflow-csrf", () => dispatch(path));
  const result = localQueue.then(() => dispatch(path));
  localQueue = result.then(() => undefined, () => undefined);
  return result;
}
