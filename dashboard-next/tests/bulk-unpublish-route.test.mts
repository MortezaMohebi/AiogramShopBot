// Verify bounded bulk catalog requests before they reach the signed bridge.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { controlJson } from "../lib/control-request.ts";

const root = fileURLToPath(new URL("..", import.meta.url));

function loadRoute() {
  const filename = path.join(root, "app/api/admin/bulk-unpublish/route.ts");
  const code = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const evaluated = { exports: {} as Record<string, unknown> };
  const calls: Array<{ path: string; method: string; data: unknown }> = [];
  runInNewContext(code, {
    module: evaluated, exports: evaluated.exports, Buffer, Set, Number, Object, Array, JSON,
    console: { warn: () => undefined },
    require: (name: string) => {
      if (name === "node:crypto") return { randomUUID: () => "test-request" };
      if (name === "next/server") return {
        NextResponse: { json: (body: unknown, options?: { status?: number }) => ({
          body, status: options?.status ?? 200,
        }) },
      };
      if (name === "@/lib/bridge") return {
        ApiError: class extends Error {},
        bridgeFetch: async (route: string, method: string, data: unknown) => {
          calls.push({ path: route, method, data });
          return route === "/auth/me"
            ? { role: "content" }
            : { selected: 2, unpublished: 2 };
        },
      };
      if (name === "@/lib/login-challenge") return {
        safeLoginFetchMetadata: () => true,
        verifyLoginChallenge: () => true,
      };
      if (name === "@/lib/control-request") return { controlJson };
      if (name === "@/lib/session") return { readSession: async () => ({ id: 1 }) };
      throw new Error(`Unexpected import: ${name}`);
    },
  });
  return {
    post: evaluated.exports.POST as (request: unknown) => Promise<{ body: unknown; status: number }>,
    calls,
  };
}

function request(payload: unknown) {
  return new Request("http://offline.test/api/admin/bulk-unpublish", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

test("valid product selection uses one atomic backend route", async () => {
  const { post, calls } = loadRoute();
  const response = await post(request({ entity: "products", ids: [3, 4] }));
  assert.equal(response.status, 200);
  assert.deepEqual(JSON.parse(JSON.stringify(response.body)), {
    ok: true, selected: 2, unpublished: 2,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    { path: "/auth/me", method: "GET", data: null },
    { path: "/products/bulk-unpublish", method: "POST", data: { ids: [3, 4] } },
  ]);
});

test("invalid or duplicate IDs never reach the backend", async () => {
  for (const ids of [[], [3, 3], [true], [0], [-1], [1.5]]) {
    const { post, calls } = loadRoute();
    const response = await post(request({ entity: "categories", ids }));
    assert.equal(response.status, 422);
    assert.deepEqual(calls, []);
  }
});

test("oversized streamed payloads never reach the backend", async () => {
  const { post, calls } = loadRoute();
  const response = await post(request({ entity: "products", ids: [1], padding: "a".repeat(40_000) }));
  assert.equal(response.status, 422);
  assert.deepEqual(calls, []);
});
