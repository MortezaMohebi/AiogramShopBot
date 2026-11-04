import assert from "node:assert/strict";
import { test } from "node:test";
import { createNavigationGuard } from "../lib/workflows/navigation.ts";
function browser() {
  const listeners = new Map<string, Set<(e: unknown) => void>>();
  const stack = [
    { url: "https://shop.test/list", state: {} },
    { url: "https://shop.test/editor", state: { __NA: true } },
  ];
  let index = 1,
    confirmations = 0;
  const host = {
    location: { href: stack[index].url },
    confirm: () => {
      confirmations++;
      return false;
    },
    addEventListener: (key: string, fn: (e: unknown) => void) => {
      if (!listeners.has(key)) listeners.set(key, new Set());
      listeners.get(key)!.add(fn);
    },
    document: { addEventListener: () => {}, removeEventListener: () => {} },
    history: {
      get state() {
        return stack[index].state;
      },
      pushState(state: Record<string, unknown>, _title: string, url: string) {
        stack.splice(index + 1);
        stack.push({ url, state });
        index++;
        host.location.href = url;
      },
      back() {
        if (index > 0) {
          index--;
          host.location.href = stack[index].url;
          for (const fn of listeners.get("popstate") ?? [])
            fn({ state: stack[index].state });
        }
      },
    },
  };
  return {
    host: host as unknown as Window,
    confirmations: () => confirmations,
    position: () => index,
  };
}
test("browser Back preserves dirty state at the same route after dismissal", () => {
  const b = browser();
  const guard = createNavigationGuard(b.host);
  guard.register(() => true);
  b.host.history.back();
  assert.equal(b.host.location.href, "https://shop.test/editor");
  assert.equal(b.confirmations(), 1);
  assert.equal(b.position(), 2);
});
test("clean Back crosses the sentinel once and reaches the previous route", () => {
  const b = browser();
  const guard = createNavigationGuard(b.host);
  guard.register(() => false);
  b.host.history.back();
  assert.equal(b.host.location.href, "https://shop.test/list");
  assert.equal(b.confirmations(), 0);
});
test("an unknown operation alone blocks history and Store-context navigation", () => {
  const b = browser();
  const guard = createNavigationGuard(b.host);
  guard.register(() => false);
  const release = guard.register(() => true);
  assert.equal(guard.confirm(), false);
  b.host.history.back();
  assert.equal(b.host.location.href, "https://shop.test/editor");
  release();
  assert.equal(guard.confirm(), true);
});
