/** Real allowlisted BFF handler; only session, CSRF and signed transport are replaced. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { randomUUID } from "node:crypto";
import ts from "typescript";
const code = ts.transpileModule(
  readFileSync(
    new URL("../app/api/admin/workflow-runtime/[[...path]]/route.ts", import.meta.url),
    "utf8",
  ),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  },
).outputText;
const id = "f423a748-9c8c-4065-9ece-37d132002677";
function fixture(csrf = true, session = true, metadata = true) {
  const calls: { path: string; method: string; body: unknown }[] = [];
  const evaluatedModule = {
    exports: {} as Record<
      string,
      (
        r: Request,
        c: { params: Promise<{ path?: string[] }> },
      ) => Promise<Response>
    >,
  };
  class ApiError extends Error {}
  const deps: Record<string, unknown> = {
    "node:crypto": { randomUUID },
    "next/server": { NextResponse: { json: Response.json.bind(Response) } },
    "@/lib/session": {
      readSession: async () => (session ? { id: 7, version: 1 } : null),
    },
    "@/lib/login-challenge": {
      safeLoginFetchMetadata: () => metadata,
      verifyLoginChallenge: () => csrf,
    },
    "@/lib/bridge": {
      ApiError,
      bridgeResponse: async (
        path: string,
        method: string,
        body: string | null,
      ) => {
        calls.push({ path, method, body: body ? JSON.parse(body) : null });
        return Response.json({ id, revision: 2 });
      },
    },
  };
  runInNewContext(code, {
    module: evaluatedModule,
    exports: evaluatedModule.exports,
    require: (k: string) => {
      assert.ok(k in deps, k);
      return deps[k];
    },
    Buffer,
    URL,
    TextDecoder,
    console: { warn: () => {} },
    Response,
  });
  return { route: evaluatedModule.exports, calls };
}
async function request(
  method: string,
  path: string[],
  body: unknown = {},
  query = "",
  options: { csrf?: boolean; session?: boolean; metadata?: boolean } = {},
) {
  const f = fixture(options.csrf, options.session, options.metadata);
  const r = new Request(
    `https://shop.test/api/admin/workflow-runtime/${path.join("/")}${query}`,
    {
      method,
      headers: method === "GET" ? {} : { "content-type": "application/json" },
      body: method === "GET" ? undefined : JSON.stringify(body),
    },
  );
  const response = await f.route[method](r, {
    params: Promise.resolve({ path }),
  });
  return { response, calls: f.calls };
}
test("POST signs only the closed runtime gate route", async () => {
  const payload = {
    bot_id: id, expected_version: 2, enabled: false, killed: true, operation_id: id,
  };
  const r = await request("POST", ["gates"], payload);
  assert.equal(r.response.status, 200);
  assert.equal(r.calls[0].path, "/workflow-runtime/gates");
  assert.deepEqual(JSON.parse(JSON.stringify(r.calls[0].body)), payload);
});
test("GET forwards only the runtime read allowlist", async () => {
  const r = await request("GET", ["runs"], {}, "?status=failed&page=2&workflow_id=" + id);
  assert.equal(r.response.status, 200);
  assert.equal(r.calls[0].path, "/workflow-runtime/runs?status=failed&page=2&workflow_id=" + id);
  assert.equal(r.response.headers.get("cache-control"), "no-store");
});
for (const path of [[], ["publications"], ["bindings"], ["runs"], ["runs", id], ["outbox"], ["history"]])
  test(`runtime read ${path.join("/") || "overview"}`, async () => {
    const r = await request("GET", path);
    assert.equal(r.response.status, 200);
  });
for (const path of [["publications", "preview"], ["publications", "activate"], ["publications", id, "retire"], ["runs", id, "recover"], ["actions", id, "approve"], ["outbox", id, "retry"]])
  test(`runtime mutation ${path.join("/")}`, async () => {
    const r = await request("POST", path);
    assert.equal(r.response.status, 200);
    assert.equal(r.calls.length, 1);
  });
for (const [name, path, query] of [
  ["arbitrary admin route", ["..", "staff"], ""],
  ["encoded traversal", ["%2e%2e"], ""],
  ["unexpected query", [id], "?token=secret"],
  ["live execute", ["invoke"], ""],
  ["unbounded route", ["runs", id, "events"], ""],
  ["duplicate page", ["runs"], "?page=1&page=2"],
  ["embedded slash", ["runs", id + "/recover"], ""],
  ["wrong query", ["bindings"], "?status=active"],
] as const)
  test(name, async () => {
    const r = await request("GET", [...path], {}, query);
    assert.equal(r.response.status, 404);
    assert.equal(r.calls.length, 0);
  });
for (const [name, options, status] of [
  ["CSRF", { csrf: false }, 403],
  ["session", { session: false }, 401],
] as const)
  test(`missing ${name} cannot mutate`, async () => {
    const r = await request("POST", ["gates"], {}, "", options);
    assert.equal(r.response.status, status);
    assert.equal(r.calls.length, 0);
  });
test("oversized chunked JSON is cancelled before signed transport", async () => {
  const f = fixture();
  let cancelled = false;
  const stream = new ReadableStream({
    pull(c) {
      c.enqueue(new Uint8Array(270000));
    },
    cancel() {
      cancelled = true;
    },
  });
  const r = new Request("https://shop.test/api/admin/workflow-runtime", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: stream,
    duplex: "half",
  } as RequestInit);
  const response = await f.route.POST(r, {
    params: Promise.resolve({ path: ["gates"] }),
  });
  assert.equal(response.status, 413);
  assert.equal(cancelled, true);
  assert.equal(f.calls.length, 0);
});

test("cross-site Origin metadata cannot sign a mutation even with a valid challenge", async () => {
  const r = await request("POST", ["gates"], {}, "", {metadata:false});
  assert.equal(r.response.status,403);
  assert.equal(r.calls.length,0);
});
for(const [body,status,contentType] of [["[]",422,"application/json"],["{",422,"application/json"],["{}",415,"text/plain"]] as const)
 test(`runtime rejects invalid body ${body} ${contentType}`, async()=>{
  const f=fixture();
  const r=new Request("https://shop.test/api/admin/workflow-runtime/gates",{method:"POST",headers:{"content-type":contentType},body});
  const response=await f.route.POST(r,{params:Promise.resolve({path:["gates"]})});
  assert.equal(response.status,status);assert.equal(f.calls.length,0);
 });
