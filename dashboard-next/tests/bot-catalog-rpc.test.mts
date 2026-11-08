import assert from "node:assert/strict";
import test from "node:test";
import {
  botCatalogQuery, catalogListParams, parseCatalogChange, parseCatalogListParams,
} from "../lib/bot-catalog-acl.ts";

test("catalog filters have a canonical URL and a bounded GET contract", () => {
  const query = { kind: "category", q: "قهوه & چای", effect: "deny", page: 2 } as const;
  assert.deepEqual(botCatalogQuery.read(botCatalogQuery.write(query)), query);
  assert.deepEqual(parseCatalogListParams(catalogListParams(query)), query);
  assert.equal(parseCatalogListParams(new URLSearchParams("page=2&page=3")), null);
  assert.equal(parseCatalogListParams(new URLSearchParams("effect=unexpected")), null);
  assert.equal(parseCatalogListParams(new URLSearchParams("path=/staff")), null);
  assert.equal(parseCatalogListParams(new URLSearchParams("page=1e2")), null);
  assert.equal(parseCatalogListParams(new URLSearchParams("q=" + "x".repeat(101))), null);
});

test("a typed catalog command also validates untrusted server-action arguments", () => {
  const command = { kind: "product", effect: "allow", expected_version: 3, target_ids: [1, 2] };
  assert.deepEqual(parseCatalogChange(command), command);
  assert.equal(parseCatalogChange({ ...command, target_ids: [1, 1] }), null);
  assert.equal(parseCatalogChange({ ...command, target_ids: ["1"] }), null);
  assert.equal(parseCatalogChange({ ...command, target_ids: Array(101).fill(1) }), null);
  assert.equal(parseCatalogChange({ ...command, expected_version: 0 }), null);
  assert.equal(parseCatalogChange({ ...command, kind: "other" }), null);
  assert.equal(parseCatalogChange({ ...command, force: true }), null);
});
