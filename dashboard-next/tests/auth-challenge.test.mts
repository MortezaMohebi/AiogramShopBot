/** Execute the actual shared CSRF route and crypto; only verified session/origin are external. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import * as crypto from "node:crypto";
import ts from "typescript";
function compiled(path: string) {
  return ts.transpileModule(
    readFileSync(new URL(path, import.meta.url), "utf8"),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    },
  ).outputText;
}
function fixture(sid: string | null, site = "same-origin") {
  const session = sid ? { id: 7, version: 2, sid, expires: 9999999999 } : null;
  const environment = {
    NODE_ENV: "production",
    NEXT_ADMIN_SESSION_SECRET: "test-only-csrf-signing-key-".repeat(3),
  };
  const evaluatedChallenge = { exports: {} as Record<string, unknown> };
  runInNewContext(compiled("../lib/login-challenge.ts"), {
    module: evaluatedChallenge,
    exports: evaluatedChallenge.exports,
    process: { env: environment },
    Buffer,
    require: (id: string) => {
      if (id === "server-only") return {};
      if (id === "node:crypto") return crypto;
      throw Error(id);
    },
  });
  const evaluatedRoute = {
    exports: {} as { GET: (r: Request) => Promise<Response> },
  };
  const writes: {
    name: string;
    value: string;
    options: Record<string, unknown>;
  }[] = [];
  const deps: Record<string, unknown> = {
    "@/lib/login-challenge": evaluatedChallenge.exports,
    "@/lib/public-origin": { publicOrigin: () => new URL("https://shop.test") },
    "@/lib/session": { readSession: async () => session },
    "next/server": {
      NextResponse: {
        json: (value: unknown, options?: ResponseInit) => {
          const response = Response.json(value, options);
          Object.assign(response, {
            cookies: {
              set: (
                name: string,
                value: string,
                config: Record<string, unknown>,
              ) => writes.push({ name, value, options: config }),
            },
          });
          return response;
        },
      },
    },
  };
  runInNewContext(compiled("../app/api/auth/challenge/route.ts"), {
    module: evaluatedRoute,
    exports: evaluatedRoute.exports,
    process: { env: environment },
    require: (id: string) => {
      assert.ok(id in deps, id);
      return deps[id];
    },
  });
  const request = (existing?: string) =>
    Object.assign(
      new Request("https://shop.test/api/auth/challenge", {
        headers: { "sec-fetch-site": site },
      }),
      { cookies: { get: () => (existing ? { value: existing } : undefined) } },
    );
  return {
    get: (existing?: string) => evaluatedRoute.exports.GET(request(existing)),
    writes,
  };
}
test("concurrent first authenticated challenges share a stable session-bound value", async () => {
  const f = fixture("A".repeat(43));
  const [a, b] = await Promise.all([f.get(), f.get()]);
  const left = await a.json(),
    right = await b.json();
  assert.equal(left.challenge, right.challenge);
  assert.match(left.challenge, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(f.writes[0].name, "__Host-shop_login_challenge");
  assert.equal(f.writes[0].options.httpOnly, true);
  assert.equal(f.writes[0].options.secure, true);
  assert.equal(f.writes[0].options.sameSite, "strict");
});
test("session refresh retains CSRF value while another session gets a distinct token", async () => {
  const f = fixture("A".repeat(43));
  const first = await (await f.get()).json();
  assert.equal(
    (await (await f.get(first.challenge)).json()).challenge,
    first.challenge,
  );
  const other = await (
    await fixture("B".repeat(43)).get(first.challenge)
  ).json();
  assert.notEqual(other.challenge, first.challenge);
});
test("anonymous forms reuse a valid existing host-bound challenge", async () => {
  const f = fixture(null);
  assert.equal(
    (await (await f.get("C".repeat(43))).json()).challenge,
    "C".repeat(43),
  );
  const fresh = await (await f.get("invalid")).json();
  assert.match(fresh.challenge, /^[A-Za-z0-9_-]{43}$/);
});
test("cross-site requests do not receive or rotate a challenge", async () => {
  const f = fixture("A".repeat(43), "cross-site");
  assert.equal((await f.get()).status, 403);
  assert.equal(f.writes.length, 0);
});
