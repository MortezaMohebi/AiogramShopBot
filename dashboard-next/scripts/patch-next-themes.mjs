/**
 * Keep next-themes' SSR anti-flash script out of fresh React 19 client mounts.
 * Upstream: https://github.com/pacocoursey/next-themes/issues/385
 * Remove this compatibility patch when upgrading to an upstream fix. Both the
 * pinned version and exact vendor hashes must be reviewed on dependency updates.
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const expected = {
  "index.js": [
    "12ae3d586f45897c12039cced4bae66585d5f74592b0663de3242730376a59dc",
    "a86783580e5bbb47308fe49ca89ba5631078999edc19fb8e126ba1e7924719fc",
  ],
  "index.mjs": [
    "f7ae8998b0d8ec4accd9e231e017e4673a002016bf84c0a8292f1dea33ede3f3",
    "d98f15f6928f754eda106fd0984c8a67ad675af82e98662d005fb0b93a203681",
  ],
};
const digest = (source) => createHash("sha256").update(source).digest("hex");

/** Validate every input before changing either distribution entry point. */
export function patchNextThemes(packageRoot) {
  const metadata = JSON.parse(readFileSync(path.join(packageRoot, "package.json"), "utf8"));
  if (metadata.name !== "next-themes" || metadata.version !== "0.4.6") {
    throw new Error("Theme compatibility patch requires reviewed next-themes 0.4.6.");
  }
  const pending = [];
  for (const [file, [originalHash, patchedHash]] of Object.entries(expected)) {
    const filename = path.join(packageRoot, "dist", file);
    const source = readFileSync(filename, "utf8");
    const hash = digest(source);
    if (hash === patchedHash) continue;
    if (hash !== originalHash) throw new Error(`Unrecognized next-themes ${file}; refusing to patch.`);
    const pattern = /([\w$]+=[\w$]+\.memo\(\(\{[^}]*\}\)=>\{)(?=let [\w$]+=JSON\.stringify)/g;
    if ([...source.matchAll(pattern)].length !== 1) throw new Error(`ThemeScript boundary missing in ${file}.`);
    const patched = source.replace(pattern, '$1if(typeof window!=="undefined")return null;');
    if (digest(patched) !== patchedHash) throw new Error(`Unexpected theme patch output in ${file}.`);
    pending.push([filename, patched]);
  }
  for (const [filename, patched] of pending) writeFileSync(filename, patched);
  return pending.length;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const packageRoot = path.resolve(path.dirname(require.resolve("next-themes")), "..");
  const changed = patchNextThemes(packageRoot);
  process.stdout.write(`next-themes React 19 compatibility: ${changed ? "applied" : "already applied"}\n`);
}
