import assert from "node:assert/strict";
import test from "node:test";
import { createActivationStore } from "../lib/activation-fragment.ts";

test("activation capability survives URL scrubbing and Strict Mode resubscription", () => {
  const token = "A".repeat(43);
  const source = {
    location: { hash: `#invite=${token}` },
    history: { replaceState(_state: unknown, _title: string, url: string) {
      assert.equal(url, "/activate");
      source.location.hash = "";
    } },
    addEventListener() {}, removeEventListener() {},
  };
  const store = createActivationStore(() => source);
  assert.equal(store.getServerSnapshot(), null);
  const unsubscribe = store.subscribe(() => {});
  assert.equal(source.location.hash, "");
  assert.deepEqual(store.getSnapshot(), { kind: "invite", token });
  unsubscribe();
  const unsubscribeAgain = store.subscribe(() => {});
  assert.deepEqual(store.getSnapshot(), { kind: "invite", token });
  store.clear();
  assert.equal(store.getSnapshot(), null);
  unsubscribeAgain();
});

test("server rendering and malformed activation fragments expose no capability", () => {
  const store = createActivationStore(() => undefined);
  const unsubscribe = store.subscribe(() => {});
  assert.equal(store.getSnapshot(), null);
  unsubscribe();
  let scrubbed = false;
  const invalid = createActivationStore(() => ({
    location: { hash: "#reset=short" },
    history: { replaceState() { scrubbed = true; } },
    addEventListener() {}, removeEventListener() {},
  }));
  invalid.subscribe(() => {});
  assert.equal(invalid.getSnapshot(), null);
  assert.equal(scrubbed, false);
});
