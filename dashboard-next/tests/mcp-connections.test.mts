import assert from "node:assert/strict";
import test from "node:test";
// Keep state verification independent of React and network doubles.
const connectionState = await import("../lib/mcp/connection-state.ts").catch(() => ({}));
const { mcpTarget } = await import("../lib/mcp/proxy-policy.ts");
const id = "10000000-0000-4000-8000-000000000001";
const request = { id, action: "confirm", expectedVersion: 0,
  storeIds: ["10000000-0000-4000-8000-000000000002"], scopes: ["workflow:read"] };

test("confirmation requires the exact grant, Store and scope receipt", () => {
  assert.equal(typeof connectionState.connectionReceipt, "function");
  const valid = { id, version: 1, revoked: false, expires_at: new Date(Date.now() + 86400000).toISOString(), store_ids: request.storeIds, scopes: request.scopes };
  assert.equal(connectionState.connectionReceipt(request, valid), true);
  for (const bad of [{ ...valid, id: "another" }, { ...valid, store_ids: [] },
    { ...valid, scopes: [...valid.scopes, "runtime:control"] }, { ...valid, revoked: true }, { ok: true }]) {
    assert.equal(connectionState.connectionReceipt(request, bad), false);
  }
});

test("revocation accepts only the same grant's advanced revoked version", () => {
  assert.equal(typeof connectionState.connectionReceipt, "function");
  const revoke = { ...request, action: "revoke", expectedVersion: 1 };
  assert.equal(connectionState.connectionReceipt(revoke, { id, version: 2, revoked: true }), true);
  assert.equal(connectionState.connectionReceipt(revoke, { id, version: 1, revoked: true }), false);
  assert.equal(connectionState.connectionReceipt(revoke, { id, version: 2, revoked: false }), false);
});

test("refresh and an absent or stale receipt preserve an unknown write", () => {
  assert.equal(typeof connectionState.reconcileConnection, "function");
  const pending = { request, status: "unknown" };
  assert.equal(connectionState.reconcileConnection(pending, null), pending);
  assert.equal(connectionState.reconcileConnection(pending, { id, version: 1, revoked: true }), pending);
  const settled = connectionState.reconcileConnection(pending, { id, version: 1, revoked: false, expires_at: new Date(Date.now() + 86400000).toISOString(),
    store_ids: request.storeIds, scopes: request.scopes });
  assert.equal(settled.status, "confirmed");
});

test("gateway links permit only HTTPS and isolate technical identifiers", () => {
  assert.equal(typeof connectionState.gatewayDashboardUrl, "function");
  assert.equal(connectionState.gatewayDashboardUrl("javascript:alert(1)", id), null);
  assert.equal(connectionState.gatewayDashboardUrl("https://user:secret@gateway.test", id), null);
  assert.equal(connectionState.gatewayDashboardUrl("http://gateway.test", id), null);
  assert.equal(connectionState.gatewayDashboardUrl("https://gateway.test", id), "https://gateway.test/dashboard?workspace=" + id);
});

test("the signed management proxy admits only closed consent and withdrawal routes", () => {
  assert.equal(mcpTarget("POST", ["pairings", id, "confirm"])?.target, "/mcp/pairings/" + id + "/confirm");
  assert.equal(mcpTarget("POST", ["owned-grants", id, "revoke"])?.target, "/account/mcp-grants/" + id + "/revoke");
  for (const path of [["operations", id, "approve"], ["operations", id, "deny"], ["commit"],
    ["pairings", "../account", "confirm"], ["grants", id, "edit"], ["pairings", id, "confirm", "extra"]]) {
    assert.equal(mcpTarget("POST", path), null);
  }
});
