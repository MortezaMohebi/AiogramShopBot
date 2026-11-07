import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const root = fileURLToPath(new URL("..", import.meta.url));

function route() {
  const source = readFileSync(path.join(root, "app/api/admin/data-models/[model]/[action]/route.ts"), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const loaded = { exports: {} as Record<string, unknown> };
  const calls: string[] = [];
  runInNewContext(code, {
    module: loaded, exports: loaded.exports, Set, BigInt, URLSearchParams, Response,
    require: (name: string) => {
      if (name === "next/server") return {
        NextResponse: { json: (body: unknown, init: { status: number }) => ({ body, status: init.status }) },
      };
      if (name === "@/lib/bridge") return {
        ApiError: class extends Error {},
        bridgeResponse: async (url: string) => { calls.push(url); return { body: "selected" }; },
      };
      if (name === "@/lib/session") return { readSession: async () => ({ id: 1 }) };
      throw new Error(`Unexpected import ${name}`);
    },
  });
  return {
    get: loaded.exports.GET as (request: unknown, context: unknown) => Promise<Response & { status: number }>,
    calls,
  };
}

test("selected update export forwards only selected IDs and fields", async () => {
  const { get, calls } = route();
  const response = await get({ nextUrl: new URL("http://test/export?format=xlsx&update_compatible=true&fields=price_irr&ids=8&ids=12") },
    { params: Promise.resolve({ model: "products", action: "export" }) });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, ["/data-models/products/export?format=xlsx&fields=price_irr&ids=8&ids=12&update_compatible=true"]);
});

test("duplicate selection and template selection are rejected before the bridge", async () => {
  for (const [action, query] of [
    ["export", "format=csv&ids=8&ids=8"],
    ["template", "format=csv&ids=8"],
  ]) {
    const { get, calls } = route();
    const response = await get({ nextUrl: new URL(`http://test/${action}?${query}`) },
      { params: Promise.resolve({ model: "products", action }) });
    assert.equal(response.status, 400);
    assert.deepEqual(calls, []);
  }
});
