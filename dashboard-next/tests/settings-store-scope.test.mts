/** Render the real Settings page across supported and restricted Store scopes. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";
import ts from "typescript";

const compiled=ts.transpileModule(readFileSync(new URL("../app/(console)/settings/page.tsx",import.meta.url),"utf8"),{
  compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
}).outputText;
class ApiError extends Error {
  status:number;code:string;
  constructor(status:number,code:string){super(code);this.status=status;this.code=code;}
}

/** Substitute transport and child renderers, retaining the page's real decisions. */
async function page(mode:"supported"|"restricted"|"failure") {
  const requests:string[]=[];
  async function read(path:string):Promise<unknown> {
    requests.push(path);
    if(path==="/settings")return {brand_name:"CURRENT_STORE_BRAND"};
    if(path==="/pwa-settings")return {name:"مدیریت فروشگاه",short_name:"فروشگاه",theme_color:"#146b66",version:0};
    if(mode==="restricted")throw new ApiError(409,"store_scope_not_supported");
    if(mode==="failure")throw new ApiError(503,"service_unavailable");
    return path==="/referral-policy"?{is_enabled:false,percent:0,min_order_irr:"0",max_bonus_irr:"0"}:{items:[]};
  }
  const Box=({children}:{children:ReactNode})=>createElement("div",null,children);
  const Link=({href,children}:{href:string;children:ReactNode})=>createElement("a",{href},children);
  const deps:Record<string,unknown>={
    "react/jsx-runtime":jsx,"next/link":{default:Link},"next/navigation":{notFound(){throw Error("404");}},
    "@/app/(console)/settings/actions":{saveChannelFeatures(){},savePaymentRails(){},saveReferralPolicy(){},savePwaAppearance(){}},
    "@/components/blocks/shop-settings-form":{ShopSettingsForm:({initial}:{initial:{brand_name:string}})=>createElement("p",{"data-brand":true},initial.brand_name)},
    "@/components/blocks/page-heading":{PageHeading:({title}:{title:string})=>createElement("h1",null,title)},
    "@/components/ui/card":{Card:Box,CardHeader:Box,CardContent:Box,CardTitle:Box,CardDescription:Box},
    "@/components/ui/input":{Input:(props:Record<string,unknown>)=>createElement("input",props)},
    "@/components/ui/button":{Button:Box},
    "@/lib/bridge":{
      ApiError,currentStaff:async()=>({role:"superadmin"}),adminFetch:read,
      optionalStoreRead:(path:string)=>mode==="restricted"?Promise.resolve(null):read(path),
    },
  };
  const evaluatedModule={exports:{} as {default:(props:unknown)=>Promise<ReactNode>}};
  runInNewContext(compiled,{module:evaluatedModule,exports:evaluatedModule.exports,require:(name:string)=>{assert(name in deps,name);return deps[name];}});
  const node=await evaluatedModule.exports.default({searchParams:Promise.resolve({})});
  return {html:renderToStaticMarkup(node),requests};
}

test("Store branding remains editable when unrelated global controls are restricted",async()=>{
  const result=await page("restricted");
  assert.match(result.html,/CURRENT_STORE_BRAND/);
  assert.match(result.html,/href="\/bots"/);
  assert.match(result.html,/href="\/payment-accounts"/);
  assert(!result.html.includes("store_scope_not_supported"));
});
test("Store settings use bot-specific commerce and payment controls",async()=>{
  const result=await page("supported");
  for(const text of ["CURRENT_STORE_BRAND","پاداش معرفی مشتری"])assert(result.html.includes(text),text);
  assert(!result.requests.includes("/channel-features"));
  assert(!result.requests.includes("/payment-rails"));
});
test("Settings does not disguise an unrelated service failure as Store availability",async()=>{
  await assert.rejects(page("failure"),(error:unknown)=>error instanceof ApiError&&error.status===503);
});
