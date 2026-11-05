/** Render Store operational aggregates without customer values or invented zeros. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";
import ts from "typescript";

const code = ts.transpileModule(readFileSync(new URL("../components/runtime/overview.tsx", import.meta.url), "utf8"), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }
}).outputText;
const mod = { exports: {} as Record<string, never> };
const deps: Record<string, unknown> = {
  "react/jsx-runtime": jsx,
  "next/link": { default: ({ children, ...props }: Record<string, unknown>) => createElement("a", props, children as never) },
  "./shared": {
    RuntimeId: ({ children }: Record<string, unknown>) => createElement("bdi", { dir: "ltr" }, children as never),
    RuntimePanel: ({ title, children }: Record<string, unknown>) => createElement("section", null, createElement("h2", null, title as never), children as never),
    RuntimeEmpty: ({ children }: Record<string, unknown>) => createElement("p", null, children as never)
  }
};
runInNewContext(code, { module: mod, exports: mod.exports, require: (key: string) => { assert.ok(key in deps, key); return deps[key]; }, Number, Object, URLSearchParams });
const render = (overview: unknown) => renderToStaticMarkup(createElement(mod.exports.RuntimeOperationalOverview, { overview }));
const workflow = "f423a748-9c8c-4065-9ece-37d132002677";
const publication = "2a74c464-402d-4e17-8939-d9d94f52f760";
const metrics = {
  runs_started: 12, runs_completed: 2, runs_cancelled: 1, runs_failed: 3,
  completed_duration_seconds_avg: 1.25, node_transitions: 42, input_validation_errors: 4,
  action_failures: 5, timeouts: 6, duplicate_events: 7, outbox_retries: 8,
  outbox_deadletters: 9, delivery_failures_by_platform: { telegram: 2 }
};
const scope = { window: "all_retained_history", store_id: "store" };

test("retained metrics show duration, actual-attempt delivery semantics and absent platform zero", () => {
  const html = render({ metrics, metrics_scope: scope, active_groups: [] });
  assert.match(html, /تمام تاریخچهٔ نگهداری‌شدهٔ فروشگاه جاری/);
  assert.match(html, /۱٫۲۵ ثانیه/);
  assert.match(html, /تلاش فیزیکی/);
  assert.match(html, /حتی اگر تلاش بعدی موفق شده باشد/);
  assert.match(html, /تلگرام/); assert.match(html, /بله/); assert.match(html, /۰/);
});

test("missing aggregate data differs from a measured zero and no completed sample", () => {
  const absent = render({});
  assert.match(absent, /آمار عملیاتی در دسترس نیست/);
  assert.match(absent, /گروه‌های فعال در دسترس نیست/);
  assert.ok(!absent.includes("۰"));
  assert.match(render({ metrics, metrics_scope: { window: "today" } }), /دامنهٔ آمار در دسترس نیست/);
  const noSample = render({ metrics: { ...metrics, completed_duration_seconds_avg: null, delivery_failures_by_platform: undefined, timeouts: undefined }, metrics_scope: scope, active_groups: [] });
  assert.match(noSample, /نمونهٔ تکمیل‌شده‌ای وجود ندارد/);
  assert.match(noSample, /در دسترس نیست/);
  assert.match(noSample, /اجرای فعالی در این گروه‌بندی وجود ندارد/);
  assert.ok(!noSample.includes("undefined"));
  assert.match(render({ metrics: { ...metrics, completed_duration_seconds_avg: 0 }, metrics_scope: scope }), /۰ ثانیه/);
});

test("active groups expose only safe metadata and exact scoped filter links", () => {
  const html = render({ active_groups: [{ workflow_id: workflow, publication_id: publication, revision: 3, active_runs: 4, variables: "PRIVATE_CUSTOMER_DO_NOT_RENDER" }], active_groups_has_more: false });
  assert.match(html, /فرایند/); assert.match(html, /انتشار/); assert.match(html, /نسخه/); assert.match(html, /تعداد اجرای فعال/);
  assert.ok(html.includes(`tab=runs&amp;workflow_id=${workflow}&amp;publication_id=${publication}`));
  assert.ok(html.includes(`tab=publications&amp;workflow_id=${workflow}`));
  assert.match(html, /۳/); assert.match(html, /۴/);
  assert.ok(!html.includes("PRIVATE_CUSTOMER"));
  assert.ok(!render({ active_groups: [{ workflow_id: "javascript:alert(1)", publication_id: publication, revision: 1, active_runs: 1 }] }).includes('href="'));
});

test("group truncation is explicit and the UI bounds an oversized payload to 100 groups", () => {
  const group = { workflow_id: workflow, publication_id: publication, revision: 1, active_runs: 1 };
  const html = render({ active_groups: Array.from({ length: 101 }, (_, index) => ({ ...group, publication_id: index === 100 ? "HIDDEN_GROUP_101" : publication, revision: index + 1 })), active_groups_has_more: true });
  assert.match(html, /فقط ۱۰۰ گروه اول/);
  assert.ok(!html.includes("HIDDEN_GROUP_101"));
});
