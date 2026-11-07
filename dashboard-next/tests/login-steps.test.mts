/** Render the production login form, including its real React hooks and fields. */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
const root = fileURLToPath(new URL("..", import.meta.url));
const nativeRequire = createRequire(import.meta.url);
function load(relative: string): Record<string, unknown> {
  const stem = path.resolve(root, relative);
  const filename = [stem, stem + ".tsx", stem + ".ts"].find(existsSync);
  assert(filename);
  const evaluated = { exports: {} };
  const code = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  runInNewContext(code, { module: evaluated, exports: evaluated.exports, require: (name: string) => {
    if (name.startsWith("@/")) return load(name.slice(2));
    if (name.startsWith(".")) return load(path.relative(root, path.resolve(path.dirname(filename), name)));
    return nativeRequire(name);
  }});
  return evaluated.exports;
}
test("initial login asks for credentials without an MFA field or recovery code", () => {
  const { LoginForm } = load("components/blocks/login-form") as { LoginForm: ComponentType<{captcha: unknown}> };
  const html = renderToStaticMarkup(createElement(LoginForm, {captcha: {provider:"none"}}));
  assert(html.includes('name="username"'));
  assert(html.includes('name="password"'));
  assert(html.includes('name="remember_me"'));
  const checkbox=html.match(/<input(?=[^>]*name="remember_me")[^>]*>/)?.[0];
  assert(checkbox);assert(!/\bchecked(?:=|\s|>)/.test(checkbox));
  assert(!html.includes('name="second_factor"'), "MFA belongs to the verified second screen");
  assert(!html.includes('autocomplete="one-time-code"'));
});
test("authenticator input accepts Persian/Arabic digits and copied groups", () => {
  const { normalizeAuthenticatorCode } = load("components/blocks/login-form") as { normalizeAuthenticatorCode: (value: string) => string };
  assert.equal(normalizeAuthenticatorCode("۱۲۳ ۴۵۶"), "123456");
  assert.equal(normalizeAuthenticatorCode("١٢٣٤٥٦"), "123456");
  assert(!/^[0-9]{6}$/.test(normalizeAuthenticatorCode("१२३४५६")));
});
