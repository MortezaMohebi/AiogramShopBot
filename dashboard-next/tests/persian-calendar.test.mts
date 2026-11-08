import assert from "node:assert/strict";
import { test } from "node:test";
import {
  formatCalendarDate, parseCalendarDate, persianDateLabel, utcPickerValue,
} from "../lib/persian-calendar.ts";

test("Gregorian form values keep their civil day and reject invalid dates", () => {
  assert.equal(formatCalendarDate(parseCalendarDate("2024-03-20")!), "2024-03-20");
  assert.equal(parseCalendarDate("2025-02-29"), null);
  assert.equal(parseCalendarDate("2024-03-20T23:59:59Z"), null);
  assert.equal(parseCalendarDate("0000-01-01"), null);
});

test("the field display follows the Persian leap day and Nowruz", () => {
  assert.equal(persianDateLabel(parseCalendarDate("2025-03-20")!), "۳۰ اسفند ۱۴۰۳");
  assert.equal(persianDateLabel(parseCalendarDate("2025-03-21")!), "۱ فروردین ۱۴۰۴");
});

test("the UTC picker displays explicit offsets without confusing their civil dates", () => {
  assert.equal(utcPickerValue("2026-03-21T00:15:42+03:30"), "2026-03-20T20:45:42.000Z");
  assert.equal(utcPickerValue("2026-03-21T00:15"), "");
  assert.equal(utcPickerValue("2026-02-30T00:15Z"), "");
});
