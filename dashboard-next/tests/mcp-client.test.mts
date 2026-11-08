import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const id = "10000000-0000-4000-8000-000000000001";
function client(fetcher: typeof fetch, challenge: () => Promise<string>) {
  const source = readFileSync(new URL("../lib/mcp/client.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText;
  const exports: Record<string, unknown> = {};
  vm.runInNewContext(compiled, { exports, fetch: fetcher, AbortSignal,
    require: (name: string) => {
      assert.equal(name, "@/lib/browser-challenge");
      return { requestBrowserChallenge: challenge };
    },
  });
  return exports as { mcpMutation: (path: string) => Promise<Response> };
}

test("native consent obtains CSRF before its one exact empty-body POST", async () => {
  const calls: string[] = [];
  const api = client(async (url, init) => {
    calls.push(String(url));
    assert.equal(init?.method, "POST");
    assert.equal(init?.body, "{}");
    assert.equal(new Headers(init?.headers).get("x-shop-login-challenge"), "fresh-test-challenge");
    return Response.json({ id, version: 1 });
  }, async () => { calls.push("challenge");return "fresh-test-challenge"; });
  await api.mcpMutation(`/pairings/${id}/confirm`);
  assert.deepEqual(calls, ["challenge", `/api/admin/mcp/pairings/${id}/confirm`]);
});

test("unavailable CSRF never dispatches withdrawal", async () => {
  let writes = 0;
  const api = client(async () => { writes++;return Response.json({}); }, async () => { throw new Error("unavailable"); });
  await assert.rejects(api.mcpMutation(`/owned-grants/${id}/revoke`));
  assert.equal(writes, 0);
});

test("a lost withdrawal response is never automatically replayed", async () => {
  let writes = 0;
  const api = client(async () => { writes++;throw new TypeError("lost"); }, async () => "fresh-test-challenge");
  await assert.rejects(api.mcpMutation(`/owned-grants/${id}/revoke`));
  assert.equal(writes, 1);
});
