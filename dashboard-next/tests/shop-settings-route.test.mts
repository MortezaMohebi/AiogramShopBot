/**
 * Execute the real BFF route with Web Request/Response streams.
 * Only Next's JSON response factory and external identity/FastAPI calls are
 * replaced. This is a route unit suite, NOT a PostgreSQL or browser E2E test.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const sourcePath = fileURLToPath(new URL("../app/api/admin/shop-settings/route.ts", import.meta.url));
const code = ts.transpileModule(readFileSync(sourcePath, "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  fileName: sourcePath,
}).outputText;
const valid = {
  brand_name: "فروشگاه آزمون", welcome_message: "خوش آمدید",
  faq_text: "پرسش آزمایشی", support_url: "https://example.test/help",
};
type Settings = typeof valid;
class ApiError extends Error {
  status: number;
  constructor(status: number) { super("private-upstream-details"); this.status = status; }
}

function fixture(options: {
  csrf?: boolean; session?: boolean; role?: string; backendStatus?: number;
  readback?: "mismatch" | "offline";
} = {}) {
  const calls: { path: string; method: string; data: unknown }[] = [];
  let persisted: Settings | null = null;
  const evaluatedModule = { exports: {} as { POST: (request: Request) => Promise<Response> } };
  const deps: Record<string, unknown> = {
    "node:crypto": { randomUUID },
    "next/server": { NextResponse: { json: Response.json.bind(Response) } },
    "@/lib/login-challenge": {
      safeLoginFetchMetadata: () => true,
      verifyLoginChallenge: () => options.csrf !== false,
    },
    "@/lib/session": { readSession: async () => options.session === false ? null : { id: 7, version: 3 } },
    "@/lib/bridge": {
      ApiError,
      bridgeFetch: async (path: string, method: string, data: unknown, identity: unknown) => {
        assert.deepEqual(JSON.parse(JSON.stringify(identity)), { id: 7, version: 3 });
        calls.push({ path, method, data });
        if (options.backendStatus) throw new ApiError(options.backendStatus);
        if (path === "/auth/me" && method === "GET") {
          return { id: 7, username: "fixture-user", role: options.role ?? "superadmin" };
        }
        if (path === "/settings" && method === "PATCH") {
          persisted = JSON.parse(JSON.stringify(data)) as Settings;
          return { ok: true };
        }
        if (path === "/settings" && method === "GET") {
          if (options.readback === "offline") throw new Error("secret-upstream-connection-string");
          return options.readback === "mismatch" ? { ...persisted, brand_name: "different" } : persisted;
        }
        throw new Error(`Unexpected upstream request: ${method} ${path}`);
      },
    },
  };
  runInNewContext(code, {
    exports: evaluatedModule.exports, module: evaluatedModule,
    require: (id: string) => {
      if (!(id in deps)) throw new Error(`Unmocked dependency: ${id}`);
      return deps[id];
    },
    Buffer, URL, TextDecoder, ReadableStream,
    console: { warn: () => undefined },
  }, { filename: sourcePath });
  return { POST: evaluatedModule.exports.POST, calls, saved: () => persisted };
}

function request(payload: unknown, headers: Record<string, string> = {}) {
  return new Request("http://localhost/api/admin/shop-settings", {
    method: "POST", body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json", ...headers },
  });
}

async function expectCode(response: Response, status: number, code: string) {
  assert.equal(response.status, status);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.match(response.headers.get("content-type") ?? "", /application\/json/);
  const body = await response.json();
  assert.equal(body.ok, false);
  assert.equal(body.code, code);
  assert.match(body.requestId, /^[0-9a-f-]{36}$/);
  assert.ok(!JSON.stringify(body).includes("secret-upstream"));
}

test("valid Persian settings are confirmed by an independent upstream read", async () => {
  const route = fixture();
  const response = await route.POST(request(valid));
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).settings, valid);
  assert.deepEqual(route.calls.map(({ path, method }) => [method, path]), [
    ["GET", "/auth/me"], ["PATCH", "/settings"], ["GET", "/settings"],
  ]);
});

test("a 20,000-character Persian FAQ fits the advertised field limits", async () => {
  const route = fixture();
  const payload = { ...valid, welcome_message: "س".repeat(4096), faq_text: "پ".repeat(20_000) };
  const response = await route.POST(request(payload));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).settings.faq_text, payload.faq_text);
});

test("chunked Persian JSON can be split inside a UTF-8 character", async () => {
  const route = fixture();
  const bytes = new TextEncoder().encode(JSON.stringify(valid));
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  });
  const req = new Request("http://localhost/api/admin/shop-settings", {
    method: "POST", body: stream, duplex: "half", headers: { "Content-Type": "application/json" },
  } as RequestInit);
  assert.equal((await route.POST(req)).status, 200);
  assert.deepEqual(route.saved(), valid);
});

test("oversized streamed body is cancelled before upstream mutation", async () => {
  const route = fixture();
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) { controller.enqueue(new Uint8Array(270_000)); },
    cancel() { cancelled = true; },
  });
  const req = new Request("http://localhost/api/admin/shop-settings", {
    method: "POST", body: stream, duplex: "half", headers: { "Content-Type": "application/json" },
  } as RequestInit);
  await expectCode(await route.POST(req), 413, "invalid_request");
  assert.equal(cancelled, true);
  assert.equal(route.calls.length, 0);
});

test("application/jsonp is not accepted as JSON", async () => {
  const route = fixture();
  await expectCode(await route.POST(request(valid, { "Content-Type": "application/jsonp" })), 415, "invalid_request");
  assert.equal(route.calls.length, 0);
});

test("read-back failure after a successful write reports an unverified save", async () => {
  const route = fixture({ readback: "offline" });
  await expectCode(await route.POST(request(valid)), 503, "save_failed");
  assert.deepEqual(route.saved(), valid);
});

test("a read-back mismatch must never show success", async () => {
  const route = fixture({ readback: "mismatch" });
  await expectCode(await route.POST(request(valid)), 503, "save_failed");
});

for (const [name, options, status, code] of [
  ["missing CSRF", { csrf: false }, 403, "security_check_failed"],
  ["expired browser session", { session: false }, 401, "session_expired"],
  ["non-superadmin role", { role: "content" }, 403, "permission_denied"],
  ["revoked backend session", { backendStatus: 401 }, 401, "session_expired"],
  ["backend permission rejection", { backendStatus: 403 }, 403, "permission_denied"],
  ["backend validation rejection", { backendStatus: 422 }, 422, "invalid_request"],
  ["backend outage", { backendStatus: 500 }, 503, "service_unavailable"],
] as const) {
  test(`${name} does not mutate settings`, async () => {
    const route = fixture(options);
    await expectCode(await route.POST(request(valid)), status, code);
    assert.equal(route.saved(), null);
  });
}

for (const [name, value] of [
  ["unknown settings", { ...valid, TOKEN: "must-not-be-saved" }],
  ["insecure support link", { ...valid, support_url: "http://example.test" }],
  ["credential-bearing support link", { ...valid, support_url: "https://user:pass@example.test/" }],
  ["oversized FAQ", { ...valid, faq_text: "x".repeat(20_001) }],
  ["array body", []],
  ["null body", null],
] as const) {
  test(`${name} is rejected before upstream work`, async () => {
    const route = fixture();
    await expectCode(await route.POST(request(value)), 422, "invalid_request");
    assert.equal(route.calls.length, 0);
  });
}
