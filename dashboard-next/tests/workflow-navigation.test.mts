import assert from "node:assert/strict";
import { test } from "node:test";
import { createNavigationGuard } from "../lib/workflows/navigation.ts";
/** A browser history host dispatches capture listeners before router listeners. */
function browser(initial = ["https://shop.test/list"], initialIndex = 0) {
  const listeners: {
    type: string;
    capture: boolean;
    fn: (e: Event) => void;
  }[] = [];
  const stack = initial.map((url) => ({
    url,
    state: { __NA: true } as Record<string, unknown>,
  }));
  let index = initialIndex,
    confirmations = 0,
    routes = 0;
  const host = {
    location: { href: stack[index].url },
    confirm: () => {
      confirmations++;
      return false;
    },
    addEventListener: (type: string, fn: (e: Event) => void, capture = false) =>
      listeners.push({ type, fn, capture }),
    document: { addEventListener: () => {} },
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
      replaceState(
        state: Record<string, unknown>,
        _title: string,
        url: string,
      ) {
        stack[index] = { url: url ?? host.location.href, state };
        host.location.href = stack[index].url;
      },
      go(delta: number) {
        const next = index + delta;
        if (next < 0 || next >= stack.length) return;
        index = next;
        host.location.href = stack[index].url;
        let stopped = false;
        const event = {
          state: stack[index].state,
          stopImmediatePropagation() {
            stopped = true;
          },
        } as unknown as Event;
        for (const listener of [...listeners].sort(
          (a, b) => Number(b.capture) - Number(a.capture),
        )) {
          if (stopped) break;
          if (listener.type === "popstate") listener.fn(event);
        }
      },
      back() {
        host.history.go(-1);
      },
      forward() {
        host.history.go(1);
      },
    },
  };
  host.addEventListener("popstate", () => {
    routes++;
  });
  const guard = createNavigationGuard(host as unknown as Window);
  return {
    host: host as unknown as Window,
    guard,
    confirmations: () => confirmations,
    routes: () => routes,
    position: () => index,
    length: () => stack.length,
  };
}
function editor() {
  const b = browser();
  b.host.history.pushState({ __NA: true }, "", "https://shop.test/editor");
  return b;
}
test("declined Back preserves the editor, its history and mounted router tree", () => {
  const b = editor();
  b.guard.register(() => true);
  b.host.history.back();
  assert.equal(b.host.location.href, "https://shop.test/editor");
  assert.equal(b.confirmations(), 1);
  assert.equal(b.length(), 2);
  assert.equal(b.routes(), 0);
});
test("clean Back reaches the previous route once", () => {
  const b = editor();
  b.guard.register(() => false);
  b.host.history.back();
  assert.equal(b.host.location.href, "https://shop.test/list");
  assert.equal(b.confirmations(), 0);
  assert.equal(b.routes(), 1);
});
test("declined Forward preserves dirty state and does not dispatch App Router restore", () => {
  const b = editor();
  b.host.history.pushState({ __NA: true }, "", "https://shop.test/versions");
  b.host.history.back();
  const routes = b.routes();
  b.guard.register(() => true);
  b.host.history.forward();
  assert.equal(b.host.location.href, "https://shop.test/editor");
  assert.equal(b.confirmations(), 1);
  assert.equal(b.routes(), routes);
  assert.equal(b.length(), 3);
});
test("a skipped multi-entry traversal cannot bypass the pending-operation guard", () => {
  const b = browser();
  b.host.history.pushState({}, "", "https://shop.test/one");
  b.host.history.pushState({}, "", "https://shop.test/two");
  b.host.history.pushState({ __NA: true }, "", "https://shop.test/editor");
  b.guard.register(() => true);
  b.host.history.go(-3);
  assert.equal(b.host.location.href, "https://shop.test/editor");
  assert.equal(b.confirmations(), 1);
  assert.equal(b.routes(), 0);
});
test("an unknown operation alone blocks Store-context navigation", () => {
  const b = editor();
  b.guard.register(() => false);
  const release = b.guard.register(() => true);
  assert.equal(b.guard.confirm(), false);
  release();
  assert.equal(b.guard.confirm(), true);
});

test("an allowed old unmarked traversal rebases before App Router replaces state", () => {
  const b = browser(
    ["https://shop.test/old-editor", "https://shop.test/versions"],
    1,
  );
  b.host.history.pushState({ __NA: true }, "", "https://shop.test/settings");
  b.host.history.go(-2);
  b.host.history.replaceState(
    { ...b.host.history.state, __NA: true },
    "",
    b.host.location.href,
  );
  const routes = b.routes();
  b.guard.register(() => true);
  b.host.history.forward();
  assert.equal(b.host.location.href, "https://shop.test/old-editor");
  assert.equal(b.routes(), routes);
  assert.equal(b.confirmations(), 1);
});
test("declining an unknown traversal starts a new epoch before later pushes", () => {
  const b = browser(
    ["https://shop.test/old-editor", "https://shop.test/versions"],
    1,
  );
  b.host.history.pushState({ __NA: true }, "", "https://shop.test/settings");
  b.host.history.go(-2);
  const release = b.guard.register(() => true);
  b.host.history.forward();
  release();
  b.host.history.pushState({ __NA: true }, "", "https://shop.test/new-editor");
  const routes = b.routes();
  b.guard.register(() => true);
  b.host.history.go(-3);
  assert.equal(b.host.location.href, "https://shop.test/new-editor");
  assert.equal(b.routes(), routes);
});
