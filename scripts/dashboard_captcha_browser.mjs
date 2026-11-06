/** Offline provider-UI acceptance; never solve a challenge or submit a login. */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const base="http://127.0.0.1:3005";
const provider=process.env.UI_CAPTCHA_PROVIDER;
assert(["turnstile","recaptcha_v2","unavailable"].includes(provider));
const env=Object.fromEntries(readFileSync(".codespaces/mcp-qa.env","utf8").trim().split("\n").map((line)=>[line.slice(0,line.indexOf("=")),line.slice(line.indexOf("=")+1)]));
assert.equal(env.SHOP_MCP_QA,"1");assert.equal(env.SHOP_BETA_QA,"1");
for(const key of ["TOKEN","BALE_BOT_TOKEN","BALE_WALLET_PROVIDER_TOKEN","TELEGRAM_FIAT_PROVIDER_TOKEN"])assert.equal(env[key],"");
const output=`/tmp/dashboard-captcha-${provider}`;mkdirSync(output,{recursive:true,mode:0o700});
const evidence={status:"RUNNING",provider,provider_sdk:"offline_stub",login_posts:0,checks:[],screenshots:[]};
const save=()=>writeFileSync(output+"/evidence.json",JSON.stringify(evidence,null,2),{mode:0o600});
const sdk=`(() => {
  let target;
  const api={ready:callback=>callback(),reset:()=>{},remove:()=>{target?.replaceChildren();},
    render:(element,options)=>{
      target=element;window.__qaCaptchaOptions=options;
      const box=document.createElement('div');box.dataset.captchaStub=options.size || 'normal';
      box.setAttribute('role','img');box.setAttribute('aria-label','Offline CAPTCHA layout fixture');
      const compact=options.size==='compact';
      box.style.cssText='box-sizing:border-box;border:1px solid currentColor;padding:12px;width:'+(compact?164:304)+'px;height:'+(compact?144:78)+'px';
      box.textContent='Offline CAPTCHA layout fixture';target.appendChild(box);return 'offline-widget';
    }};
  window.turnstile=api;window.grecaptcha=api;
})()`;
let browser;
try {
  const {chromium}=await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
  browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
  for(const mode of ["light","dark"]) {
    const context=await browser.newContext({colorScheme:mode,viewport:{width:320,height:900},serviceWorkers:"block",reducedMotion:"reduce"});
    await context.route("**/*",route=>{
      const url=new URL(route.request().url());
      if(url.origin===base) {
        if(url.pathname==="/api/auth/login"&&route.request().method()==="POST") {
          evidence.login_posts++;save();return route.abort();
        }
        return route.continue();
      }
      if(url.pathname.endsWith("/api.js")&&["challenges.cloudflare.com","www.google.com"].includes(url.hostname))return route.fulfill({status:200,contentType:"application/javascript",body:sdk});
      return route.abort();
    });
    const page=await context.newPage();const errors=[];
    page.on("pageerror",()=>errors.push("pageerror"));
    await page.goto(base+"/login",{waitUntil:"domcontentloaded"});
    await page.getByRole("heading",{name:"ورود به پنل مدیریت",exact:true}).waitFor();
    await page.getByRole("button",{name:"نمایش رمز عبور",exact:true}).click();
    assert.equal(await page.locator("#password").getAttribute("type"),"text");
    await page.getByRole("button",{name:"مخفی‌کردن رمز عبور",exact:true}).click();
    if(provider==="unavailable") {
      await page.getByRole("button",{name:"ادامه",exact:true}).waitFor();
      assert.equal(await page.getByRole("button",{name:"ادامه",exact:true}).isDisabled(),true);
      await page.locator("main").getByRole("alert").filter({hasText:"تنظیمات بررسی امنیتی ورود کامل نیست"}).waitFor();
    } else {
      await page.locator('[data-captcha-stub="compact"]').waitFor();
    }
    for(const width of [320,390,1280]) {
      await page.setViewportSize({width,height:900});
      const dimensions=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert(dimensions.scroll<=dimensions.width+1,JSON.stringify(dimensions));
      assert.equal(await page.locator("html").getAttribute("dir"),"rtl");
      const name=`${provider}-${mode}-${width}.png`;await page.screenshot({path:output+"/"+name,caret:"initial"});evidence.screenshots.push(name);
      evidence.checks.push({mode,width,status:"PASS"});save();
    }
    if(provider!=="unavailable") {
      await page.evaluate(()=>window.__qaCaptchaOptions["error-callback"]());
      await page.locator("main").getByRole("alert").filter({hasText:"بررسی امنیتی بارگذاری نشد"}).waitFor();
      evidence.checks.push({mode,check:"provider_error_feedback",status:"PASS"});
    }
    assert.deepEqual(errors,[]);await context.close();
  }
  assert.equal(evidence.login_posts,0);evidence.status="PASS";save();console.log(`PASS ${provider} offline widget UI: ${evidence.checks.length} checks, no login POST`);
} catch(error) {
  evidence.status="FAIL";evidence.failure={name:error.name,message:String(error.message).slice(0,600)};save();console.error(JSON.stringify(evidence.failure));process.exitCode=1;
} finally {if(browser)await browser.close();}
