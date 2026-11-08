/** Render the real receiver panel to verify the administrator setup flow. */
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
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022, esModuleInterop: true,
    },
  }).outputText;
  runInNewContext(code, {
    module: evaluated, exports: evaluated.exports,
    require: (name: string) => {
      if (name === "@/app/(console)/bots/[id]/actions") {
        // Rendering cannot invoke Next's authenticated server actions.
        return { stageBotReceiver: async () => {}, activateBotReceiver: async () => {} };
      }
      if (name.startsWith("@/")) return load(name.slice(2));
      if (name.startsWith(".")) return load(path.relative(root, path.resolve(path.dirname(filename), name)));
      return nativeRequire(name);
    },
  });
  return evaluated.exports;
}

test("verified draft receiver activation does not repeat password or MFA", () => {
  const { BotReceiverPanel } = load("components/blocks/bot-receiver-panel") as {
    BotReceiverPanel: ComponentType<Record<string, unknown>>;
  };
  const html = renderToStaticMarkup(createElement(BotReceiverPanel, {
    bot: { id: "20000000-0000-4000-8000-000000000001", status: "draft" },
    receiver: {
      configured: true, state: "staged", mode: "polling", version: 3,
      runtime_enabled: true, worker_ready: true,
    },
    pending: { verified_at: "2026-11-07T00:00:00Z" },
  }));
  assert(html.includes("فعال‌سازی دریافت پیام"));
  assert(html.includes('name="expected_version"'));
  assert(!html.includes('name="current_password"'), "Setup relies on the authenticated administrator session");
  assert(!html.includes('name="second_factor"'), "Setup does not ask for another MFA code");
});

test("a verified staged token is waiting for activation, not verification", () => {
  const { botCredentialLabel } = load("lib/bot-registry") as {
    botCredentialLabel: (credential: { state: "staged"; verified_at: string | null }) => string;
  };
  assert.equal(botCredentialLabel({ state: "staged", verified_at: null }), "در انتظار تأیید");
  assert.equal(botCredentialLabel({ state: "staged", verified_at: "2026-11-08T03:45:50Z" }),
    "تأییدشده · در انتظار فعال‌سازی");
});
