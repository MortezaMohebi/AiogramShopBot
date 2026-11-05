/** Render actual Runtime views with safe transport doubles; raw private data must never enter HTML. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
const privateText="PRIVATE_CUSTOMER_PHONE_FILE_PROOF_DO_NOT_RENDER";
function evaluate(file:string,deps:Record<string,unknown>,expose=""){
 const code=ts.transpileModule(readFileSync(new URL(file,import.meta.url),"utf8"),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 const mod={exports:{} as Record<string,unknown>};
 runInNewContext(code+expose,{module:mod,exports:mod.exports,require:(key:string)=>{assert.ok(key in deps,`Missing test dependency ${key}`);return deps[key];},Date,Number,console});return mod.exports;
}
const jsx=await import("react/jsx-runtime"),React=await import("react");
const Link=({href,children,...props}:Record<string,unknown>)=>createElement("a",{href,...props},children as never);
const Button=({children,...props}:Record<string,unknown>)=>createElement("button",props,children as never);
const Badge=({children}:Record<string,unknown>)=>createElement("span",null,children as never);
const state=await import("../lib/runtime/state.ts");
const shared=evaluate("../components/runtime/shared.tsx",{"react/jsx-runtime":jsx,"next/link":{default:Link},"@/components/ui/badge":{Badge},"@/lib/runtime/state":state});
let recoveryProps: unknown;
const operations={RetryDelivery:()=>null,ApproveAction:()=>null,RecoverRun:(props:unknown)=>{recoveryProps=props;return null;}};
const lists=evaluate("../components/runtime/lists.tsx",{"react/jsx-runtime":jsx,"next/link":{default:Link},"./shared":shared,"./operations":operations});
test("delivery HTML distinguishes queued, sent and unknown without outbound payloads",()=>{
 const items=["pending","sent","uncertain"].map((status,index)=>({id:`d${index}`,run_id:"r",node_id:"n",kind:"text",sequence:index,attempts:1,status,message_ids:[],error_code:status==="uncertain"?"runtime_delivery_unknown":null,payload:{text:privateText}}));
 const html=renderToStaticMarkup(createElement(lists.RuntimeDeliveries as never,{items,canManage:false}));
 assert.match(html,/در صف ارسال/);assert.match(html,/ارسال‌شده/);assert.match(html,/نتیجهٔ ارسال نامعلوم/);assert.match(html,/ارسال دوباره ارائه نمی‌شود/);assert.ok(!html.includes(privateText));
});
test("Run detail ignores variable values and unrecognized raw event summary fields",async()=>{
 const run={id:"f423a748-9c8c-4065-9ece-37d132002677",store_id:"store",bot_id:"bot",workflow_id:"workflow",publication_id:"published",node_id:"node",platform:"telegram",status:"suspended",lock_version:2,revision:1,created_at:"2026-11-05T00:00:00Z",updated_at:"2026-11-05T00:00:00Z",expires_at:"2026-11-05T12:00:00Z",correlation_id:"correlation",variables:[{name:"phone",type:"string",is_set:true,value:privateText}],actions:[{id:"job",key:"wholesale.create_application",version:"1.0.0",node_id:"action",status:"succeeded",receipt_id:"receipt",attempts:1,error_code:null,output:privateText}],outbox:[],events:[{id:"event",kind:"text",node_id:"node",status:"waiting_input",created_at:"2026-11-05T00:00:00Z",summary:{text:privateText,file:privateText,proof:privateText,characters:5,has_file:true}}]};
 const page=evaluate("../app/(console)/studio/runtime/runs/[id]/page.tsx",{"react/jsx-runtime":jsx,"next/link":{default:Link},"next/navigation":{notFound:()=>{throw Error("404");}},"@/lib/bridge":{adminFetch:async(path:string)=>path.includes("/runs/")?run:{can_manage:false},ApiError:Error},"@/components/blocks/page-heading":{PageHeading:({title}:Record<string,unknown>)=>createElement("h1",null,title as never)},"@/components/workflows/studio-home-nav":{StudioHomeNav:()=>null},"@/components/runtime/shared":shared,"@/components/runtime/lists":lists,"@/components/runtime/operations":operations,"@/components/runtime/refresh":{RuntimeRefresh:()=>null}});
 const element=await (page.default as (props:unknown)=>Promise<ReturnType<typeof createElement>>)({params:Promise.resolve({id:run.id})});
 const html=renderToStaticMarkup(element);assert.ok(!html.includes(privateText));assert.ok(!JSON.stringify(recoveryProps).includes(privateText));assert.ok(!JSON.stringify(recoveryProps).includes("variables"));assert.match(html,/خصوصی/);assert.match(html,/receipt/);assert.match(html,/۵|5/);
});
test("read-only gates do not render controls and absent gates stay disabled",()=>{
 const gates=evaluate("../components/runtime/gates.tsx",{"react/jsx-runtime":jsx,react:React,"@/components/ui/button":{Button},"@/components/ui/badge":{Badge},"./shared":shared,"./use-mutation":{useRuntimeMutation:()=>({disabled:false,state:{status:"idle"}}),RuntimeMutationNotice:()=>null},"@/lib/runtime/state":state});
 const html=renderToStaticMarkup(createElement(gates.RuntimeGates as never,{overview:{global_enabled:true,global_killed:false,can_manage:false,gates:[]},bots:[{id:"bot",name:"ربات",platform:"bale",status:"active"}],storeId:"f423a748-9c8c-4065-9ece-37d132002677"}));
 assert.match(html,/غیرفعال/);assert.match(html,/دسترسی این حساب برای مشاهده/);assert.ok(!html.includes('type="checkbox"'));assert.ok(!html.includes('<form'));
});

test("publication preview attributes selected and retained entries to each Bot without implying replacement",()=>{
 const botA="f423a748-9c8c-4065-9ece-37d132002677",botB="2a74c464-402d-4e17-8939-d9d94f52f760",oldPublication="2c92dcba-aa29-4fef-9fb1-5e36b964b93d";
 const pointer=(id:string,bot_id:string,key:string)=>({id,bot_id,kind:"command",key,node_id:"start",version:1,publication_id:oldPublication,enabled:true});
 const previous=[pointer("p1",botA,"apply"),pointer("p2",botA,"old"),pointer("p3",botB,"apply")];
 const next=[botA,botB].map(bot_id=>({bot_id,kind:"command",key:"apply",node_id:"start",priority:0,enabled:true,eligibility:"all",fallback:"legacy",version_policy:"active_publication"}));
 const preview={preview_id:"e1d67cfa-4fd2-45a2-b72a-78aaec98258d",expires_at:"2099-01-01T00:00:00Z",ready:true,issues:[],dependencies:[],mutating_nodes:[],platforms:["telegram"],diff:{previous_revision:1,next_revision:2,definition_changed:true,previous_bindings:previous,next_bindings:next,unchanged_bindings:[previous[1]],retains_unselected_bindings:true}};
 let hookIndex=0;
 const previewReact={...React,useState:(value:unknown)=>{const index=hookIndex++;return React.useState(index===1?preview:value);}};
 const evaluatedModule=evaluate("../components/runtime/publication.tsx",{"react/jsx-runtime":jsx,react:previewReact,"next/link":{default:Link},"@/components/ui/button":{Button},"@/components/ui/input":{Input:(props:unknown)=>createElement("input",props as never)},"@/components/workflows/fields":{Field:({children}:Record<string,unknown>)=>createElement("div",null,children as never),Select:()=>null},"@/lib/workflows/client":{workflowRequest:async()=>({})},"@/lib/runtime/client":{runtimeRequest:async()=>({}),runtimeErrorText:()=>"error"},"@/lib/runtime/state":state,"./shared":shared,"./use-mutation":{useRuntimeMutation:()=>({disabled:false,state:{status:"idle"}}),RuntimeMutationNotice:()=>null},"./operations":{RetirePublication:()=>null}},"\nmodule.exports.reviewForm = ReviewForm;");
 const source={id:"workflow",name:"test",revision:2,definition:{target_platforms:["telegram"],assignment:{mode:"all_eligible",bot_ids:[]},entry_points:[{kind:"command",key:"apply",node_id:"start"}]}};
 const bots=[{id:botA,name:"Bot A",platform:"telegram",status:"active"},{id:botB,name:"Bot B",platform:"telegram",status:"active"}];
 const html=renderToStaticMarkup(createElement(evaluatedModule.reviewForm as never,{source,bots,bindings:[],canPublish:true,rollback:false}));
 assert.match(html,/ورودی‌های انتخاب‌شده برای تغییر/);
 assert.match(html,/ورودی‌های انتخاب‌نشده که حفظ می‌شوند/);
 assert.match(html,/ورودی‌های انتخاب‌نشده حذف یا غیرفعال نمی‌شوند/);
 assert.match(html,/ورودی‌های ربات‌های دیگر هم بدون تغییر باقی می‌مانند/);
 assert.ok(!html.includes("ورودی‌های پس از تأیید"));
 const before=html.slice(html.indexOf("ورودی‌های فعلی ربات‌های انتخابی"),html.indexOf("ورودی‌های انتخاب‌شده برای تغییر"));
 assert.ok(before.includes(botA));assert.ok(before.includes(botB));
 const retained=html.slice(html.indexOf("ورودی‌های انتخاب‌نشده که حفظ می‌شوند"));
 assert.ok(retained.includes("command:old"));assert.ok(retained.includes(botA));assert.ok(retained.includes(oldPublication));
});
