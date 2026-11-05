/** Exercise the real browser transport with independent tabs sharing a CSRF cookie. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import * as receipts from "../lib/runtime/receipts.ts";
const code=ts.transpileModule(readFileSync(new URL("../lib/runtime/client.ts",import.meta.url),"utf8"),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function client(fetcher:(url:string,request:RequestInit)=>Promise<unknown>, challenge=async()=>"test-challenge",locks?:unknown){
 const mod={exports:{} as {runtimeRequest:(path:string,method?:string,payload?:unknown,context?:unknown)=>Promise<unknown>;runtimeErrorText:(error:unknown)=>string}};
 runInNewContext(code,{module:mod,exports:mod.exports,require:(key:string)=>{if(key==="@/lib/runtime/receipts")return receipts;assert.equal(key,"@/lib/browser-challenge");return {requestBrowserChallenge:challenge};},navigator:{locks},fetch:fetcher,AbortSignal});
 return mod.exports;
}
test("runtime uses same-origin no-store requests and serializes challenge creation across tabs",async()=>{
 let cookie="",tail=Promise.resolve(),count=0;const calls:string[]=[];
 const locks={request:(name:string,run:()=>Promise<unknown>)=>{assert.equal(name,"shop-admin-workflow-csrf");const next=tail.then(run);tail=next.then(()=>undefined,()=>undefined);return next;}};
 const challenge=async()=>{cookie=String(++count);await Promise.resolve();return cookie;};
 const fetcher=async(url:string,request:RequestInit)=>{assert.equal(url,"/api/admin/workflow-runtime/gates");assert.equal(request.credentials,"same-origin");assert.equal(request.cache,"no-store");assert.equal((request.headers as Record<string,string>)["x-shop-login-challenge"],cookie);calls.push(JSON.parse(request.body as string).operation_id);const payload=JSON.parse(request.body as string);return Response.json({scope_key:`bot:${payload.bot_id}`,operation_id:payload.operation_id,replayed:true});};
 const a=client(fetcher,challenge,locks),b=client(fetcher,challenge,locks);
 await Promise.all([a.runtimeRequest("/gates","POST",{bot_id:targetId,operation_id:operationId}),b.runtimeRequest("/gates","POST",{bot_id:targetId,operation_id:otherId})]);
 assert.deepEqual(calls,[operationId,otherId]);
});
test("lost response is unknown and never automatically replayed",async()=>{
 let calls=0;const c=client(async()=>{calls++;throw new TypeError("private upstream failure");});
 await assert.rejects(c.runtimeRequest("/gates","POST",{}),(error:unknown)=>(error as {status:number;code:string}).status===0 && (error as {code:string}).code==="network_unavailable");
 assert.equal(calls,1);
});
test("malformed success response after mutation is an unknown outcome",async()=>{
 const c=client(async()=>new Response("private raw response",{status:200}));
 await assert.rejects(c.runtimeRequest("/gates","POST",{}),(error:unknown)=>(error as {status:number}).status===0);
});
test("stale fresh-auth result preserves reauthentication requirement without replay or proof weakening",async()=>{
 let calls=0;const c=client(async()=>{calls++;return Response.json({code:"reauthentication_required"},{status:428});});
 let captured:unknown;
 try{await c.runtimeRequest("/publications/activate","POST",{preview_id:"p",approved:true});}catch(error){captured=error;}
 assert.equal((captured as {status:number}).status,428);
 assert.equal((captured as {code:string}).code,"reauthentication_required");
 assert.match(c.runtimeErrorText(captured),/MFA/);assert.equal(calls,1);
});
test("GET reads do not request a challenge",async()=>{
 const c=client(async()=>Response.json({items:[]}),async()=>{throw Error("must not request challenge");});
 assert.ok(await c.runtimeRequest("/history"));
});

const targetId="f423a748-9c8c-4065-9ece-37d132002677";
const operationId="2c92dcba-aa29-4fef-9fb1-5e36b964b93d";
const previewId="e1d67cfa-4fd2-45a2-b72a-78aaec98258d";
const otherId="2a74c464-402d-4e17-8939-d9d94f52f760";
const mutationCases=[
 {path:"/gates",payload:{bot_id:targetId,expected_version:2,enabled:false,killed:true,operation_id:operationId},receipt:{scope_key:`bot:${targetId}`,operation_id:operationId,replayed:false,version:3,enabled:false,killed:true}},
 {path:`/runs/${targetId}/recover`,payload:{expected_version:2,operation:"cancel",operation_id:operationId},receipt:{id:targetId,operation_id:operationId,replayed:true}},
 {path:`/publications/${targetId}/retire`,payload:{operation_id:operationId},receipt:{publication_id:targetId,operation_id:operationId,retired:true,replayed:false}},
 {path:`/actions/${targetId}/approve`,payload:{expected_version:2,operation_id:operationId},receipt:{job_id:targetId,operation_id:operationId,status:"pending",lock_version:3,replayed:false}},
 {path:`/outbox/${targetId}/retry`,payload:{expected_attempts:2,operation_id:operationId},receipt:{id:targetId,operation_id:operationId,status:"retryable",replayed:false}},
 {path:"/publications/activate",payload:{preview_id:previewId,approved:true},receipt:{publication_id:targetId,preview_id:previewId,revision:4,replayed:false}},
];
for(const spec of mutationCases) {
 for(const [name,body] of [["null",null],["empty object",{}],["array",[]],["false success envelope",{ok:false,code:"runtime_invalid_request"}]] as const)
  test(`${spec.path} treats HTTP-200 ${name} as unknown without replay`,async()=>{
   let calls=0;const c=client(async()=>{calls++;return Response.json(body);});
   await assert.rejects(c.runtimeRequest(spec.path,"POST",spec.payload),(error:unknown)=>(error as {status:number;code:string}).status===0 && (error as {code:string}).code==="runtime_outcome_unknown");
   assert.equal(calls,1);
  });
 test(`${spec.path} accepts its exact authoritative receipt`,async()=>{
  const c=client(async()=>Response.json(spec.receipt));
  assert.deepEqual(await c.runtimeRequest(spec.path,"POST",spec.payload),spec.receipt);
 });
 const identityKey="operation_id" in spec.receipt?"operation_id":"preview_id";
 test(`${spec.path} rejects a receipt for a different local intent`,async()=>{
  const c=client(async()=>Response.json({...spec.receipt,[identityKey]:otherId}));
  await assert.rejects(c.runtimeRequest(spec.path,"POST",spec.payload),(error:unknown)=>(error as {status:number}).status===0);
 });
}
test("bot gate cannot accept a different target or flags/version even with exact operation ID",async()=>{
 const spec=mutationCases[0];
 for(const patch of [{scope_key:`bot:${otherId}`},{enabled:true},{killed:false},{version:2},{replayed:"false"},{ok:false}]){
  const c=client(async()=>Response.json({...spec.receipt,...patch}));
  await assert.rejects(c.runtimeRequest(spec.path,"POST",spec.payload),(error:unknown)=>(error as {status:number}).status===0);
 }
});
test("Store gate must match the current Store scope independently of Bot gates",async()=>{
 const payload={bot_id:null,expected_version:0,enabled:true,killed:false,operation_id:operationId};
 const c=client(async()=>Response.json({scope_key:`store:${otherId}`,operation_id:operationId,replayed:true}));
 await assert.rejects(c.runtimeRequest("/gates","POST",payload,{scopeKey:`store:${targetId}`}),(error:unknown)=>(error as {status:number}).status===0);
});
for(const [path,payload,body] of [
 [`/runs/${targetId}/recover`,{expected_version:2,operation:"resume",operation_id:operationId},{id:otherId,operation_id:operationId,replayed:true}],
 [`/publications/${targetId}/retire`,{operation_id:operationId},{publication_id:otherId,operation_id:operationId,retired:true,replayed:true}],
 [`/actions/${targetId}/approve`,{expected_version:2,operation_id:operationId},{job_id:otherId,operation_id:operationId,replayed:true}],
 [`/outbox/${targetId}/retry`,{expected_attempts:2,operation_id:operationId},{id:otherId,operation_id:operationId,replayed:true}],
] as const) test(`${path} rejects replay evidence for a different target`,async()=>{
 const c=client(async()=>Response.json(body));await assert.rejects(c.runtimeRequest(path,"POST",payload),(error:unknown)=>(error as {status:number}).status===0);
});
test("activation binds the new receipt revision to the reviewed preview",async()=>{
 const c=client(async()=>Response.json({publication_id:targetId,preview_id:previewId,revision:5,replayed:false}));
 await assert.rejects(c.runtimeRequest("/publications/activate","POST",{preview_id:previewId,approved:true},{revision:4}),(error:unknown)=>(error as {status:number}).status===0);
});
for(const spec of mutationCases) test(`${spec.path} accepts the documented minimal replay receipt`,async()=>{
 const body={...spec.receipt,replayed:true} as Record<string,unknown>;
 for(const key of ["version","enabled","killed","revision","status","lock_version"])delete body[key];
 const c=client(async()=>Response.json(body));assert.deepEqual(await c.runtimeRequest(spec.path,"POST",spec.payload),body);
});
test("fresh recovery needs complete Run evidence and the requested terminal state",async()=>{
 const payload={expected_version:2,operation:"cancel",operation_id:operationId};
 const body={id:targetId,operation_id:operationId,replayed:false,store_id:otherId,bot_id:otherId,workflow_id:otherId,publication_id:otherId,node_id:"start",platform:"telegram",status:"cancelled",lock_version:3,created_at:"2026-11-05T00:00:00Z",updated_at:"2026-11-05T00:00:00Z",expires_at:"2099-01-01T00:00:00Z",correlation_id:targetId,error_code:"runtime_operator_cancel"};
 assert.deepEqual(await client(async()=>Response.json(body)).runtimeRequest(`/runs/${targetId}/recover`,"POST",payload),body);
 for(const patch of [{status:"failed"},{lock_version:2},{bot_id:null},{expires_at:null},{error_code:[]}])await assert.rejects(client(async()=>Response.json({...body,...patch})).runtimeRequest(`/runs/${targetId}/recover`,"POST",payload),(error:unknown)=>(error as {status:number}).status===0);
});
test("a fresh Store gate receipt must echo its exact Store, flags and next version",async()=>{
 const payload={bot_id:null,expected_version:0,enabled:true,killed:false,operation_id:operationId};
 const body={scope_key:`store:${targetId}`,operation_id:operationId,replayed:false,version:1,enabled:true,killed:false};
 assert.deepEqual(await client(async()=>Response.json(body)).runtimeRequest("/gates","POST",payload,{scopeKey:`store:${targetId}`}),body);
});
test("publication preview binds saved revision, selected edits and retained pointers",async()=>{
 const entry={bot_id:targetId,kind:"command",key:"apply",node_id:"start",priority:0,enabled:true,eligibility:"all",fallback:"legacy",version_policy:"active_publication"};
 const retained={id:otherId,bot_id:targetId,kind:"command",key:"old",node_id:"old_start",publication_id:otherId,version:1,enabled:true};
 const payload={workflow_id:targetId,revision:4,bindings:[entry]};
 const body={preview_id:previewId,expires_at:"2099-01-01T00:00:00Z",ready:true,issues:[],dependencies:[],mutating_nodes:[],platforms:["telegram"],diff:{previous_revision:1,next_revision:4,definition_changed:true,previous_bindings:[retained],next_bindings:[entry],unchanged_bindings:[retained],retains_unselected_bindings:true}};
 assert.deepEqual(await client(async()=>Response.json(body)).runtimeRequest("/publications/preview","POST",payload),body);
 const comparison={bot_id:targetId,kind:"command",key:"apply",previous_revision:null,previous_publication_id:null,definition_changed:true};
 const grouped={...body,diff:{...body.diff,previous_revision:null,binding_comparisons:[comparison]}};
 assert.deepEqual(await client(async()=>Response.json(grouped)).runtimeRequest("/publications/preview","POST",payload),grouped);
 for(const comparisons of [[],[comparison,comparison],[{...comparison,key:"old"}],[{...comparison,previous_publication_id:otherId,previous_revision:1}],[{...comparison,definition_changed:false}]]) {
   await assert.rejects(client(async()=>Response.json({...grouped,diff:{...grouped.diff,binding_comparisons:comparisons}})).runtimeRequest("/publications/preview","POST",payload));
 }
 for(const patch of [{next_revision:5},{next_bindings:[{...entry,bot_id:otherId}]},{unchanged_bindings:[]},{retains_unselected_bindings:false},...(["priority","enabled","eligibility","fallback","version_policy"] as const).map(key=>({next_bindings:[{...entry,[key]:null}]}))])await assert.rejects(client(async()=>Response.json({...body,diff:{...body.diff,...patch}})).runtimeRequest("/publications/preview","POST",payload),(error:unknown)=>(error as {status:number}).status===0);
});
test("approved and retry receipts cannot claim an unexpected execution or delivery state",async()=>{
 for(const spec of [mutationCases[3],mutationCases[4]])await assert.rejects(client(async()=>Response.json({...spec.receipt,status:"succeeded"})).runtimeRequest(spec.path,"POST",spec.payload),(error:unknown)=>(error as {status:number}).status===0);
});
