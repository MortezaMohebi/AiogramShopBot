import assert from "node:assert/strict";
import test from "node:test";
import { codespaceActionHeaders } from "../lib/codespace-action-origin.ts";
const origin = "https://example-space-3006.app.github.dev";
function headers(extra: Record<string, string> = {}) {
  return new Headers({ origin: "http://localhost:3006", "x-forwarded-host": new URL(origin).host,
    "sec-fetch-site": "same-origin", "next-action": "test-action", ...extra });
}
test("restore public Origin only for a verified same-origin Codespaces action", () => {
  assert.equal(codespaceActionHeaders("POST", headers(), origin).get("origin"), origin);
});
test("restore the HTTPS loopback Origin emitted by the Codespaces proxy", () => {
  const input = headers({ origin: "https://localhost:3006" });
  const restored = codespaceActionHeaders("POST", input, origin);
  assert.equal(restored.get("origin"), origin);
  assert.equal(input.get("origin"), "https://localhost:3006");
  assert.equal(restored.get("x-forwarded-host"), new URL(origin).host);
});
for (const extra of [
  { origin: "https://localhost:3005" },
  { origin: "https://localhost:3006.attacker.test" },
  { origin: "https://127.0.0.1:3006" },
  { origin: "https://localhost:3006", "sec-fetch-site": "cross-site" },
  { origin: "https://localhost:3006", "x-forwarded-host": "attacker.test" },
]) {
  test(`keep untrusted HTTPS loopback metadata unchanged: ${JSON.stringify(extra)}`, () => {
    const input = headers(extra);
    assert.equal(codespaceActionHeaders("POST", input, origin), input);
  });
}
for (const extra of [{ "sec-fetch-site": "cross-site" }, { "sec-fetch-site": "same-site" },
  { origin: "https://attacker.test" }, { "x-forwarded-host": "other.app.github.dev" },
  { origin: "http://localhost:3005" }, { "next-action": "" }]) {
  test(`leave untrusted headers unchanged: ${JSON.stringify(extra)}`, () => {
    const input = headers(extra);
    assert.equal(codespaceActionHeaders("POST", input, origin).get("origin"), input.get("origin"));
  });
}
test("leave other deployments and GET requests unchanged", () => {
  for (const [method, configured] of [["GET", origin], ["POST", "https://shop.test"], ["POST", ""]]) {
    assert.equal(codespaceActionHeaders(method, headers(), configured).get("origin"), "http://localhost:3006");
  }
});
