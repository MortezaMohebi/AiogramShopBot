import assert from "node:assert/strict";
import test from "node:test";
import { duplicateAttributeDraft, moveAttributeDraft } from "../lib/product-attribute-drafts.ts";

test("duplicating a product row preserves the shared catalog IDs and drops the old link IDs", () => {
  const source = {
    key: "finish", label: "بافت", unit: null, visible: true, variation: true,
    definition_id: 4, aliases: ["روکش"], external_ids: { "odoo:main": "12" },
    values: [{ id: 7, value_id: 18, label: "مات", external_ids: { "odoo:main": "18" } }],
  };
  const duplicate = duplicateAttributeDraft(source);
  assert.notEqual(duplicate.attribute.key, source.key);
  assert.equal(duplicate.attribute.definition_id, source.definition_id);
  assert.deepEqual(duplicate.attribute.values, [{ label: "مات", value_id: 18 }]);
  assert.equal(duplicate.attribute.external_ids, undefined);
  assert.equal(duplicate.attribute.variation, true);
  assert.deepEqual(duplicate.attribute.aliases, ["روکش"]);
  assert.notEqual(duplicate.attribute.aliases, source.aliases);
});

test("moving a row changes saved priority without changing any attribute or value identity", () => {
  const rows = ["first", "second", "third"].map((key, index) => ({ rowId: key, attribute: {
    key, label: key, unit: null, visible: true, variation: false,
    values: [{ id: index + 1, label: key }],
  } }));
  const moved = moveAttributeDraft(rows, "first", "third");
  assert.deepEqual(moved.map((row) => row.rowId), ["second", "third", "first"]);
  assert.equal(moved[2], rows[0]);
  assert.equal(moved[2].attribute.values[0].id, 1);
  assert.equal(moveAttributeDraft(rows, "first", "missing"), rows);
});
