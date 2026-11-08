/** Exercise the actual mutation hook and transport without running live administrative writes. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import * as jsx from "react/jsx-runtime";
import ts from "typescript";
const targetId="f423a748-9c8c-4065-9ece-37d132002677";
const operationId="2c92dcba-aa29-4fef-9fb1-5e36b964b93d";
const otherId="2a74c464-402d-4e17-8939-d9d94f52f760";
function evaluate(file:string,require:(key:string)=>unknown) {
 const source=readFileSync(new URL(file,import.meta.url),"utf8");
 const code=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 const mod={exports:{} as Record<string,unknown>};
 runInNewContext(code,{module:mod,exports:mod.exports,require,AbortSignal,Date,JSON});return mod.exports;
}
function hook(fetcher:(url:string,request:RequestInit)=>Promise<Response>,refresh:()=>void=()=>undefined){
 const receipts=()=>evaluate("../lib/runtime/receipts.ts",()=>{throw Error("No runtime dependency expected");});
 // The transport's global fetch is provided through a second isolated evaluation.
 const source=ts.transpileModule(readFileSync(new URL("../lib/runtime/client.ts",import.meta.url),"utf8"),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 const clientModule={exports:{} as Record<string,unknown>};
 runInNewContext(source,{module:clientModule,exports:clientModule.exports,require:(key:string)=>key==="@/lib/browser-challenge"?{requestBrowserChallenge:async()=>"challenge"}:receipts(),fetch:fetcher,AbortSignal});
 const values:unknown[]=[];let index=0;
 const react={
  useState:(initial:unknown)=>{const slot=index++;if(!(slot in values))values[slot]=typeof initial==="function"?(initial as ()=>unknown)():initial;return [values[slot],(next:unknown)=>{values[slot]=typeof next==="function"?(next as (old:unknown)=>unknown)(values[slot]):next;}];},
  useRef:(initial:unknown)=>{const slot=index++;if(!(slot in values))values[slot]={current:initial};return values[slot];},
  useEffect:(effect:()=>unknown)=>{effect();},
 };
 const evaluatedModule=evaluate("../components/runtime/use-mutation.tsx",key=>{
  if(key==="react")return react;
  if(key==="react/jsx-runtime")return jsx;
  if(key==="next/navigation")return {useRouter:()=>({refresh})};
  if(key==="@/components/blocks/reauthentication")return {ReauthenticateButton:()=>null};
  if(key==="@/components/ui/button")return {Button:()=>null};
  if(key==="@/lib/runtime/client")return clientModule.exports;
  if(key==="@/lib/runtime/receipts")return receipts();
  throw Error(key);
 });
 return ()=>{index=0;return (evaluatedModule.useRuntimeMutation as ()=>{state:{status:string;message:string;intent?:{path:string;payload:unknown}};execute:(path:string,payload:unknown,message:string,evidence?:unknown)=>Promise<void>;inspect:()=>Promise<void>;disabled:boolean})()};
}
for(const body of [null,{},[],{ok:false,code:"runtime_invalid_request"}])test(`invalid HTTP-200 body ${JSON.stringify(body)} cannot become done or replayed`,async()=>{
 let posts=0;const render=hook(async()=>{posts++;return Response.json(body);});
 const payload={expected_attempts:2,operation_id:operationId};
 await render().execute(`/outbox/${targetId}/retry`,payload,"COMMITTED_SUCCESS",{operationId});
 let current=render();assert.equal(current.state.status,"unknown");assert.ok(!current.state.message.includes("COMMITTED_SUCCESS"));assert.equal(current.disabled,true);
 payload.expected_attempts=99;
 assert.deepEqual(JSON.parse(JSON.stringify(current.state.intent)),{path:`/outbox/${targetId}/retry`,payload:{expected_attempts:2,operation_id:operationId},context:{}});
 await current.execute(`/outbox/${targetId}/retry`,payload,"COMMITTED_SUCCESS");current=render();assert.equal(current.state.status,"unknown");assert.equal(posts,1);
});
test("unknown intent only reconciles an audit with the exact operation, action and target",async()=>{
 let posts=0,correct=false,refreshes=0;
 const render=hook(async(_url,request)=>{if(request.method==="POST"){posts++;throw Error("lost");}return Response.json({items:[{id:operationId,action:"retry_delivery",target_id:correct?targetId:otherId,summary:{},created_at:"2026-11-05T00:00:00Z"}],page:1,has_more:false});},()=>refreshes++);
 await render().execute(`/outbox/${targetId}/retry`,{expected_attempts:2,operation_id:operationId},"COMMITTED_SUCCESS",{operationId});
 await render().inspect();assert.equal(render().state.status,"unknown");assert.equal(posts,1);assert.equal(refreshes,0,"unmatched history must not remount version-keyed forms and erase a frozen unknown intent");
 correct=true;await render().inspect();assert.equal(render().state.status,"done");assert.equal(posts,1);assert.equal(refreshes,1);
});
