/** Exercise the category Server Action against the strict backend request contract. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const root = fileURLToPath(new URL("..", import.meta.url));

function loadAction() {
  const filename = path.join(root, "app/(console)/categories/actions.ts");
  const code = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const evaluated = { exports: {} as Record<string, unknown> };
  const requests: Array<{ path: string; method: string; payload: Record<string, unknown> }> = [];
  runInNewContext(code, {
    module: evaluated,
    exports: evaluated.exports,
    require: (name: string) => {
      if (name === "next/cache") return { revalidatePath: () => undefined };
      if (name === "next/navigation") return { redirect: (url: string) => { throw new Error(`redirect:${url}`); } };
      if (name === "@/lib/session") return { readSession: async () => ({ id: 1 }) };
      if (name === "@/lib/section-rpc-server") return { sectionRpcError: () => "outcome_unknown" };
      if (name === "@/lib/bridge") return {
        bridgeFetch: async (requestPath: string, method: string, payload: Record<string, unknown>) => {
          requests.push({ path: requestPath, method, payload });
          return { id: 42 };
        },
        adminFetch: async (requestPath: string, method: string, payload: Record<string, unknown>) => {
          requests.push({ path: requestPath, method, payload });
          return { id: 42 };
        },
      };
      throw new Error(`Unexpected import: ${name}`);
    },
  });
  return {
    saveCategory: evaluated.exports.saveCategory as (form: FormData) => Promise<void>,
    saveCategoryDraft: evaluated.exports.saveCategoryDraft as
      (id: number, patch: { parent_id: number | null }) => Promise<unknown>,
    requests,
  };
}

test("new category uses the backend create contract even if position is submitted", async () => {
  const { saveCategory, requests } = loadAction();
  const form = new FormData();
  form.set("name", "QA کالاهای فیزیکی");
  form.set("position", "10");
  form.set("is_published", "on");
  await assert.rejects(saveCategory(form), /redirect:\/categories\?saved=1/);
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [
    { path: "/categories", method: "POST", payload: { name: "QA کالاهای فیزیکی", is_published: true } },
  ]);
});

test("editing a category retains its requested display position", async () => {
  const { saveCategory, requests } = loadAction();
  const form = new FormData();
  form.set("id", "42");
  form.set("name", "QA دیجیتال");
  form.set("position", "20");
  await assert.rejects(saveCategory(form), /redirect:\/categories\?saved=1/);
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [
    { path: "/categories/42", method: "PATCH", payload: { name: "QA دیجیتال", position: 20, is_published: false } },
  ]);
});

test("saving an inline draft can remove its parent without rewriting other fields", async () => {
  const { saveCategoryDraft, requests } = loadAction();
  const receipt = await saveCategoryDraft(42, { parent_id: null });
  assert.deepEqual(JSON.parse(JSON.stringify(receipt)), { ok: true, data: { id: 42 } });
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [
    { path: "/categories/42", method: "PATCH", payload: { parent_id: null } },
  ]);
});
