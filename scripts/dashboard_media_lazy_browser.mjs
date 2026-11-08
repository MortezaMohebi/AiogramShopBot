/** Exercise production image/UI components in an isolated, read-only preview fixture. */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync, existsSync, unlinkSync, rmdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
const base="http://127.0.0.1:3005",output="/tmp/dashboard-lazy-media",dir="dashboard-next/app/lazy-media-ui-qa";
const env=Object.fromEntries(readFileSync(".codespaces/mcp-qa.env","utf8").trim().split("\n").map(line=>[line.slice(0,line.indexOf("=")),line.slice(line.indexOf("=")+1)]));
assert.equal(env.SHOP_MCP_QA,"1");assert.equal(env.SHOP_BETA_QA,"1");
for(const key of ["TOKEN","BALE_BOT_TOKEN","BALE_WALLET_PROVIDER_TOKEN","TELEGRAM_FIAT_PROVIDER_TOKEN"])assert.equal(env[key],"");
const fixture=`"use client";
import { useState } from "react";
import { MediaThumbnail } from "@/components/blocks/media-thumbnail";
import { ProductMediaPanel } from "@/components/blocks/product-media-panel";
import { ThemeToggle } from "@/components/blocks/theme-toggle";
import { Button } from "@/components/ui/button";
export default function Fixture(){const [id,setId]=useState(4);return <main className="mx-auto max-w-4xl space-y-6 p-5">
<h1>پیش‌نمایش آزمایشی بارگذاری تصویر</h1><ThemeToggle />
<div className="flex flex-wrap gap-4">
<div data-case="slow"><p>در حال دریافت</p><MediaThumbnail mediaId={1} mimeType="image/png" alt="تصویر نمونهٔ آزمایشی" /></div>
<div data-case="error"><p>تصویر ناموجود</p><MediaThumbnail mediaId={2} mimeType="image/png" alt="تصویر ناموجود آزمایشی" /></div>
<div data-case="replace"><p>جایگزینی منبع</p><MediaThumbnail mediaId={id} mimeType="image/png" alt="تصویر جایگزین آزمایشی" /><Button onClick={()=>setId(5)}>تعویض تصویر نمونه</Button></div>
</div>
<ProductMediaPanel productId={1} initial={[{id:6,filename:"qa-product-image-with-a-long-file-name-for-RTL-layout.png",kind:"photo",mime_type:"image/png",size_bytes:600,caption:"تصویر نمونهٔ آزمایشی",is_published:false},{id:7,filename:"qa-document.pdf",kind:"document",mime_type:"application/pdf",size_bytes:600,caption:null,is_published:false}]} />
<div style={{height:6000}} aria-hidden="true" />
<div data-case="far"><p>تصویر پایین صفحه</p><MediaThumbnail mediaId={3} mimeType="image/png" alt="تصویر نمونهٔ پایین صفحه" /></div>
</main>;}
`;
if(process.argv.includes("--prepare")) {
 assert(!existsSync(dir),"refuse to overwrite an existing route");mkdirSync(dir);writeFileSync(dir+"/page.tsx",fixture);console.log("Isolated image fixture prepared");process.exit(0);
}
assert.equal(readFileSync(dir+"/page.tsx","utf8"),fixture,"only remove the owned fixture");
mkdirSync(output,{recursive:true});
const evidence={status:"RUNNING",fixture:"offline PNG responses; production components; no business data",checks:[],screenshots:[],errors:[],blocked_mutations:0};
const save=()=>writeFileSync(output+"/evidence.json",JSON.stringify(evidence,null,2));
const png=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAAC50lEQVR4nO3cT0iTcRzH8a9bbWxJsyY5pS1INNbm+nOIGEYasrxEYYcQPHYJjOgYWAwMolNUl6Br1MX+HAXJJMsMb4I5N+2QypLEsImDYdjhgfISH57f89jveeLzujnGsy9vvs82tsdVTRfnhf7Oo3sAp2MggIEABgIYCGAggIEABgIYCGAggIEABgIYCGAggIGAHTYe69TtfhuPZtFo301bjlNlywdmjkqzlfVMVgM5Ns1WVjJZeg5yRR2xNqd6ILfUMShPqxjIXXUMajPzZR5QCeTG9TEoTM4NAkwHcu/6GMzOzw0CGAhgIICBAAYCGAhgIICBAAYCGAhgIICBAAYCGAhgIICBAAYCGAiw87t5Bd0n05dPt1c2NnZ6vY/evB6Y+Gjc3pNuvXup+2jfjW+lH3on1BmoPZ7oSbd2Pbi3Wl4PBYJPr/Qufl/5MFsQkbMtqccjwx2J5LPxMY0Tit5TrLcjk305sFpeF5HV8nr21fNrmU4RCfh8QZ//ydi7TDKlcTyDzkDNkcjkwp9LJybnvxyqbxCRM/HE8Kep2aWlWDjs82p+EtD88FtViezy+0WkM3WkZX/03LHjkVBNuqlpJDetcSqdgXLFYioam/g8Z/yZisbyxaLX42ncV9d2p19E2uOJTDKlN5DOU+zh0GD2wsXdgYCIhALBW+e77g8NnjjYOLW4YNxhfK7QFj+scULRu0FvZ3INNXteXL3+c3OzuS4iIgfCtbFw7ehMzrhDuVJZLpWaI/X5r0VdQ5q+wmz7vnreW10dr294X8hv0/F/M3XBmYPeSa+srf2DOmY5KJAzMRDAQAADAQwEMBDAQAADAQwEMBDAQAADAQwEMBDAQAADAQwEMBBgOpBd/4+ui9n5uUGASiD3LpHC5NwgQDGQG5dIbWb1DXJXI+VpLZ1ibmlkZU7++gtgTyCDozI56/eD/mN8mQcYCGAggIEABgIYCGAggIEABgIYCGAggIEABgIYCPgFnLG5xhv9EssAAAAASUVORK5CYII=","base64");
let browser;
async function state(page,name,value){await page.locator(`[data-case="${name}"] [data-media-thumbnail][data-state="${value}"]`).waitFor();}
async function reflow(page){assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.equal(await page.locator("html").getAttribute("dir"),"rtl");}
try {
 const {chromium}=await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
 browser=await chromium.launch({headless:true,args:["--no-sandbox"]});evidence.browser=browser.version();
 for(const mode of ["light","dark"]) {
  const context=await browser.newContext({colorScheme:mode,reducedMotion:"reduce",serviceWorkers:"block",viewport:{width:1280,height:1000}});
  await context.addInitScript(mode=>localStorage.setItem("theme",mode),mode);
  const requests=[];let releaseSlow,releaseNew;
  const slow=new Promise(resolve=>releaseSlow=resolve),replacement=new Promise(resolve=>releaseNew=resolve);
  await context.route("**/*",async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==base)return route.abort();
   if(!["GET","HEAD"].includes(request.method())){evidence.blocked_mutations++;return route.abort();}
   if(url.pathname.startsWith("/api/")) {
    const match=url.pathname.match(/^\/api\/admin\/preview\/product\/([1-6])$/);
    if(!match)return route.abort();
    const id=Number(match[1]);requests.push(id);
    if(id===1)await slow;if(id===5)await replacement;
    return route.fulfill({status:id===2?404:200,contentType:id===2?"text/plain":"image/png",body:id===2?"Not found":png});
   }
   return route.continue();
  });
  const page=await context.newPage();page.setDefaultNavigationTimeout(60000);
  page.on("pageerror",error=>evidence.errors.push(error.message));
  page.on("console",message=>{if(message.type()!=="error")return;const {url}=message.location();if(url===base+"/api/admin/preview/product/2"&&/404/.test(message.text()))return;evidence.errors.push(message.text());});
  await page.goto(base+"/lazy-media-ui-qa");
  await page.locator('button[aria-label="تغییر حالت روشن و تاریک"]:not([disabled])').waitFor();
  await page.waitForFunction(()=>document.querySelector('[data-case="slow"] img')?.classList.contains("lazyloading"));
  await state(page,"slow","loading");await state(page,"error","error");await state(page,"replace","loaded");
  assert.equal(requests.filter(id=>id===3).length,0,"offscreen image must remain deferred");
  assert.equal(await page.locator('[data-case="far"] img').getAttribute("src"),null);
  const before=await page.locator('[data-case="slow"] [data-media-thumbnail]').boundingBox();assert.equal(before.width,96);assert.equal(before.height,96);
  for(const width of [1440,1024,768,390,320]) {
   await page.setViewportSize({width,height:1000});await reflow(page);
   const name=`pending-error-${mode}-${width}.png`;await page.screenshot({path:output+"/"+name,caret:"initial"});evidence.screenshots.push(name);
   evidence.checks.push({check:"reserved skeleton, error copy and RTL",mode,width,status:"PASS"});save();
  }
  releaseSlow();await state(page,"slow","loaded");
  const after=await page.locator('[data-case="slow"] [data-media-thumbnail]').boundingBox();assert.equal(after.width,before.width);assert.equal(after.height,before.height);
  assert.equal(await page.locator('[data-case="slow"] img').evaluate(img=>img.naturalWidth),96);
  await page.getByRole("button",{name:"تعویض تصویر نمونه",exact:true}).click();await state(page,"replace","loading");
  releaseNew();await state(page,"replace","loaded");assert.equal(await page.locator('[data-case="replace"] img').getAttribute("src"),"/api/admin/preview/product/5");
  assert.equal(requests.filter(id=>id===3).length,0);
  await page.locator('[data-case="far"]').scrollIntoViewIfNeeded();await state(page,"far","loaded");assert.equal(requests.filter(id=>id===3).length,1);
  for(const id of [1,2,4,5])assert.equal(requests.filter(value=>value===id).length,1,`no duplicate image request ${id}`);
  await page.locator("h1").scrollIntoViewIfNeeded();await reflow(page);
  const loaded=`loaded-${mode}-320.png`;await page.screenshot({path:output+"/"+loaded,caret:"initial"});evidence.screenshots.push(loaded);
  evidence.checks.push({check:"load success, stable size, source replacement, offscreen deferral and one request per image",mode,status:"PASS"});save();
  await context.close();
 }
 // With JavaScript disabled, noscript still uses the same authenticated image route.
 const noJs=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:900}});
 await noJs.route("**/*",route=>{
  const url=new URL(route.request().url());if(url.origin!==base)return route.abort();
  if(url.pathname.startsWith("/api/"))return route.fulfill({status:200,contentType:"image/png",body:png});
  return route.continue();
 });
 const fallback=await noJs.newPage();await fallback.goto(base+"/lazy-media-ui-qa");
 await fallback.locator('[data-case="slow"] noscript img').waitFor();
 await fallback.waitForFunction(()=>{const img=document.querySelector('[data-case="slow"] noscript img');return img?.complete&&img.naturalWidth===96;});
 assert.equal(await fallback.locator('[data-case="slow"] noscript img').getAttribute("src"),"/api/admin/preview/product/1");
 evidence.checks.push({check:"no-JavaScript image fallback",status:"PASS"});await noJs.close();
 assert.equal(evidence.blocked_mutations,0);assert.deepEqual(evidence.errors,[]);evidence.status="PASS";save();
 console.log(`PASS lazy media: ${evidence.checks.length} checks, ${evidence.screenshots.length} captures, no mutations`);
} catch(error){evidence.status="FAIL";evidence.failure={name:error.name,message:String(error.message).slice(0,1200)};save();console.error(evidence.failure);process.exitCode=1;}
finally {
 try {if(browser)await browser.close();}
 finally {try{unlinkSync(dir+"/page.tsx");rmdirSync(dir);evidence.fixture_cleanup="PASS";}catch{evidence.fixture_cleanup="FAIL";evidence.status="FAIL";process.exitCode=1;}save();}
}
