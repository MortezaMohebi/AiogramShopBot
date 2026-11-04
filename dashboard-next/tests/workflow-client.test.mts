/** Concurrent browser calls share a cookie jar and a Web Lock, including other tabs. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
const code = ts.transpileModule(
  readFileSync(new URL("../lib/workflows/client.ts", import.meta.url), "utf8"),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  },
).outputText;
test("overlapping studio mutations cannot invalidate each other's CSRF cookie", async () => {
  let cookie = "",
    counter = 0,
    tail = Promise.resolve();
  const operations: string[] = [];
  const locks = {
    request: (_name: string, run: () => Promise<unknown>) => {
      const result = tail.then(run);
      tail = result.then(
        () => undefined,
        () => undefined,
      );
      return result;
    },
  };
  const evaluatedModule = {
    exports: {} as {
      workflowRequest: <T>(
        path: string,
        method: string,
        payload: unknown,
      ) => Promise<T>;
    },
  };
  runInNewContext(code, {
    module: evaluatedModule,
    exports: evaluatedModule.exports,
    require: (key: string) => {
      assert.equal(key, "@/lib/browser-challenge");
      return {
        requestBrowserChallenge: async () => {
          const token = String(++counter);
          cookie = token;
          await Promise.resolve();
          return token;
        },
      };
    },
    navigator: { locks },
    AbortSignal,
    fetch: async (
      _url: string,
      request: { headers: Record<string, string>; body: string },
    ) => {
      assert.equal(request.headers["x-shop-login-challenge"], cookie);
      operations.push(JSON.parse(request.body).operation_id);
      await Promise.resolve();
      return { ok: true, json: async () => ({ revision: 2 }) };
    },
  });
  await Promise.all(
    Array.from({ length: 6 }, (_, i) =>
      evaluatedModule.exports.workflowRequest("/same", "PATCH", {
        operation_id: `op_${i}`,
      }),
    ),
  );
  assert.deepEqual(operations, [
    "op_0",
    "op_1",
    "op_2",
    "op_3",
    "op_4",
    "op_5",
  ]);
});
