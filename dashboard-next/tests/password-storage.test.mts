/** Browser storage uses synthetic values; no real password-manager entry is made. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";
import ts from "typescript";
const code=ts.transpileModule(readFileSync(new URL("../lib/password-storage.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function helper({supported=true,fail=false}:{supported?:boolean;fail?:boolean}={}){
 const writes:unknown[]=[],evaluated={exports:{} as {offerPasswordStorage:(u:string,p:string)=>Promise<void>}};
 class Credential {id:string;password:string;constructor(data:{id:string;password:string}){this.id=data.id;this.password=data.password;}}
 runInNewContext(code,{module:evaluated,exports:evaluated.exports,window:{isSecureContext:true,PasswordCredential:supported?Credential:undefined,setTimeout,clearTimeout},navigator:{credentials:{store:async(value:unknown)=>{writes.push(value);if(fail)throw Error("browser declined");return value;}}},setTimeout,clearTimeout});
 return {...evaluated.exports,writes};
}
test("verified password storage preserves the exact value and account identity",async()=>{const f=helper();await f.offerPasswordStorage("qa.synthetic"," synthetic-only ");assert.equal(f.writes.length,1);assert.equal((f.writes[0] as {password:string}).password," synthetic-only ");assert.equal((f.writes[0] as {id:string}).id,"qa.synthetic");});
test("unsupported credential APIs do not request storage",async()=>{const f=helper({supported:false});await f.offerPasswordStorage("qa.synthetic","synthetic");assert.equal(f.writes.length,0);});
test("browser refusal does not turn a completed login into a failure",async()=>{const f=helper({fail:true});await f.offerPasswordStorage("qa.synthetic","synthetic");assert.equal(f.writes.length,1);});
