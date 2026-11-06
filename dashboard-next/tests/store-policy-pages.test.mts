/** Exercise actual protected pages when the current Store differs from the default. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const defaultId = "10000000-0000-4000-8000-000000000001";
const currentId = "10000000-0000-4000-8000-000000000002";
const otherId = "10000000-0000-4000-8000-000000000003";
const stores = [defaultId, currentId, otherId].map((id, index) => ({
  id, name: `STORE_${index + 1}`, slug: `store-${index + 1}`, state: "active",
  access_level: "manager", active: id === currentId, current: id === currentId,
}));
const context = {
  staff_id: 1, version: 1, preference_version: 1,
  current_store_id: currentId, default_store_id: defaultId,
  active_store_ids: [currentId], allowed_store_ids: stores.map(store => store.id), stores,
};
const Box = ({ children }: { children?: ReactNode }) => createElement("div", null, children);
const noop = async () => { throw Error("mutations_are_not_part_of_a_read_test"); };

function fixture(page: "stores" | "payment-accounts", {
  active = [currentId], role = "superadmin", failure,
}: { active?: string[]; role?: string; failure?: Error } = {}) {
  const calls: string[] = [];
  const selected = { ...context, active_store_ids: active };
  async function read(path: string) {
    calls.push(path);
    if (path === "/store-context") return selected;
    if (path === "/stores") return { items: stores, default_store_id: defaultId };
    const match = path.match(/^\/stores\/([^/]+)\/(commerce|customer-menu|checkout-policy|payment-accounts)$/);
    assert(match, `Unexpected read ${path}`);
    if (!active.includes(match[1])) throw Object.assign(Error("store_access_denied"), { status: 403 });
    if (failure) throw failure;
    if (match[2] === "payment-accounts") return { items: [] };
    if (match[2] === "commerce") return { version: 1, cart_scope: "bot", credit_scope: "identity" };
    return {};
  }
  const deps: Record<string, unknown> = {
    "react/jsx-runtime": jsx,
    "next/link": { default: ({ href, children }: { href: string; children: ReactNode }) => createElement("a", { href }, children) },
    "next/navigation": {
      notFound() { throw Object.assign(Error("not_found"), { status: 404 }); },
      redirect(destination: string) { throw Object.assign(Error("redirect"), { destination }); },
    },
    "lucide-react": { CreditCard: Box, KeyRound: Box },
    "@/components/blocks/page-heading": { PageHeading: ({ title }: { title: string }) => createElement("h1", null, title) },
    "@/components/ui/button": { Button: Box },
    "@/components/ui/input": { Input: (props: Record<string, unknown>) => createElement("input", props) },
    "@/components/ui/card": { Card: Box, CardContent: Box, CardHeader: Box, CardTitle: Box },
    "@/components/blocks/customer-experience-policy-panel": { CustomerExperiencePolicyPanel: ({ id }: { id: string }) => createElement("span", null, id) },
    "@/lib/bridge": { adminFetch: read, currentStaff: async () => ({ role }) },
    "./actions": { createPaymentAccount: noop, setPaymentAccountState: noop },
    "./commerce-actions": { saveStoreCommercePolicy: noop },
  };
  const code = ts.transpileModule(readFileSync(new URL(`../app/(console)/${page}/page.tsx`, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const evaluated = { exports: {} as { default: (props: unknown) => Promise<ReactNode> } };
  runInNewContext(code, { module: evaluated, exports: evaluated.exports, require: (id: string) => {
    assert(id in deps, `Unexpected module ${id}`);
    return deps[id];
  } });
  return { calls, async render(query = {}) {
    return renderToStaticMarkup(await evaluated.exports.default({ searchParams: Promise.resolve(query) }));
  } };
}

test("payment accounts read the current selected Store even when the default is inactive", async () => {
  const f = fixture("payment-accounts");
  const html = await f.render();
  assert(html.includes("STORE_2"));
  assert(!html.includes("STORE_1"));
  assert.deepEqual(f.calls, ["/store-context", `/stores/${currentId}/payment-accounts`]);
});

test("a stale payment Store query redirects without reading an inactive Store", async () => {
  const f = fixture("payment-accounts");
  await assert.rejects(f.render({ store_id: defaultId }), (error: unknown) =>
    typeof error === "object" && error !== null && "destination" in error && error.destination === "/payment-accounts");
  assert.deepEqual(f.calls, ["/store-context"]);
});

test("an explicitly selected active payment Store remains readable", async () => {
  const f = fixture("payment-accounts", { active: [defaultId, currentId] });
  await f.render({ store_id: defaultId });
  assert(f.calls.includes(`/stores/${defaultId}/payment-accounts`));
});

test("Stores reads policies only for the session's active Stores", async () => {
  const f = fixture("stores");
  const html = await f.render();
  assert(html.includes("STORE_2"));
  assert(!html.includes("STORE_1"));
  assert(!html.includes("STORE_3"));
  assert.deepEqual(new Set(f.calls), new Set(["/store-context", ...["commerce", "customer-menu", "checkout-policy"].map(part => `/stores/${currentId}/${part}`)]));
});

test("Stores preserves a selected multi-Store read without including other grants", async () => {
  const f = fixture("stores", { active: [defaultId, currentId] });
  const html = await f.render();
  assert(html.includes("STORE_1") && html.includes("STORE_2"));
  assert(!html.includes("STORE_3"));
});

for (const page of ["stores", "payment-accounts"] as const) {
  test(`${page} keeps the existing role boundary before any Store read`, async () => {
    const f = fixture(page, { role: "viewer" });
    await assert.rejects(f.render(), (error: unknown) => typeof error === "object" && error !== null && "status" in error && error.status === 404);
    assert.deepEqual(f.calls, []);
  });
  test(`${page} does not disguise a genuine backend failure as empty data`, async () => {
    const failure = Object.assign(Error("service_unavailable"), { status: 503 });
    const f = fixture(page, { failure });
    await assert.rejects(f.render(), error => error === failure);
  });
}
