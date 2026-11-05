import assert from "node:assert/strict";
import { test } from "node:test";
import {
  filterActions,
  parseActionInput,
  mappingVariables,
} from "../lib/actions/state.ts";
import type { ActionDescriptor } from "../lib/actions/types.ts";

const schema = {
  type: "object",
  additionalProperties: false,
  required: ["product_id"],
  properties: {
    product_id: { type: "integer", minimum: 1, maximum: 9007199254740991 },
    quantity: { type: "integer", minimum: 1, maximum: 99, default: 1 },
    note: { type: "string", maxLength: 8 },
    topic: { type: "string", enum: ["general", "order"] },
  },
};
const descriptors = [
  {
    key: "catalog.get_product",
    version: "1.0.0",
    name: "جزئیات محصول",
    category: "catalog",
    side_effect: "read_only",
    deprecated: false,
  },
  {
    key: "cart.add_item",
    version: "1.0.0",
    name: "افزودن به سبد",
    category: "cart",
    side_effect: "business_mutation",
    deprecated: false,
  },
  {
    key: "catalog.old_product",
    version: "0.9.0",
    name: "نسخه قدیمی",
    category: "catalog",
    side_effect: "read_only",
    deprecated: true,
  },
] as ActionDescriptor[];

test("Catalog filters combine category, side effect, name and deprecation", () => {
  assert.deepEqual(
    filterActions(descriptors, {
      q: "محصول",
      category: "catalog",
      effect: "read_only",
      deprecated: "false",
    }).map((x) => x.key),
    ["catalog.get_product"],
  );
  assert.deepEqual(
    filterActions(descriptors, {
      q: "",
      category: "",
      effect: "",
      deprecated: "true",
    }).map((x) => x.key),
    ["catalog.old_product"],
  );
  assert.deepEqual(
    filterActions(descriptors, {
      q: "cart.add",
      category: "",
      effect: "",
      deprecated: "all",
    }).map((x) => x.key),
    ["cart.add_item"],
  );
});
test("Dry-run form produces typed bounded constants and omits empty optional fields", () => {
  assert.deepEqual(
    parseActionInput(schema, {
      product_id: "12",
      quantity: "3",
      note: "",
      topic: "order",
    }),
    { product_id: 12, quantity: 3, topic: "order" },
  );
});
for (const [name, values] of [
  ["fractional integer", { product_id: "1.5" }],
  ["missing required", {}],
  ["negative quantity", { product_id: "1", quantity: "0" }],
  ["large count", { product_id: "1", quantity: "100" }],
  ["invalid enum", { product_id: "1", topic: "admin" }],
  ["long text", { product_id: "1", note: "0123456789" }],
  ["extra identity", { product_id: "1", customer_id: "99" }],
] as const)
  test(`Dry-run rejects ${name}`, () =>
    assert.throws(() => parseActionInput(schema, values)));
test("Binding variable choices respect primitive and explicit reference fields", () => {
  const variables = [
    {
      name: "product",
      type: "product_ref",
      scope: "workflow",
      label: "",
      choices: [],
      default: null,
    },
    {
      name: "count",
      type: "integer",
      scope: "workflow",
      label: "",
      choices: [],
      default: null,
    },
    {
      name: "body",
      type: "string",
      scope: "workflow",
      label: "",
      choices: [],
      default: null,
    },
  ] as const;
  assert.deepEqual(
    mappingVariables(schema.properties.product_id, "product_id", [
      ...variables,
    ]).map((x) => x.name),
    ["product", "count"],
  );
  assert.deepEqual(
    mappingVariables(schema.properties.quantity, "quantity", [
      ...variables,
    ]).map((x) => x.name),
    ["count"],
  );
  assert.deepEqual(
    mappingVariables({ type: "object" }, "items", [...variables]),
    [],
  );
});
