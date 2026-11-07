/** Check actual form patterns against the Unicode Sets syntax used by browsers. */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : path.endsWith(".tsx") ? [path] : [];
  });
}

test("every literal HTML pattern compiles with the browser's v flag", () => {
  let count = 0;
  for (const file of [...files("app"), ...files("components")]) {
    for (const match of readFileSync(file, "utf8").matchAll(/\bpattern="([^"]+)"/g)) {
      assert.doesNotThrow(() => new RegExp(`^(?:${match[1]})$`, "v"), file);
      count++;
    }
  }
  assert.ok(count > 10, "The scan must cover real application forms");
});
