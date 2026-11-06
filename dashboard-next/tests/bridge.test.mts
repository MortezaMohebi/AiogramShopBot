/** Real HMAC bridge behavior; only network transport and Next session are doubled. */
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const file = fileURLToPath(new URL("../lib/bridge.ts", import.meta.url));
const code = ts.transpileModule(readFileSync(file, "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  fileName: file,
}).outputText;
const key = "synthetic-signing-key-that-is-not-a-real-secret";
const identity = { id: 11, version: 2 };
type Bridge = {
  bridgeFetch: (p: string, m: string, d: unknown, i: unknown, t?: number) => Promise<unknown>;
  adminFetch: (p: string, method?: string, data?: unknown) => Promise<unknown>;
  optionalStoreRead: (p: string) => Promise<unknown>;
};

function load(send: typeof fetch, authenticated = true) {
  const evaluatedModule = { exports: {} as Bridge };
  const logs: unknown[][] = [];
  const deps: Record<string, unknown> = {
    "server-only": {}, "node:crypto": crypto,
    "next/navigation": {
      redirect: (destination: string) => { throw Object.assign(new Error("redirect"), { destination }); },
    },
    "@/lib/session": { readSession: async () => authenticated ? identity : null },
  };
  runInNewContext(code, {
    exports: evaluatedModule.exports, module: evaluatedModule,
    require: (id: string) => {
      if (!(id in deps)) throw new Error(`Unexpected dependency ${id}`);
      return deps[id];
    },
    process: { env: { SHOP_FASTAPI_INTERNAL_URL: "http://backend.invalid:5000", NEXT_ADMIN_BRIDGE_SECRET: key } },
    Buffer, URL, Uint8Array, AbortSignal, Response, fetch: send,
    console: { warn: (...values: unknown[]) => logs.push(values) },
  }, { filename: file });
  return { ...evaluatedModule.exports, logs };
}

function hasStatus(status: number) {
  return (error: unknown) => typeof error === "object" && error !== null
    && "status" in error && error.status === status;
}

test("HMAC covers exact UTF-8 body, identity, method and full target", async () => {
  let count = 0;
  const bridge = load(async (url, init) => {
    count++;
    assert.equal(String(url), "http://backend.invalid:5000/internal/admin/v1/settings?check=1");
    assert.equal(init?.method, "PATCH");
    assert.equal(init?.redirect, "error");
    assert.equal(init?.cache, "no-store");
    const body = Buffer.from(init?.body as Uint8Array);
    assert.deepEqual(JSON.parse(body.toString("utf8")), { brand_name: "فروشگاه" });
    const headers = new Headers(init?.headers);
    const expected = crypto.createHmac("sha256", key).update([
      headers.get("x-shop-time"), "PATCH", "/internal/admin/v1/settings?check=1",
      crypto.createHash("sha256").update(body).digest("hex"), "11", "2",
    ].join("\n")).digest("hex");
    assert.equal(headers.get("x-shop-signature"), expected);
    return Response.json({ ok: true });
  });
  assert.deepEqual(await bridge.bridgeFetch("/settings?check=1", "PATCH", { brand_name: "فروشگاه" }, identity), { ok: true });
  assert.equal(count, 1);
});

test("network failure produces a safe diagnostic without logging its secret URI", async () => {
  const bridge = load(async () => { throw new Error("https://private.invalid/?token=DO_NOT_LOG"); });
  await assert.rejects(bridge.bridgeFetch("/overview?filter=PRIVATE_QUERY", "GET", null, identity), hasStatus(503));
  const logs = JSON.stringify(bridge.logs);
  assert.ok(logs.includes("/internal/admin/v1/overview"));
  assert.ok(logs.includes("network"));
  for (const secret of [key, "DO_NOT_LOG", "PRIVATE_QUERY", "private.invalid"]) assert.ok(!logs.includes(secret));
});

test("HTTP failure logs status and route but not backend error contents", async () => {
  const bridge = load(async () => Response.json({ detail: "DB_PASSWORD=PRIVATE" }, { status: 500 }));
  await assert.rejects(bridge.bridgeFetch("/overview", "GET", null, identity), hasStatus(500));
  const logs = JSON.stringify(bridge.logs);
  assert.ok(logs.includes("500"));
  assert.ok(logs.includes("overview"));
  assert.ok(!logs.includes("DB_PASSWORD"));
});

test("expired backend identity redirects a protected data read to login", async () => {
  const bridge = load(async () => Response.json({ detail: "Session revoked" }, { status: 401 }));
  await assert.rejects(bridge.adminFetch("/settings"), (error: unknown) =>
    typeof error === "object" && error !== null && "destination" in error
      && error.destination === "/login?expired=1");
});

test("role rejection remains a 403 instead of becoming a login redirect", async () => {
  const bridge = load(async () => Response.json({ detail: "Permission denied" }, { status: 403 }));
  await assert.rejects(bridge.adminFetch("/settings"), hasStatus(403));
});

test("parallel protected page and layout reads both redirect mandatory MFA enrollment", async () => {
  const bridge = load(async () => Response.json({ detail: "mfa_enrollment_required" }, { status: 428 }));
  const results = await Promise.allSettled([bridge.adminFetch("/store-context"), bridge.adminFetch("/overview")]);
  for (const result of results) {
    assert.equal(result.status, "rejected");
    assert.equal((result as PromiseRejectedResult).reason.destination, "/account?enroll=1");
  }
});

test("unrelated 428 and enrollment write failures remain errors", async () => {
  const bridge = load(async () => Response.json({ detail: "reauthentication_required" }, { status: 428 }));
  await assert.rejects(bridge.adminFetch("/settings"), hasStatus(428));
  const enrollment = load(async () => Response.json({ detail: "mfa_enrollment_required" }, { status: 428 }));
  await assert.rejects(enrollment.adminFetch("/settings", "POST", {}), hasStatus(428));
  await assert.rejects(enrollment.adminFetch("/account"), hasStatus(428));
});

test("malformed upstream success body is reported as protocol error", async () => {
  const bridge = load(async () => new Response("<html>proxy failure</html>", { status: 200 }));
  await assert.rejects(bridge.bridgeFetch("/overview", "GET", null, identity), hasStatus(502));
  assert.ok(JSON.stringify(bridge.logs).includes("invalid_json"));
});

test("explicit JSON request deadline aborts the transport and never retries", async () => {
  let count = 0;
  const bridge = load(async (_url, init) => {
    count++;
    return new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(Response.json({ ok: true })), 120);
      init?.signal?.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(init.signal?.reason);
      }, { once: true });
    });
  });
  await assert.rejects(bridge.bridgeFetch("/bot-connections/probe", "GET", null, identity, 5), hasStatus(504));
  assert.equal(count, 1);
});

test("missing browser session prevents any backend request", async () => {
  let count = 0;
  const bridge = load(async () => { count++; return Response.json({ ok: true }); }, false);
  await assert.rejects(bridge.adminFetch("/overview"), (error: unknown) =>
    typeof error === "object" && error !== null && "destination" in error && error.destination === "/login");
  assert.equal(count, 0);
});

test("Runtime replay denial preserves its safe code and discards private upstream fields", async () => {
  for (const [detail, expected] of [
    ["runtime_delivery_replay_forbidden", "runtime_delivery_replay_forbidden"],
    ["PRIVATE_PROVIDER_DETAIL", undefined],
  ] as const) {
    let calls = 0;
    const bridge = load(async () => {
      calls++;
      return Response.json({ detail, private: "PRIVATE_PROVIDER_FIELD" }, { status: 409 });
    });
    await assert.rejects(
      bridge.bridgeFetch("/workflow-runtime/outbox/fixture/retry", "POST", {}, identity),
      (error: unknown) => {
        assert.ok(hasStatus(409)(error));
        assert.equal((error as { code?: string }).code, expected);
        return true;
      },
    );
    assert.equal(calls, 1);
    const logs = JSON.stringify(bridge.logs);
    for (const privateValue of ["PRIVATE_PROVIDER_DETAIL", "PRIVATE_PROVIDER_FIELD", key]) {
      assert.ok(!logs.includes(privateValue));
    }
  }
});


test("expected Store restriction becomes unavailable without exposing raw errors",async()=>{
  const bridge=load(async()=>Response.json({detail:"store_scope_not_supported"},{status:409}));
  assert.equal(await bridge.optionalStoreRead("/channel-features"),null);
});
for(const [status,detail] of [[403,"permission_denied"],[409,"configuration_changed"],[500,"PRIVATE_DATABASE_ERROR"]] as const) {
  test(`optional Store read preserves unrelated failure ${status}/${detail}`,async()=>{
    const bridge=load(async()=>Response.json({detail},{status}));
    await assert.rejects(bridge.optionalStoreRead("/channel-features"),hasStatus(status));
  });
}
