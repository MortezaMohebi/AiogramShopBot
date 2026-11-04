import assert from "node:assert/strict";
import test from "node:test";
import { formatOrderAmount } from "../lib/order-money.ts";

test("Stars orders display frozen XTR rather than catalog IRR", () => {
  const label = formatOrderAmount({ platform: "telegram", total_irr: "9000", total_stars_snapshot: 7 });
  assert.match(label, /XTR/);
  assert.match(label, /۷/);
  assert.doesNotMatch(label, /ریال|۹٬۰۰۰/);
});

test("settled Stars amount remains exact after refund", () => {
  assert.match(formatOrderAmount({ platform: "telegram", total_irr: "9000", total_stars_snapshot: 7, payment_currency: "XTR", payment_amount: "7" }), /۷.*XTR/);
});

test("Bale IRR is never guessed to be Telegram Stars", () => {
  const label = formatOrderAmount({ platform: "bale", total_irr: "1500", total_stars_snapshot: null });
  assert.match(label, /۱٬۵۰۰/);
  assert.match(label, /ریال/);
  assert.doesNotMatch(label, /XTR/);
});
