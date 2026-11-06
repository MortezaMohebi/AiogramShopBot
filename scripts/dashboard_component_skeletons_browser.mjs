/** Read-only browser acceptance for production section views and deferred Studio forms. */
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const base = "http://127.0.0.1:3005";
const output = "/tmp/dashboard-component-skeletons";
const directory = "dashboard-next/app/component-ui-qa";
const env = Object.fromEntries(readFileSync(process.env.COMPONENT_UI_QA_ENV ?? ".codespaces/mcp-qa.env", "utf8").trim().split("\n").map(line => {
  const equal = line.indexOf("=");
  return [line.slice(0, equal), line.slice(equal + 1)];
}));
assert.equal(env.SHOP_MCP_QA, "1");
assert.equal(env.SHOP_BETA_QA, "1");
for (const key of ["TOKEN", "BALE_BOT_TOKEN", "BALE_WALLET_PROVIDER_TOKEN", "TELEGRAM_FIAT_PROVIDER_TOKEN"]) assert.equal(env[key], "");

// Temporary routes live outside the protected console. They use synthetic data,
// never bypass authentication, and are deleted after the owned browser closes.
const studio = `"use client";
import { useState } from "react";
import { WorkflowEditor } from "@/components/workflows/editor";
import { Button } from "@/components/ui/button";
import type { WorkflowRecord, Catalog } from "@/lib/workflows/types";
const initial: WorkflowRecord = {
 id:"qa-read-only",store_id:"qa-store",key:"qa",status:"draft",revision:1,head_revision:1,can_write:false,
 name:"فرایند نمونهٔ آزمایشی",description:"فقط مشاهده",
 definition:{schema_version:1,target_platforms:["telegram","bale"],assignment:{mode:"all_eligible",bot_ids:[]},
 entry_points:[{kind:"start",key:"main",node_id:"start",command:""}],
 nodes:[{id:"start",type:"start",label:"شروع نمونه",config:{},platform_overrides:{},max_visits:null},
 {id:"end",type:"end",label:"پایان نمونه",config:{},platform_overrides:{},max_visits:null}],
 edges:[],variables:[],error_policy:{max_steps:100,on_error:"stop",message:"خطا"},timeout_policy:{seconds:300,outcome:"cancel"}},
 layout:{positions:{},viewport:{x:0,y:0,zoom:1}},
 validation:{valid:true,can_simulate:true,activation_available:false,issues:[]},runtime_available:false
};
const catalog:Catalog={nodes:["start","end"].map(type=>({type,label:type,group:"basic",ports:[],defaults:{},fields:[],
 action_contract:{key:"",service:null,available:false,execution_available:false,simulation_only:true}})),
 platforms:{telegram:{},bale:{}},can_write:false,store_id:"qa-store",runtime_available:false,
 limits:{nodes:100,edges:200,variables:50,request_bytes:100000}};
export function StudioFixture(){const [settings,setSettings]=useState(false);return <>
 <Button onClick={()=>setSettings(value=>!value)}>تنظیمات نمونه</Button>
 <WorkflowEditor initial={initial} catalog={catalog} settings={settings}/></>;}
`;
const fixture = `import { Suspense } from "react";
import { ProductsTable } from "@/components/data/products";
import { OrdersList, ReviewQueueView } from "@/components/data/orders";
import { OverviewView } from "@/components/data/overview";
import { TableSkeleton, FormSkeleton, OverviewSkeleton } from "@/components/data/skeletons";
import { DataSectionError } from "@/components/data/section-error";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { StudioFixture } from "./studio";
const order={id:77,platform:"bale",name:"سفارش نمونهٔ آزمایشی",status:"paid",total_irr:"1000",payment_currency:"IRR",payment_amount:"1000",created_at:"2026-11-06T00:00:00Z"};
const orders={items:[order],total:1,page:1,page_size:20};
const products={items:[{id:8,name:"محصول نمونهٔ آزمایشی",sku:"QA-8",external_ref:null,store_id:"qa-store",uom_id:"unit",purchase_uom_id:null,category_id:null,description:"",price_stars:null,digital_delivery_mode:"none",requires_shipping:true,product_type:"physical",position:0,price_irr:"1000",stock_quantity:3,is_published:false}],total:1,page:1,page_size:20};
const overview={products:1,published_products:0,open_refunds:0,channels:[],recent_orders:[order],campaigns:{queued:0,unknown:0}};
async function Delayed({children,ms}:{children:React.ReactNode;ms:number}){await new Promise(resolve=>setTimeout(resolve,ms));return children;}
export default async function Fixture({searchParams}:{searchParams:Promise<Record<string,string>>}){
 const {mode="stream"}=await searchParams, geometry=mode==="geometry", loaded=mode==="loaded";
 return <main className="mx-auto min-w-0 max-w-7xl space-y-8 p-4 sm:p-6">
 <p className="text-sm text-muted-foreground">پیش‌نمایش آزمایشی · دادهٔ ساختگی · بدون ثبت تغییر</p>
 <h1 className="text-2xl font-bold">بارگذاری بخش‌های داشبورد</h1>
 {mode==="studio"?<StudioFixture/>:<>
 <section data-case="products" className="min-w-0 space-y-4"><h2 className="text-xl font-bold">محصولات</h2>
 <Card><CardContent className="space-y-5 pt-5"><form className="flex flex-wrap gap-3" method="get"><input type="hidden" name="mode" value="geometry"/>
 <Input name="search" aria-label="جستجو در محصول و SKU" defaultValue="فیلتر روغن" className="max-w-sm"/>
 <Button type="submit">جستجو</Button></form>
 {geometry?<TableSkeleton label="در حال دریافت محصولات…"/>:loaded?<ProductsTable data={products} page={1} search="فیلتر روغن" canEdit={false}/>:
 <Suspense fallback={<TableSkeleton label="در حال دریافت محصولات…"/>}><Delayed ms={5000}><ProductsTable data={products} page={1} search="فیلتر روغن" canEdit={false}/></Delayed></Suspense>}
 </CardContent></Card></section>
 <section data-case="queue" className="min-w-0">{mode==="error"?<DataSectionError title="درخواست‌ها دریافت نشدند"/>:geometry?<FormSkeleton label="در حال دریافت درخواست‌ها…"/>:loaded?<ReviewQueueView queue={[]}/>:
 <Suspense fallback={<FormSkeleton label="در حال دریافت درخواست‌ها…"/>}><Delayed ms={8000}><ReviewQueueView queue={[]}/></Delayed></Suspense>}</section>
 <section data-case="orders" className="min-w-0">{geometry?<TableSkeleton label="در حال دریافت سفارش‌ها…"/>:loaded||mode==="error"?<OrdersList data={orders} page={1}/>:
 <Suspense fallback={<TableSkeleton label="در حال دریافت سفارش‌ها…"/>}><Delayed ms={300}><OrdersList data={orders} page={1}/></Delayed></Suspense>}</section>
 <section data-case="overview" className="min-w-0">{geometry?<OverviewSkeleton/>:loaded?<OverviewView overview={overview}/>:
 <Suspense fallback={<OverviewSkeleton/>}><Delayed ms={5000}><OverviewView overview={overview}/></Delayed></Suspense>}</section>
 </>}
 </main>;
}
`;
const ownedFiles = { "page.tsx": fixture, "studio.tsx": studio };
if (process.argv.includes("--prepare")) {
  assert(!existsSync(directory), "refuse to overwrite an existing route");
  mkdirSync(directory);
  for (const [name, source] of Object.entries(ownedFiles)) writeFileSync(`${directory}/${name}`, source);
  console.log("Read-only component fixtures prepared before Next startup");
  process.exit(0);
}
for (const [name, source] of Object.entries(ownedFiles)) assert.equal(readFileSync(`${directory}/${name}`, "utf8"), source);
mkdirSync(output, { recursive: true });
const evidence = { status: "RUNNING", fixture: "production views + skeletons; synthetic read-only data; controlled server latency and module delivery", checks: [], screenshots: [], errors: [], blocked_mutations: 0 };
const save = () => writeFileSync(output + "/evidence.json", JSON.stringify(evidence, null, 2));
const check = (name, extra = {}) => { evidence.checks.push({ check: name, status: "PASS", ...extra }); save(); };
async function capture(page, name) {
  await page.screenshot({ path: `${output}/${name}.png`, fullPage: true, caret: "initial" });
  evidence.screenshots.push(name + ".png"); save();
}
async function reflow(page) {
  assert.equal(await page.locator("html").getAttribute("dir"), "rtl");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "no page-wide horizontal overflow");
}
let browser;
try {
  const { chromium } = await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ headless: true, executablePath: process.env.COMPONENT_UI_CHROME, args: ["--no-sandbox"] });
  evidence.browser = browser.version();
  for (const theme of ["light", "dark"]) {
    const context = await browser.newContext({ colorScheme: theme, reducedMotion: "reduce", viewport: { width: 390, height: 900 }, serviceWorkers: "block" });
    await context.addInitScript(value => localStorage.setItem("theme", value), theme);
    await context.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== base) return route.abort();
      if (!["GET", "HEAD"].includes(request.method())) { evidence.blocked_mutations++; return route.abort(); }
      if (url.pathname.startsWith("/api/")) return route.abort();
      return route.continue();
    });
    const page = await context.newPage();
    page.setDefaultNavigationTimeout(60000);
    page.on("pageerror", error => evidence.errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") evidence.errors.push(message.text()); });
    // One real stream proves partial completion; the stable geometry route lets
    // all viewport/theme combinations inspect exactly the same pending state.
    await page.goto(base + "/component-ui-qa?mode=stream", { waitUntil: "commit" });
    await page.getByText("سفارش نمونهٔ آزمایشی", { exact: true }).waitFor();
    assert(await page.getByRole("status", { name: "در حال دریافت درخواست‌ها…", exact: true }).isVisible());
    assert(await page.getByRole("status", { name: "در حال دریافت محصولات…", exact: true }).isVisible());
    assert.equal(await page.getByLabel("جستجو در محصول و SKU").inputValue(), "فیلتر روغن");
    assert.equal(await page.getByLabel("جستجو در محصول و SKU").isEnabled(), true);
    await capture(page, `partial-${theme}`);
    await page.getByText("محصول نمونهٔ آزمایشی", { exact: true }).waitFor();
    await page.getByText("سفارشی برای بررسی دستی موجود نیست.", { exact: true }).waitFor();
    assert.equal(await page.getByRole("status").count(), 0);
    check("independent streaming, interactive search, confirmed empty queue", { theme });
    for (const mode of ["geometry", "loaded"]) {
      await page.goto(`${base}/component-ui-qa?mode=${mode}`);
      await page.waitForFunction(() => document.documentElement.classList.contains(localStorage.getItem("theme")));
      for (const width of [1440, 1024, 768, 390, 320]) {
        await page.setViewportSize({ width, height: 900 });
        await reflow(page);
        if (mode === "geometry") {
          assert.equal(await page.getByRole("status").count(), 4);
          assert.equal(await page.getByText("محصولات تعریف‌شده", { exact: true }).count(), 0);
          assert.equal(await page.getByText("سفارشی برای بررسی دستی موجود نیست.", { exact: true }).count(), 0);
          const motion = await page.locator(".animate-pulse").first().evaluate(element => getComputedStyle(element).animationDuration);
          assert(parseFloat(motion) <= 0.01, "reduced-motion pulse is disabled");
        }
        await capture(page, `${mode}-${theme}-${width}`);
        check("RTL, theme, reflow and truthful state", { theme, mode, width });
      }
    }
    // Retry refreshes the read-only RSC route; it must never submit a review.
    await page.goto(base + "/component-ui-qa?mode=error");
    await page.getByRole("alert").waitFor();
    assert(await page.getByText("سفارش نمونهٔ آزمایشی", { exact: true }).isVisible());
    let refreshReads = 0;
    const countRefresh = request => { if (request.method() === "GET" && request.url().includes("mode=error") && request.headers()["rsc"] === "1") refreshReads++; };
    page.on("request", countRefresh);
    const refreshResponse = page.waitForResponse(response => response.request().method() === "GET" && response.request().headers()["rsc"] === "1");
    await page.getByRole("button", { name: "دریافت دوباره", exact: true }).click();
    await refreshResponse;
    page.off("request", countRefresh);
    assert.equal(refreshReads, 1);
    await capture(page, `section-error-${theme}`);
    check("local error retains sibling data; retry performs one GET refresh", { theme });
    await context.close();

    // Hold actual lazy chunks, then change selection before they resolve.
    const lazy = await browser.newContext({ colorScheme: theme, viewport: { width: 390, height: 900 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await lazy.addInitScript(value => localStorage.setItem("theme", value), theme);
    const held = {}; const seen = [];
    let releaseInspector, releaseSettings;
    const inspectorGate = new Promise(resolve => releaseInspector = resolve);
    const settingsGate = new Promise(resolve => releaseSettings = resolve);
    await lazy.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== base) return route.abort();
      if (!["GET", "HEAD"].includes(request.method())) { evidence.blocked_mutations++; return route.abort(); }
      if (url.pathname.startsWith("/api/")) return route.abort();
      if (url.pathname.endsWith(".js")) {
        const response = await route.fetch();
        const body = await response.text();
        if (/function Inspector\(/.test(body)) { seen.push("inspector"); held.inspector = true; await inspectorGate; }
        if (/function WorkflowSettings\(/.test(body)) { seen.push("settings"); held.settings = true; await settingsGate; }
        return route.fulfill({ response, body });
      }
      return route.continue();
    });
    const editor = await lazy.newPage(); editor.setDefaultNavigationTimeout(60000);
    editor.on("pageerror", error => evidence.errors.push(error.message));
    editor.on("console", message => { if (message.type() === "error") evidence.errors.push(message.text()); });
    try {
      await editor.goto(base + "/component-ui-qa?mode=studio");
      await editor.getByRole("button", { name: "1. شروع نمونه 0 خروجی", exact: true }).waitFor();
      assert.deepEqual(seen, [], "optional forms are not requested on initial editor load");
      await editor.getByRole("button", { name: "1. شروع نمونه 0 خروجی", exact: true }).click();
      await editor.getByRole("status", { name: "در حال دریافت ویژگی‌های مرحله…", exact: true }).waitFor();
      assert.equal(held.inspector, true);
      await editor.getByRole("button", { name: "2. پایان نمونه 0 خروجی", exact: true }).click();
      await capture(editor, `inspector-pending-${theme}`);
      releaseInspector();
      await editor.getByRole("status", { name: "در حال دریافت ویژگی‌های مرحله…", exact: true }).waitFor({ state: "detached" });
      assert.equal(await editor.getByLabel("عنوان گره", { exact: true }).inputValue(), "پایان نمونه");
      assert.equal(await editor.getByLabel("عنوان گره", { exact: true }).isEnabled(), false);
      await editor.getByRole("button", { name: "تنظیمات نمونه", exact: true }).click();
      await editor.getByRole("status", { name: "در حال دریافت تنظیمات فرایند…", exact: true }).waitFor();
      assert.equal(held.settings, true);
      await capture(editor, `settings-pending-${theme}`);
      releaseSettings();
      await editor.getByRole("status", { name: "در حال دریافت تنظیمات فرایند…", exact: true }).waitFor({ state: "detached" });
      await editor.getByRole("button", { name: "تنظیمات نمونه", exact: true }).click();
      assert.equal(await editor.getByLabel("عنوان گره", { exact: true }).inputValue(), "پایان نمونه");
      assert.equal(await editor.getByRole("button", { name: "ذخیره", exact: true }).isEnabled(), false);
      await reflow(editor); await capture(editor, `inspector-loaded-${theme}`);
      assert.equal(seen.filter(name => name === "inspector").length, 1);
      assert.equal(seen.filter(name => name === "settings").length, 1);
      check("on-demand forms, matching fallbacks, latest selection, preserved parent state and readonly save", { theme });
    } finally { releaseInspector(); releaseSettings(); await lazy.close(); }
  }
  assert.equal(evidence.blocked_mutations, 0);
  assert.deepEqual(evidence.errors, []);
  evidence.status = "PASS"; save();
  console.log(`PASS component skeletons: ${evidence.checks.length} checks, ${evidence.screenshots.length} captures, no mutations`);
} catch (error) {
  evidence.status = "FAIL";
  evidence.failure = { name: error.name, message: String(error.message).slice(0, 1200) };
  save(); console.error(evidence.failure); process.exitCode = 1;
} finally {
  try { if (browser) await browser.close(); }
  finally {
    for (const [name, source] of Object.entries(ownedFiles)) assert.equal(readFileSync(`${directory}/${name}`, "utf8"), source);
    rmSync(directory, { recursive: true });
    evidence.fixture_cleanup = "PASS"; save();
  }
}
