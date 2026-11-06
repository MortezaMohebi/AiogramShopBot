/** Execute the actual BFF, CSRF/signature helpers and Next Cookie implementation. */
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import * as crypto from "node:crypto";
import ts from "typescript";
const root=fileURLToPath(new URL("..",import.meta.url)),require=createRequire(import.meta.url);
const {NextRequest}=require("next/server");
const requestId="12345678-1234-4234-8234-123456789abc";
class ApiError extends Error {status:number;code?:string;requestId=requestId;constructor(status:number,code?:string){super("upstream");this.status=status;this.code=code;}}
function fixture({failure,ttl,legacy=false}:{failure?:ApiError;ttl?:number;legacy?:boolean}={}) {
 const sent:Record<string,unknown>[]=[],logs:unknown[][]=[],cache=new Map<string,Record<string,unknown>>();
 function load(relative:string):Record<string,unknown>{
  const stem=path.resolve(root,relative),filename=[stem,stem+".ts"].find(existsSync);assert(filename);
  const previous=cache.get(filename);if(previous)return previous;
  const evaluated={exports:{} as Record<string,unknown>};cache.set(filename,evaluated.exports);
  const source=process.env.LOGIN_BASELINE==="1"?execFileSync("git",["show",`HEAD:dashboard-next/${path.relative(root,filename)}`],{cwd:root,encoding:"utf8"}):readFileSync(filename,"utf8");
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  runInNewContext(code,{module:evaluated,exports:evaluated.exports,Buffer,URL,Request,Response,Headers,Uint8Array,AbortSignal,ReadableStream,TextDecoder,TextEncoder,console:{warn:(...args:unknown[])=>logs.push(args)},process:{env:{NODE_ENV:"production",NEXT_ADMIN_PUBLIC_ORIGIN:"https://shop.test",NEXT_ADMIN_SESSION_SECRET:"synthetic-session-signing-key-".repeat(3)}},require:(name:string)=>{
   if(name==="server-only")return {};
   if(name==="node:crypto")return crypto;
   if(name==="next/headers")return {cookies:async()=>({get:()=>undefined})};
   if(name==="@/lib/bridge")return {ApiError,bridgeFetch:async(_p:string,_m:string,data:Record<string,unknown>)=>{sent.push(data);if(failure)throw failure;if(legacy&&"remember_me" in data)throw new ApiError(422);return {id:11,session_version:2,session_token:"B".repeat(43),...(legacy?{}:{session_ttl_seconds:ttl??(data.remember_me?2592000:28800)})};}};
   if(name==="@/lib/captcha-config")return {serverCaptchaConfig:()=>({provider:"none"})};
   if(name==="@/lib/captcha-verification")return {verifyCaptchaToken:async()=>"ok"};
   if(name.startsWith("@/"))return load(name.slice(2));
   return require(name);
  }});return evaluated.exports;
 }
 const {POST}=load("app/api/auth/login/route") as {POST:(request:unknown)=>Promise<import("next/server").NextResponse>};
 const {verifySession}=load("lib/session") as {verifySession:(value:string)=>{expires:number}|null};
 return {sent,logs,verifySession,post:(remember:unknown=false)=>POST(new NextRequest("https://shop.test/api/auth/login",{method:"POST",headers:{origin:"https://shop.test","sec-fetch-site":"same-origin","content-type":"application/json",accept:"application/json",cookie:"__Host-shop_login_challenge="+"C".repeat(43),"x-shop-login-challenge":"C".repeat(43)},body:JSON.stringify({username:"qa.synthetic",password:"TEST-ONLY-SECRET",remember_me:remember})}))};
}
test("default login is a browser-session Cookie with an eight-hour signed limit",async()=>{
 const f=fixture(),response=await f.post();assert.equal(response.status,200);
 const cookie=response.cookies.get("__Host-shop_admin");assert(cookie);assert.equal(cookie.maxAge,undefined);assert.equal(cookie.expires,undefined);assert.equal(cookie.httpOnly,true);assert.equal(cookie.secure,true);assert.equal(cookie.sameSite,"strict");
 assert(Math.abs(f.verifySession(cookie.value)!.expires-Math.floor(Date.now()/1000)-28800)<=1);assert.equal(f.sent[0].remember_me,undefined);
});
test("remember me agrees across backend request, signed envelope and persistent Cookie",async()=>{
 const f=fixture(),response=await f.post(true);assert.equal(response.status,200);const cookie=response.cookies.get("__Host-shop_admin");assert.equal(cookie.maxAge,2592000);assert.equal(f.sent[0].remember_me,true);assert(Math.abs(f.verifySession(cookie.value)!.expires-Math.floor(Date.now()/1000)-2592000)<=1);
});
test("a backend that does not grant persistence cannot receive a longer browser session",async()=>{
 const f=fixture({ttl:28800}),response=await f.post(true);assert.equal(response.status,503);assert.equal(response.cookies.get("__Host-shop_admin"),undefined);
});
test("string remember flags cannot silently opt a user into persistence",async()=>{
 const f=fixture(),response=await f.post("false");assert.equal(response.status,422);assert.equal(f.sent.length,0);
});
test("internal unauthorized responses are service errors, not false password failures",async()=>{
 const f=fixture({failure:new ApiError(401)}),response=await f.post();assert.equal(response.status,503);assert.equal((await response.json()).code,"service_unavailable");assert.equal(response.cookies.get("__Host-shop_admin"),undefined);
});
test("known password failures retain401 and their safe correlation ID without a session",async()=>{
 const f=fixture({failure:new ApiError(401,"invalid_credentials")}),response=await f.post(true);assert.equal(response.status,401);const reply=await response.json();assert.equal(reply.code,"invalid_credentials");assert.equal(reply.requestId,requestId);assert.equal(response.cookies.get("__Host-shop_admin"),undefined);assert(!JSON.stringify(f.logs).includes("TEST-ONLY-SECRET"));
});
test("ordinary login remains compatible with a strict older short-session backend",async()=>{
 const f=fixture({legacy:true}),response=await f.post(false);assert.equal(response.status,200);assert.equal(f.sent.length,1);assert(!("remember_me" in f.sent[0]));assert.equal(response.cookies.get("__Host-shop_admin")?.maxAge,undefined);
});
