/** Exercise retention receipt handling without deleting real customer data. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = fileURLToPath(new URL("../app/(console)/customers/retention/actions.ts", import.meta.url));
const code = ts.transpileModule(readFileSync(source, "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  fileName: source,
}).outputText;

class ApiError extends Error {
  status: number;
  constructor(status: number) { super("private upstream details"); this.status = status; }
}

function fixture(receipt: unknown, error?: ApiError) {
  const requests: { path: string; method: string; data: unknown }[] = [];
  const evaluatedModule = { exports: {} as { purgeCustomerNotes: (form: FormData) => Promise<void> } };
  const dependencies: Record<string, unknown> = {
    "@/lib/draft-mutation": { saveDraftMutation() { throw new Error("Unexpected policy write"); } },
    "next/cache": { revalidatePath() {} },
    "next/navigation": {
      redirect(destination: string) {
        throw Object.assign(new Error("redirect"), { destination });
      },
    },
    "@/lib/bridge": {
      ApiError,
      async adminFetch(path: string, method: string, data: unknown) {
        requests.push({ path, method, data: JSON.parse(JSON.stringify(data)) });
        if (error) throw error;
        return receipt;
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
  return { ...evaluatedModule.exports, requests };
}

function redirectsTo(destination: string) {
  return (error: unknown) => typeof error === "object" && error !== null
    && "destination" in error && error.destination === destination;
}

test("a default dry run returns the eligible count without deletion consent", async () => {
  const action = fixture({ ok: true, dry_run: true, notes_eligible: 17 });
  await assert.rejects(action.purgeCustomerNotes(new FormData()),
    redirectsTo("/customers/retention?saved=preview&count=17"));
  assert.deepEqual(action.requests, [{
    path: "/customer-retention/purge", method: "POST",
    data: { dry_run: true, confirmation: "" },
  }]);
});

test("explicit consent returns only the authoritative deleted count", async () => {
  const action = fixture({ ok: true, dry_run: false, notes_deleted: 4, notes_eligible: 99 });
  const form = new FormData();
  form.set("confirm", "on");
  await assert.rejects(action.purgeCustomerNotes(form),
    redirectsTo("/customers/retention?saved=purged&count=4"));
  assert.deepEqual(action.requests[0]?.data, {
    dry_run: false, confirmation: "PURGE_EXPIRED_NOTES",
  });
});

for (const receipt of [
  null, { ok: false, dry_run: true, notes_eligible: 3 },
  { ok: true, dry_run: false, notes_eligible: 3 },
  { ok: true, dry_run: true }, { ok: true, dry_run: true, notes_eligible: -1 },
  { ok: true, dry_run: true, notes_eligible: "3" },
  { ok: true, dry_run: true, notes_eligible: 1.5 },
  { ok: true, dry_run: true, notes_eligible: Number.MAX_SAFE_INTEGER + 1 },
]) {
  test(`an unconfirmed receipt cannot report a successful preview: ${JSON.stringify(receipt)}`, async () => {
    const action = fixture(receipt);
    await assert.rejects(action.purgeCustomerNotes(new FormData()),
      redirectsTo("/customers/retention?error=receipt"));
    assert.equal(action.requests.length, 1);
  });
}

test("reauthentication failure does not report a count or retry deletion", async () => {
  const action = fixture(undefined, new ApiError(428));
  const form = new FormData();
  form.set("confirm", "on");
  await assert.rejects(action.purgeCustomerNotes(form),
    redirectsTo("/customers/retention?error=reauth"));
  assert.equal(action.requests.length, 1);
});
