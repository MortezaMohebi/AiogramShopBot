/** Exercise the real login page with intercepted synthetic auth responses only. */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const base="http://127.0.0.1:3005", output="/tmp/dashboard-login-steps";
const env=Object.fromEntries(readFileSync(".codespaces/mcp-qa.env","utf8").trim().split("\n").map(line=>{const i=line.indexOf("=");return [line.slice(0,i),line.slice(i+1)];}));
assert.equal(env.SHOP_MCP_QA,"1");assert.equal(env.SHOP_BETA_QA,"1");
for(const key of ["TOKEN","BALE_BOT_TOKEN","BALE_WALLET_PROVIDER_TOKEN","TELEGRAM_FIAT_PROVIDER_TOKEN"])assert.equal(env[key],"");
mkdirSync(output,{recursive:true});
const evidence={status:"RUNNING",scope:"production LoginForm; fake CSRF/auth replies; no real account proof or session",checks:[],screenshots:[],errors:[],real_mutations:0};
const save=()=>writeFileSync(output+"/evidence.json",JSON.stringify(evidence,null,2));
const check=(name,theme)=>{evidence.checks.push({name,theme,status:"PASS"});save();};
async function capture(page,name){await page.screenshot({path:`${output}/${name}.png`,caret:"initial"});evidence.screenshots.push(name+".png");save();}
async function credentials(page){await page.getByLabel("نام کاربری",{exact:true}).fill("qa.synthetic");await page.getByLabel("رمز عبور",{exact:true}).fill("SYNTHETIC-ONLY-password-123");await page.getByRole("button",{name:"ادامه",exact:true}).click();}
let browser;
try {
 const {chromium}=await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
 browser=await chromium.launch({headless:true,args:["--no-sandbox"]});evidence.browser=browser.version();
 for(const theme of ["light","dark"]) {
  const context=await browser.newContext({viewport:{width:390,height:900},colorScheme:theme,reducedMotion:"reduce",serviceWorkers:"block"});
  await context.addInitScript(value=>localStorage.setItem("theme",value),theme);
  let behavior="bad-password", calls=0, lastFactor="";
  await context.route("**/*",async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==base)return route.abort();
   if(url.pathname==="/api/auth/challenge")return route.fulfill({contentType:"application/json",body:JSON.stringify({ok:true,challenge:"C".repeat(43)})});
   if(url.pathname==="/api/auth/login") {
    assert.equal(request.method(),"POST");const body=request.postDataJSON();calls++;
    assert.equal(body.username,"qa.synthetic");assert.equal(body.password,"SYNTHETIC-ONLY-password-123");
    assert.equal(request.headers()["x-shop-login-challenge"],"C".repeat(43));lastFactor=body.second_factor;
    let status=428,reply={ok:false,code:"mfa_required"};
    if(behavior==="bad-password"){status=401;reply={ok:false,code:"invalid_credentials"};}
    else if(body.second_factor&&behavior==="bad-code"){status=401;reply={ok:false,code:"invalid_verification"};}
    else if(body.second_factor&&behavior==="malformed"){status=200;reply={ok:true,redirect:"https://outside.invalid"};}
    else if((body.second_factor&&behavior==="accept")||behavior==="no-mfa"){status=200;reply={ok:true,redirect:"/dashboard"};}
    return route.fulfill({status,contentType:"application/json",body:JSON.stringify(reply)});
   }
   if(url.pathname==="/dashboard")return route.fulfill({contentType:"text/html",body:'<h1>نتیجهٔ آزمایشی ورود</h1>'});
   if(!["GET","HEAD"].includes(request.method())){evidence.real_mutations++;return route.abort();}
   if(url.pathname.startsWith("/api/"))return route.abort();
   return route.continue();
  });
  const page=await context.newPage();page.setDefaultNavigationTimeout(60000);
  await page.clock.install();
  page.on("pageerror",error=>evidence.errors.push(error.message));
  await page.goto(base+"/login");
  // Password reveal proves the production client handlers have hydrated.
  await page.getByRole("button",{name:"نمایش رمز عبور",exact:true}).click();
  assert.equal(await page.getByLabel("رمز عبور",{exact:true}).getAttribute("type"),"text");
  await page.getByRole("button",{name:"مخفی‌کردن رمز عبور",exact:true}).click();
  assert.equal(await page.locator('[name="second_factor"]').count(),0);
  for(const width of [1440,1024,768,390,320]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await capture(page,`credentials-${theme}-${width}`);}
  await credentials(page);await page.locator("form").getByRole("alert").waitFor();
  assert.equal(await page.locator('[name="second_factor"]').count(),0);assert.equal(await page.getByLabel("رمز عبور",{exact:true}).inputValue(),"");
  check("no MFA on first screen; wrong password cannot advance",theme);
  behavior="password-ok";await credentials(page);await page.getByRole("heading",{name:"تأیید دومرحله‌ای",exact:true}).waitFor();
  assert.equal(lastFactor,"");assert.equal(await page.locator('[name="password"], [name="username"]').count(),0);
  await page.waitForFunction(()=>document.activeElement?.getAttribute("name")==="second_factor");
  for(const width of [1440,1024,768,390,320]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await capture(page,`mfa-${theme}-${width}`);}
  check("verified password opens a separate focused MFA screen; no password field",theme);
  behavior="bad-code";await page.getByLabel("کد تأیید",{exact:true}).fill("۱۲۳ ۴۵۶");await page.getByRole("button",{name:"ورود",exact:true}).click();
  await page.getByText("کد تأیید پذیرفته نشد",{exact:true}).waitFor();assert.equal(lastFactor,"123456");
  await capture(page,`mfa-error-${theme}`);check("localized copied OTP normalizes; rejection stays on MFA",theme);
  await page.getByRole("button",{name:"استفاده از کد بازیابی",exact:true}).click();assert.equal(await page.getByLabel("کد بازیابی",{exact:true}).getAttribute("inputmode"),"text");
  behavior="accept";const recovery="a1".repeat(16);await page.getByLabel("کد بازیابی",{exact:true}).fill(recovery);await page.getByRole("button",{name:"ورود",exact:true}).click();
  await page.getByRole("heading",{name:"نتیجهٔ آزمایشی ورود",exact:true}).waitFor();assert.equal(lastFactor,recovery);check("unchanged recovery code reaches the verified redirect",theme);
  behavior="password-ok";await page.goto(base+"/login");await credentials(page);await page.getByLabel("کد تأیید",{exact:true}).waitFor();
  await page.getByRole("button",{name:"بازگشت به ورود",exact:true}).click();await page.getByLabel("رمز عبور",{exact:true}).waitFor();assert.equal(await page.getByLabel("رمز عبور",{exact:true}).inputValue(),"");
  await credentials(page);await page.getByLabel("کد تأیید",{exact:true}).waitFor();
  behavior="malformed";await page.getByLabel("کد تأیید",{exact:true}).fill("123456");await page.getByRole("button",{name:"ورود",exact:true}).click();await page.getByText("سرویس ورود در دسترس نیست",{exact:true}).waitFor();assert(new URL(page.url()).pathname==="/login");
  check("Back clears password; malformed success cannot redirect",theme);
  await page.clock.fastForward(5*60*1000+1);await page.getByText("زمان ورود پایان یافت",{exact:true}).waitFor();assert.equal(await page.getByLabel("رمز عبور",{exact:true}).inputValue(),"");
  check("five-minute MFA wait expires and clears pending credentials",theme);
  behavior="no-mfa";await credentials(page);await page.getByRole("heading",{name:"نتیجهٔ آزمایشی ورود",exact:true}).waitFor();check("account without MFA goes directly to the permitted destination",theme);
  evidence.fake_auth_requests=(evidence.fake_auth_requests??0)+calls;await context.close();
 }
 assert.equal(evidence.real_mutations,0);assert.deepEqual(evidence.errors,[]);evidence.status="PASS";save();console.log(`PASS login steps: ${evidence.checks.length} checks; ${evidence.screenshots.length} captures; zero real auth writes`);
} catch(error){evidence.status="FAIL";evidence.failure={name:error.name,message:String(error.message).slice(0,1500)};save();console.error(evidence.failure);process.exitCode=1;}
finally {if(browser)await browser.close();evidence.browser_cleanup="PASS";save();}
