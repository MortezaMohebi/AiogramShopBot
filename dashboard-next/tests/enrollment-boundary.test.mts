/** Authenticated enrollment must not depend on a Store the session cannot read yet. */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement, type ReactNode, type ComponentType } from "react";
import test from "node:test";
import ts from "typescript";
const root=fileURLToPath(new URL("..",import.meta.url)),require=createRequire(import.meta.url);
class ApiError extends Error {status:number;code:string;constructor(status:number,code:string){super(code);this.status=status;this.code=code;}}
const account={username:"qa.synthetic",role:"superadmin",display_name:"",time_zone:"Asia/Tehran",mfa_enabled:false,mfa_required_by_role:true,password_policy:{min_length:14},preferences:{language:"fa",calendar:"auto",notify_orders:true,notify_campaigns:true,notify_finance:true,notify_system:true},sessions:[],permissions:["account.manage_self"],events:[]};
function fixture(failure=new ApiError(428,"mfa_enrollment_required")){
 const calls:string[]=[],cache=new Map<string,Record<string,unknown>>();
 function load(relative:string):Record<string,unknown>{
  const stem=path.resolve(root,relative),filename=[stem,stem+".ts",stem+".tsx"].find(existsSync)??stem;
  const prev=cache.get(filename);if(prev)return prev;const evaluated={exports:{} as Record<string,unknown>};cache.set(filename,evaluated.exports);
  const source=process.env.ACCOUNT_BASELINE==="1"?execFileSync("git",["show",`HEAD:dashboard-next/${path.relative(root,filename)}`],{cwd:root,encoding:"utf8"}):readFileSync(filename,"utf8");
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  runInNewContext(code,{module:evaluated,exports:evaluated.exports,require:(name:string)=>{
   if(name==="@/lib/bridge")return {ApiError,currentStaff:async()=>({id:1,username:"qa.synthetic",role:"superadmin"}),adminFetch:async(path:string)=>{calls.push(path);if(path==="/account")return account;throw failure;}};
   if(name==="next/navigation")return {redirect:(destination:string)=>{throw Object.assign(Error("redirect"),{destination});},useRouter:()=>({refresh(){},replace(){}}),usePathname:()=>"/account"};
   if(name.startsWith("@/"))return load(name.slice(2));if(name.startsWith("."))return load(path.relative(root,path.resolve(path.dirname(filename),name)));return require(name);
  }});return evaluated.exports;
 }
 return {calls,load};
}
test("personal account and enrollment render without fetching StoreContext",async()=>{
 const f=fixture(),legacy=process.env.ACCOUNT_BASELINE==="1";
 if(!legacy)assert(!existsSync(path.join(root,"app/(console)/account/page.tsx")),"account has exactly one route");
 const Page=f.load(legacy?"app/(console)/account/page.tsx":"app/account/page.tsx").default as ()=>Promise<ReactNode>;
 let content=await Page();if(legacy){const Layout=f.load("app/(console)/layout.tsx").default as (p:{children:ReactNode})=>Promise<ReactNode>;content=await Layout({children:content});}
 const html=renderToStaticMarkup(content);assert(html.includes("شروع فعال‌سازی MFA"));assert.deepEqual(f.calls,["/account"]);assert(!html.includes("فروشگاه فعال"));
});
test("non-MFA permission failures keep their original enforcement",async()=>{
 const failure=new ApiError(403,"permission_denied"),f=fixture(failure),Layout=f.load("app/(console)/layout.tsx").default as (p:{children:ReactNode})=>Promise<ReactNode>;
 await assert.rejects(Layout({children:"hidden"}),error=>error===failure);
});
test("required first enrollment exposes only its MFA controls",()=>{
 const f=fixture(),Panel=f.load("components/blocks/account-panel.tsx").AccountPanel as ComponentType<{initial:unknown}>;
 const html=renderToStaticMarkup(createElement(Panel,{initial:account}));assert(html.includes("شروع فعال‌سازی MFA"));assert(!html.includes("ذخیره مشخصات"));assert(!html.includes('name="new_password"'));
 assert(!html.includes('name="current_password"'), "the password just verified at login is not requested again for setup");
});
