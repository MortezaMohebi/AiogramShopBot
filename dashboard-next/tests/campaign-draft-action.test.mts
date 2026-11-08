/** Execute the actual draft action; only the signed API and Next runtime are doubled. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = fileURLToPath(new URL("../app/(console)/campaigns/actions.ts", import.meta.url));
const code = ts.transpileModule(readFileSync(source, "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  fileName: source,
}).outputText;
const botId = "20000000-0000-4000-8000-000000000001";

function fixture() {
  const writes: { path: string; method: string; data: unknown }[] = [];
  const evaluatedModule = { exports: {} as { createCampaign: (form: FormData) => Promise<void> } };
  const dependencies: Record<string, unknown> = {
    "next/cache": { revalidatePath() {} },
    "next/navigation": {
      redirect(destination: string) {
        throw Object.assign(new Error("redirect"), { destination });
      },
    },
    "@/lib/bridge": {
      async adminFetch(path: string, method: string, data: unknown) {
        writes.push({ path, method, data: JSON.parse(JSON.stringify(data)) });
        return { id: 15 };
      },
    },
  };
  runInNewContext(code, {
    exports: evaluatedModule.exports, module: evaluatedModule,
    require(id: string) {
      if (!(id in dependencies)) throw new Error(`Unexpected dependency: ${id}`);
      return dependencies[id];
    },
  }, { filename: source });
  return { ...evaluatedModule.exports, writes };
}

function form(target?: string) {
  const values = new FormData();
  values.set("title", " عنوان ");
  values.set("text", " متن اعلان ");
  if (target !== undefined) values.set("target", target);
  return values;
}

function redirectsTo(destination: string) {
  return (error: unknown) => typeof error === "object" && error !== null
    && "destination" in error && error.destination === destination;
}

test("a Registry choice carries its explicit bot identity into the signed API", async () => {
  const action = fixture();
  await assert.rejects(action.createCampaign(form(botId)), redirectsTo("/campaigns?saved=1"));
  assert.deepEqual(action.writes, [{
    path: "/campaigns", method: "POST",
    data: { title: "عنوان", text: "متن اعلان", bot_id: botId, audience: "all" },
  }]);
});

for (const target of [undefined, "", "legacy:all", "legacy:telegram", "legacy:bale", "legacy:unknown", "not-a-bot"]) {
  test(`an invalid or absent target ${JSON.stringify(target)} cannot become a campaign draft`, async () => {
    const action = fixture();
    await assert.rejects(action.createCampaign(form(target)), redirectsTo("/campaigns?error=create"));
    assert.equal(action.writes.length, 0);
  });
}
