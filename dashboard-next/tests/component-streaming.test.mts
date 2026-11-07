/** Exercise production page boundaries with controlled external GET reads. */
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { Writable } from "node:stream";
import { EventEmitter } from "node:events";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { renderToPipeableStream } from "react-dom/server";
import type { ReactNode } from "react";
import ts from "typescript";
const root=fileURLToPath(new URL("..",import.meta.url)),nativeRequire=createRequire(import.meta.url);
class ApiError extends Error {status:number;constructor(status:number,message:string){super(message);this.status=status;}}
function loader(read:(path:string)=>Promise<unknown>,role="superadmin") {
 const cache=new Map<string,Record<string,unknown>>();
 function load(relative:string):Record<string,unknown> {
  const stem=path.resolve(root,relative),filename=[stem,stem+".tsx",stem+".ts"].find(existsSync);assert(filename,relative);
  const old=cache.get(filename);if(old)return old;
  const evaluated={exports:{} as Record<string,unknown>};cache.set(filename,evaluated.exports);
  const code=ts.transpileModule(readFileSync(filename,"utf8"),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  runInNewContext(code,{module:evaluated,exports:evaluated.exports,require:(name:string)=>{
   if(name==="server-only")return {};
   if(name==="@/lib/bridge")return {ApiError,adminFetch:read,currentStaff:async()=>({id:11,username:"qa",role})};
   if(name==="next/navigation")return {notFound(){throw Error("NOT_FOUND");},useRouter:()=>({refresh(){}})};
   if(name==="@/app/(console)/orders/actions")return {reviewOrder:async()=>{throw Error("mutations_not_allowed");}};
   if(name.startsWith("@/"))return load(name.slice(2));
   if(name.startsWith("."))return load(path.relative(root,path.resolve(path.dirname(filename),name)));
   return nativeRequire(name);
  }});return evaluated.exports;
 }
 return Object.assign((name:string)=>load(`app/(console)/${name}/page.tsx`).default as (props:unknown)=>Promise<ReactNode>, {module:load});
}
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:unknown)=>void;const promise=new Promise<T>((done,fail)=>{resolve=done;reject=fail;});return {promise,resolve,reject};}
const pageData={items:[],total:0,page:1,page_size:20};
const order={id:77,platform:"bale",name:"QA_FAST_ORDER",status:"paid",total_irr:"1000",payment_currency:"IRR",payment_amount:"1000",created_at:"2026-11-06T00:00:00Z"};
async function shellBeforeRead(work:Promise<ReactNode>) {
 let done=false;void work.then(()=>{done=true;},()=>{done=true;});await new Promise(setImmediate);
 assert(done,"authorized page shell must resolve before its data response");return work;
}
async function stream(node:ReactNode){
 let html="";const events=new EventEmitter(),finished=deferred<void>();
 const target=new Writable({write(chunk,_encoding,callback){html+=chunk.toString();events.emit("chunk");callback();}});target.on("finish",()=>finished.resolve());
 const shell=deferred<void>();const result=renderToPipeableStream(node,{onShellReady(){result.pipe(target);shell.resolve();},onShellError(error){shell.reject(error);},onError(){}});
 await shell.promise;
 return {text:()=>html,done:finished.promise,abort:()=>result.abort(),waitFor(text:string){if(html.includes(text))return Promise.resolve();return new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>{events.off("chunk",check);reject(Error("missing streamed content: "+text));},5000);const check=()=>{if(html.includes(text)){clearTimeout(timer);events.off("chunk",check);resolve();}};events.on("chunk",check);});}};
}
test("product search controls render while matching results remain pending",async()=>{
 const held=deferred<unknown>(),calls:string[]=[];
 const work=loader(async path=>{calls.push(path);return held.promise;})("products")({searchParams:Promise.resolve({page:"2",search:"فیلتر روغن"})});
 let rendered:Awaited<ReturnType<typeof stream>>|undefined;
 try {rendered=await stream(await shellBeforeRead(work));await rendered.waitFor("جستجو در محصول و SKU");assert(rendered.text().includes('value="فیلتر روغن"'));assert(rendered.text().includes("در حال دریافت محصولات"));assert(!rendered.text().includes("هنوز محصولی ثبت نشده"));held.resolve({...pageData,page:2});await rendered.done;
 assert.deepEqual(calls,["/products?page=2&search=%D9%81%DB%8C%D9%84%D8%AA%D8%B1%20%D8%B1%D9%88%D8%BA%D9%86"]);
 }finally{held.resolve(pageData);rendered?.abort();await work;}
});
test("dashboard heading resolves before the single overview response",async()=>{
 const held=deferred<unknown>(),calls:string[]=[];const work=loader(async path=>{calls.push(path);return held.promise;})("dashboard")({});let rendered:Awaited<ReturnType<typeof stream>>|undefined;
 try{rendered=await stream(await shellBeforeRead(work));await rendered.waitFor("نمای کلی فروشگاه");assert(rendered.text().includes("در حال دریافت نمای کلی"));assert(!rendered.text().includes("محصولات تعریف‌شده"));held.resolve({products:0,published_products:0,open_refunds:0,channels:[],recent_orders:[],campaigns:{queued:0,unknown:0}});await rendered.done;assert.deepEqual(calls,["/overview"]);}finally{held.resolve({products:0,published_products:0,open_refunds:0,channels:[],recent_orders:[],campaigns:{queued:0,unknown:0}});rendered?.abort();await work;}
});
test("orders list completes while its independent review queue is pending",async()=>{
 const queue=deferred<unknown>();const work=loader(async path=>path==="/orders/review-queue"?queue.promise:{...pageData,items:[order]})("orders")({searchParams:Promise.resolve({})});let rendered:Awaited<ReturnType<typeof stream>>|undefined;
 try{rendered=await stream(await shellBeforeRead(work));await rendered.waitFor("QA_FAST_ORDER");assert(rendered.text().includes("در حال دریافت درخواست‌ها"));assert(!rendered.text().includes("سفارشی برای بررسی دستی موجود نیست"));queue.resolve([]);await rendered.done;}finally{queue.resolve([]);rendered?.abort();await work;}
});
test("finance renders orders without requesting or showing the review queue",async()=>{
 const calls:string[]=[];const page=await loader(async path=>{calls.push(path);return {...pageData,items:[order]};},"finance")("orders")({searchParams:Promise.resolve({})});const rendered=await stream(page);await rendered.done;assert.deepEqual(calls,["/orders?page=1"]);assert(!rendered.text().includes("درخواست‌های نیازمند بررسی دستی"));rendered.abort();
});
test("unauthorized order role is rejected before any protected data read",async()=>{
 const calls:string[]=[];await assert.rejects(loader(async path=>{calls.push(path);return pageData;},"viewer")("orders")({searchParams:Promise.resolve({})}),/NOT_FOUND/);assert.deepEqual(calls,[]);
});
test("service failure replaces only the queue and never exposes private backend text",async()=>{
 const page=await loader(async path=>{if(path==="/orders/review-queue")throw new ApiError(503,"PRIVATE_PROVIDER_SECRET");return {...pageData,items:[order]};})("orders")({searchParams:Promise.resolve({})});const rendered=await stream(page);await rendered.done;assert(rendered.text().includes("QA_FAST_ORDER"));assert(rendered.text().includes("درخواست‌ها دریافت نشدند"));assert(!rendered.text().includes("PRIVATE_PROVIDER_SECRET"));assert(!rendered.text().includes("سفارشی برای بررسی دستی موجود نیست"));rendered.abort();
});

for (const status of [401, 403, 409, 429]) {
 test(`section read preserves the original ${status} failure`, async () => {
  const failure = new ApiError(status, "protected response");
  const {readSection} = loader(async () => {throw failure;}).module("lib/read-section") as {
   readSection: (path: string) => Promise<unknown>;
  };
  await assert.rejects(readSection("/products"), error => error === failure);
 });
}
test("section read preserves redirects and unexpected failures", async () => {
 for (const failure of [Object.assign(new Error("redirect"), {digest:"NEXT_REDIRECT;replace;/login;307;"}), new TypeError("bad response")]) {
  const {readSection} = loader(async () => {throw failure;}).module("lib/read-section") as {
   readSection: (path: string) => Promise<unknown>;
  };
  await assert.rejects(readSection("/overview"), error => error === failure);
 }
});
