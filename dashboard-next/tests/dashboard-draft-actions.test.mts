import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

function actions(page: string, rejection?: number, signedIn = true) {
  const requests: unknown[][] = [];
  const revalidated: string[] = [];
  const mod = { exports: {} as Record<string, (data: FormData) => Promise<unknown>> };
  const source = readFileSync(new URL(`../app/(console)/${page}/actions.ts`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  const helper = ts.transpileModule(readFileSync(new URL("../lib/draft-mutation.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const deps: Record<string, unknown> = {
    "server-only": {},
    "next/cache": { revalidatePath: (path: string) => revalidated.push(path) },
    "next/navigation": { redirect: (path: string) => { throw new Error(path); } },
    "@/lib/session": { readSession: async () => signedIn ? { id: 1 } : null },
    "@/lib/bridge": { bridgeFetch: async (...args: unknown[]) => {
      requests.push(args);
      if (rejection) throw new Error("backend rejected request");
      return { ok: true };
    }},
    "@/lib/section-rpc-server": { sectionRpcError: () => rejection === 409 ? "conflict" : "outcome_unknown" },
  };
  const resolve = (name: string) => {
    assert(name in deps, name);
    return deps[name];
  };
  const transport = {};
  runInNewContext(helper, { exports: transport, require: resolve });
  deps["@/lib/draft-mutation"] = transport;
  runInNewContext(code, { exports: mod.exports, require: resolve });
  return { mod: mod.exports, requests, revalidated };
}

function fields(data: Record<string, string>) {
  const form = new FormData();
  Object.entries(data).forEach(([name, value]) => form.set(name, value));
  return form;
}

test("shipping draft edits an existing method and confirms without redirecting", async () => {
  const { mod, requests, revalidated } = actions("shipping");
  const result = await mod.saveShippingDraft(fields({ id: "12", name: "Test shipping", price_irr: "500" }));
  assert.equal(JSON.stringify(result), '{"ok":true,"data":null}');
  assert.equal(requests[0][0], "/shipping/12");
  assert.equal(requests[0][1], "PATCH");
  assert.deepEqual(revalidated, ["/shipping"]);
});

test("drafts cannot create a method or coupon with a missing or invalid ID", async () => {
  for (const [page, action] of [["shipping", "saveShippingDraft"], ["coupons", "saveCouponDraft"]]) {
    const { mod, requests } = actions(page);
    for (const id of ["", "../settings"]) {
      assert.equal(JSON.stringify(await mod[action](fields({ id }))), '{"ok":false,"code":"validation"}');
    }
    assert.deepEqual(requests, []);
  }
});

test("failed coupon draft returns its error without a success redirect or revalidation", async () => {
  const { mod, requests, revalidated } = actions("coupons", 409);
  const result = await mod.saveCouponDraft(fields({ id: "2", expires_at: "2027-01-01" }));
  assert.equal(JSON.stringify(result), '{"ok":false,"code":"conflict"}');
  assert.equal(requests[0][1], "PATCH");
  assert.equal((requests[0][2] as { expires_at: string }).expires_at, "2027-01-01T23:59:59+00:00");
  assert.deepEqual(revalidated, []);
});

test("creating a shipping method remains a separate explicit POST", async () => {
  const { mod, requests } = actions("shipping");
  await assert.rejects(mod.saveShipping(fields({ name: "New method" })), /shipping\?saved=1/);
  assert.equal(requests[0][0], "/shipping");
  assert.equal(requests[0][1], "POST");
});

test("expired sessions never send a draft to the administrative API", async () => {
  const { mod, requests, revalidated } = actions("shipping", undefined, false);
  const result = await mod.saveShippingDraft(fields({ id: "12" }));
  assert.equal(JSON.stringify(result), '{"ok":false,"code":"session_expired"}');
  assert.deepEqual(requests, []);
  assert.deepEqual(revalidated, []);
});

test("an uncertain write never confirms or retries the request", async () => {
  const { mod, requests, revalidated } = actions("shipping", 503);
  const result = await mod.saveShippingDraft(fields({ id: "12" }));
  assert.equal(JSON.stringify(result), '{"ok":false,"code":"outcome_unknown"}');
  assert.equal(requests.length, 1);
  assert.deepEqual(revalidated, []);
});
