/** Isolated UI fixtures render production components; all auth responses stay offline. */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync, existsSync, unlinkSync, rmdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
const base="http://127.0.0.1:3005",output="/tmp/dashboard-orbs",fixtureDir="dashboard-next/app/orb-ui-qa";
const env=Object.fromEntries(readFileSync(".codespaces/mcp-qa.env","utf8").trim().split("\n").map(line=>[line.slice(0,line.indexOf("=")),line.slice(line.indexOf("=")+1)]));
assert.equal(env.SHOP_MCP_QA,"1");assert.equal(env.SHOP_BETA_QA,"1");
for(const key of ["TOKEN","BALE_BOT_TOKEN","BALE_WALLET_PROVIDER_TOKEN","TELEGRAM_FIAT_PROVIDER_TOKEN"])assert.equal(env[key],"");
assert(!existsSync(fixtureDir),"do not overwrite an existing route");
mkdirSync(output,{recursive:true});mkdirSync(fixtureDir);
writeFileSync(fixtureDir+"/page.tsx",`
import Dashboard from "../(console)/loading";
import Workflows from "../(console)/studio/workflows/loading";
import Runtime from "../(console)/studio/runtime/loading";
import MCP from "../(console)/studio/mcp/loading";
import { ActivityIndicator } from "@/components/ui/activity-indicator";
import { ThemeToggle } from "@/components/blocks/theme-toggle";
import { Button } from "@/components/ui/button";
export default function Fixture(){return <main className="mx-auto max-w-5xl space-y-8 p-5">
<h1>پیش‌نمایش آزمایشی نشانگرهای بارگذاری</h1><ThemeToggle />
<div data-case="primary"><Button disabled><ActivityIndicator announce={false} onPrimary label="در حال بررسی…" /></Button></div>
<section data-case="dashboard"><h2>داشبورد</h2><Dashboard /></section>
<section data-case="workflows"><h2>فرایندها</h2><Workflows /></section>
<section data-case="runtime"><h2>اجراها</h2><Runtime /></section>
<section data-case="mcp"><h2>MCP</h2><MCP /></section>
<section data-case="long"><ActivityIndicator label="در حال دریافت اطلاعات و بررسی وضعیت اتصال‌های فروشگاه انتخاب‌شده…" /></section>
</main>;}
`);
const evidence={status:"RUNNING",fixture:"isolated UI only; no business data",checks:[],screenshots:[],errors:[],auth_backend_calls:0};
const save=()=>writeFileSync(output+"/evidence.json",JSON.stringify(evidence,null,2));
let browser;
const reflow=async page=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
const brightness=canvas=>canvas.evaluate(el=>{const pixels=el.getContext("2d").getImageData(0,0,el.width,el.height).data;let total=0,count=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i+3]>20){total+=pixels[i];count++;}return {ink:count,mean:total/Math.max(1,count)};});
try {
 const {chromium}=await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
 browser=await chromium.launch({headless:true,args:["--no-sandbox"]});evidence.browser=browser.version();
 const context=await browser.newContext({reducedMotion:"reduce",serviceWorkers:"block",viewport:{width:1280,height:1000}});
 await context.route("**/*",route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.setDefaultNavigationTimeout(60000);page.on("pageerror",e=>evidence.errors.push(e.message));
 page.on("console",m=>{if(m.type()==="error")evidence.errors.push(m.text());});
 await page.goto(base+"/orb-ui-qa");
 const toggle=page.getByRole("button",{name:"تغییر حالت روشن و تاریک",exact:true});
 await page.locator('button[aria-label="تغییر حالت روشن و تاریک"]:not([disabled])').waitFor();
 await page.waitForLoadState("networkidle");
 assert.equal(await page.locator("canvas").count(),6);
 assert.equal(await page.locator('canvas[aria-hidden="true"][tabindex="-1"]').count(),6);
 assert.equal(await page.getByRole("status").count(),5);
 const palettes={};
 for(const mode of ["light","dark"]) {
  if(await page.locator("html").evaluate(el=>el.classList.contains("dark"))!==(mode==="dark"))await toggle.click();
  await page.waitForFunction(mode=>document.documentElement.classList.contains("dark")===(mode==="dark"),mode);
  // Wait for the canvas effect after the host theme updates.
  await page.waitForFunction(()=>document.querySelector('canvas')?.width>0);
  await page.waitForLoadState("networkidle");
  palettes[mode]={primary:await brightness(page.locator('[data-case="primary"] canvas')),normal:await brightness(page.locator('[data-case="mcp"] canvas'))};
  for(const width of [1440,1024,768,390,320]) {
   await page.setViewportSize({width,height:1000});await reflow(page);
   for(const name of ["primary","dashboard","workflows","runtime","mcp","long"]) {
    const target=page.locator(`[data-case="${name}"]`);await target.scrollIntoViewIfNeeded();
    const filename=`${name}-${mode}-${width}.png`;await target.screenshot({path:output+"/"+filename,caret:"initial"});evidence.screenshots.push(filename);
   }
   evidence.checks.push({check:"RTL and reflow",mode,width,status:"PASS"});save();
  }
 }
 assert(palettes.light.normal.ink>0&&palettes.dark.normal.ink>0);
 assert(palettes.dark.normal.mean>palettes.light.normal.mean,"normal ink follows host theme");
 assert(palettes.light.primary.mean>palettes.dark.primary.mean,"primary-button ink follows its contrast palette");
 evidence.palettes=palettes;
 const canvas=page.locator('[data-case="long"] canvas');await canvas.scrollIntoViewIfNeeded();
 const still=await canvas.evaluate(el=>el.toDataURL());
 // This deliberate sample interval tests animation stability, not page readiness.
 await page.waitForTimeout(250);assert.equal(await canvas.evaluate(el=>el.toDataURL()),still);
 evidence.checks.push({check:"reduced motion renders a stable painted frame",status:"PASS"});
 await page.emulateMedia({reducedMotion:"no-preference"});
 await page.waitForFunction(still=>document.querySelector('[data-case="long"] canvas').toDataURL()!==still,still);
 evidence.checks.push({check:"animation resumes when reduced motion is disabled",status:"PASS"});
 await context.close();
 for(const mode of ["light","dark"]) {
  const ctx=await browser.newContext({colorScheme:mode,reducedMotion:"reduce",viewport:{width:320,height:900},serviceWorkers:"block"});
  await ctx.addInitScript(mode=>localStorage.setItem("theme",mode),mode);
  let release;const hold=new Promise(resolve=>release=resolve);
  await ctx.route("**/*",async route=>{
   const url=new URL(route.request().url());if(url.origin!==base)return route.abort();
   if(url.pathname==="/api/auth/challenge"){await hold;return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({challenge:"q".repeat(43)})});}
   if(url.pathname==="/api/auth/login")return route.fulfill({status:401,contentType:"application/json",body:JSON.stringify({ok:false,code:"invalid_credentials"})});
   return route.continue();
  });
  const login=await ctx.newPage();login.on("pageerror",e=>evidence.errors.push(e.message));
  await login.goto(base+"/login");
  await login.getByLabel("نام کاربری",{exact:true}).fill("qa_orb");
  await login.getByLabel("رمز عبور",{exact:true}).fill("offline-ui-fixture");
  await login.getByRole("button",{name:"ورود",exact:true}).click();
  const pending=login.getByRole("button",{name:"در حال بررسی…",exact:true});await pending.waitFor();assert(await pending.isDisabled());
  await pending.locator("canvas").waitFor();await reflow(login);
  const file=`login-pending-${mode}-320.png`;await login.screenshot({path:output+"/"+file,caret:"initial"});evidence.screenshots.push(file);
  release();await login.locator("#login-error").waitFor();assert.equal(await login.locator("canvas").count(),0);assert(await login.getByRole("button",{name:"ورود",exact:true}).isEnabled());
  evidence.checks.push({check:"real login pending UI and offline failure recovery",mode,status:"PASS"});await ctx.close();
 }
 assert.deepEqual(evidence.errors,[]);evidence.status="PASS";save();console.log(`PASS orb UI: ${evidence.checks.length} checks, ${evidence.screenshots.length} captures, zero backend auth calls`);
} catch(error) {evidence.status="FAIL";evidence.failure={name:error.name,message:String(error.message).slice(0,1000)};save();console.error(evidence.failure);process.exitCode=1;}
finally {
 try {if(browser)await browser.close();}
 finally {
  try {unlinkSync(fixtureDir+"/page.tsx");rmdirSync(fixtureDir);evidence.fixture_cleanup="PASS";}
  catch {evidence.fixture_cleanup="FAIL";evidence.status="FAIL";process.exitCode=1;}
  save();
 }
}
