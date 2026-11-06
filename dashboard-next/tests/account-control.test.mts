/** Verify account feedback against the real client function without network I/O. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../lib/account-control.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
}).outputText;

/** Replace only challenge/network boundaries; retain production result handling. */
function client({challengeError, response, transportError}: {
  challengeError?: Error;
  response?: Response;
  transportError?: Error;
} = {}) {
  const requests: string[] = [];
  const evaluated = {exports:{} as {controlAction:(action:string,data:unknown)=>Promise<{ok?:boolean}>}};
  runInNewContext(compiled, {
    module:evaluated, exports:evaluated.exports, Error, AbortSignal,
    require:(name:string) => {
      assert.equal(name,"@/lib/browser-challenge");
      return {requestBrowserChallenge:async () => {
        if(challengeError) throw challengeError;
        return "synthetic-challenge";
      }};
    },
    fetch:async (url:string) => {
      requests.push(url);
      if(transportError) throw transportError;
      return response;
    },
  });
  return {...evaluated.exports,requests};
}

test("a failed account challenge shows safe feedback without dispatching a write",async () => {
  const api=client({challengeError:new Error("INTERNAL_SECURITY_DETAIL")});
  await assert.rejects(api.controlAction("profile",{}), /بررسی امنیتی انجام نشد/);
  assert.equal(api.requests.length,0);
});

test("a lost account response stays unconfirmed and does not replay the write",async () => {
  const api=client({transportError:new TypeError("INTERNAL_NETWORK_DETAIL")});
  await assert.rejects(api.controlAction("profile",{}), /پاسخ نهایی دریافت نشد.*وضعیت فعلی/);
  assert.deepEqual(api.requests,["/api/account/profile"]);
});

test("an unreadable account response directs status checking without automatic replay",async () => {
  const api=client({response:new Response("not-json",{headers:{"content-type":"application/json"}})});
  await assert.rejects(api.controlAction("profile",{}), /پاسخ نهایی قابل خواندن نیست.*وضعیت فعلی/);
  assert.equal(api.requests.length,1);
});

test("account rejection translates the stable code and excludes raw server detail",async () => {
  const api=client({response:Response.json({ok:false,code:"permission_denied",detail:"INTERNAL_SQL_DETAIL"},{status:403})});
  await assert.rejects(api.controlAction("profile",{}), (error:unknown) => {
    assert(error instanceof Error);
    assert.match(error.message,/مجوز/);
    assert(!error.message.includes("INTERNAL_SQL_DETAIL"));
    return true;
  });
  assert.equal(api.requests.length,1);
});

test("only an affirmative account receipt returns a successful result",async () => {
  const api=client({response:Response.json({ok:true})});
  const result=await api.controlAction("profile",{});
  assert.equal(result.ok,true);
  assert.equal(api.requests.length,1);
});
