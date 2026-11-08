/** Real account request handling preserves safe errors for contextual recovery. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";
import ts from "typescript";

function load(send: typeof fetch) {
  const evaluated = { exports: {} as { controlAction: (action: string, data: unknown) => Promise<unknown> } };
  const code = ts.transpileModule(readFileSync(new URL("../lib/account-control.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  runInNewContext(code, {
    module: evaluated, exports: evaluated.exports, AbortSignal, fetch: send,
    require: (name: string) => {
      assert.equal(name, "@/lib/browser-challenge");
      return { requestBrowserChallenge: async () => "C".repeat(43) };
    },
  });
  return evaluated.exports;
}

test("expired recent proof retains its safe code for enrollment sign-in recovery", async () => {
  const actions = load(async (_url, init) => {
    assert.equal(init?.body, "{}");
    return Response.json({ ok: false, code: "reauthentication_required" }, { status: 403 });
  });
  await assert.rejects(actions.controlAction("mfa-setup", {}), error =>
    (error as { code?: string }).code === "reauthentication_required");
});

test("unknown response text is never used as an account error message", async () => {
  const actions = load(async () => Response.json({ ok: false, code: "PRIVATE_BACKEND_DETAIL" }, { status: 500 }));
  await assert.rejects(actions.controlAction("mfa-setup", {}), error =>
    !String((error as Error).message).includes("PRIVATE_BACKEND_DETAIL"));
});
