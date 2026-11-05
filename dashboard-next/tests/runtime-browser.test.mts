/** Exercise browser-runner telemetry assertions without a browser, Docker or a server. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../../scripts/workflow_runtime_browser.mjs", import.meta.url), "utf8");
const start = source.indexOf("function assertNextClean(");
assert.ok(start >= 0, "runner must validate structured Next error results");
const end = source.indexOf("\n/**", start);
class CheckFailure extends Error {}
const telemetry = runInNewContext(`${source.slice(start, end)}; assertNextClean`, {
  requireSafe: (ok: boolean, code: string) => { if (!ok) throw new CheckFailure(code); }, CheckFailure, JSON, Array, Object
}) as (value: unknown, tool: string) => void;
const result = (value: unknown) => ({ content: [{ type: "text", text: JSON.stringify(value) }] });

test("Next 16.4 clean error arrays pass without matching obsolete English prose", () => {
  telemetry(result({ configErrors: [], sessionErrors: [] }), "get_errors");
  telemetry(result({ issues: [] }), "get_compilation_issues");
});

test("Next tooling failures, malformed results and real application errors cannot pass", () => {
  for (const value of [
    undefined,
    result({ error: "No browser sessions connected" }), result({}),
    result({ configErrors: [], sessionErrors: [{ errors: [{ message: "private" }] }] }),
    result({ configErrors: [{ message: "invalid config" }], sessionErrors: [] }),
    { content: [{ type: "text", text: "No errors detected" }] },
    { content: [{ type: "text", text: "not-json" }] },
    { ...result({ configErrors: [], sessionErrors: [] }), isError: true }
  ]) assert.throws(() => telemetry(value, "get_errors"), /next_application_error/);
  for (const value of [result({ error: "Turbopack project is not available" }), result({ issues: [{ severity: "error" }] }), result({ issues: null })])
    assert.throws(() => telemetry(value, "get_compilation_issues"), /next_compilation_issue/);
});

test("normal logout restores a supported desktop viewport before locating its visible control", async () => {
  const start = source.indexOf("async function logout(session)");
  const end = source.indexOf("\ntry {", start);
  const events: string[] = [];
  const page = {
    isClosed: () => false,
    setViewportSize: async (viewport: { width: number }) => { assert.equal(viewport.width, 1100); events.push("desktop"); },
    url: () => "http://localhost:3004/studio/runtime",
    getByRole: () => ({ waitFor: async () => { events.push("visible"); }, click: async () => { events.push("logout"); } }),
    waitForURL: async () => { events.push("login"); }
  };
  const logout = runInNewContext(`${source.slice(start, end)}; logout`, {
    URL, ready: async () => {},
    bff: async (_: unknown, path: string, options: { status: number }) => { assert.equal(options.status, 401); assert.equal(path, "/api/admin/workflow-runtime"); events.push("unauthorized"); },
    docker: () => { events.push("revocation"); }
  }) as (session: unknown) => Promise<void>;
  const session = { loggedIn: true, page, viewport: { width: 390, height: 1000 }, backendToken: "synthetic-test-token" };
  await logout(session);
  assert.deepEqual(events, ["desktop", "visible", "logout", "login", "unauthorized", "revocation"]);
  assert.equal(session.loggedIn, false);
});
