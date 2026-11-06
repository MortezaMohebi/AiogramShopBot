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
