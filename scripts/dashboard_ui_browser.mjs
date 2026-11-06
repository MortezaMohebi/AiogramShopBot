/** Dashboard acceptance against the dedicated PostgreSQL lab and fake providers. */
import assert from "node:assert/strict";
import { execFile, execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const base = "http://127.0.0.1:3005";
const compose = "compose.workflow-mcp-qa.yml";
const output = process.env.DASHBOARD_UI_ARTIFACTS || "/tmp/dashboard-ui-browser";
const env = Object.fromEntries(readFileSync(".codespaces/mcp-qa.env", "utf8").trim().split("\n")
  .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]));
assert.equal(env.SHOP_MCP_QA, "1");assert.equal(env.SHOP_BETA_QA, "1");
assert.equal(env.SHOP_FASTAPI_INTERNAL_URL, "http://127.0.0.1:8095");
for (const key of ["TOKEN", "BALE_BOT_TOKEN", "BALE_WALLET_PROVIDER_TOKEN", "TELEGRAM_FIAT_PROVIDER_TOKEN"])
  if (env[key] !== "") throw Error("live_provider_credentials_not_allowed");
mkdirSync(output, { recursive: true, mode: 0o700 });
const evidence = { status: "RUNNING", origin: base, checks: [], screenshots: [], mutation_posts: 0, routes: [] };
const persist = () => writeFileSync(output + "/evidence.json", JSON.stringify(evidence, null, 2), { mode: 0o600 });

/** Guard Docker operations before imports and suppress raw secret diagnostics. */
function docker(code, data = {}) {
  const prelude = `import os,sys,json,asyncio
from scripts.test_lab_safety import require_isolated_lab
require_isolated_lab()
assert os.environ.get("SHOP_MCP_QA")=="1" and __debug__
data=json.loads(sys.stdin.read())
`;
  try {
    return execFileSync("docker", ["compose", "-f", compose, "exec", "-T", "api", "python", "-c", prelude + code], {
      input: JSON.stringify(data), encoding: "utf8", timeout: 45000, stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch { throw new Error("guarded_lab_operation_failed"); }
}
/** Keep Playwright request interception responsive while preparing synthetic MFA. */
function dockerAsync(code, data = {}) {
  const prelude = `import os,sys,json,asyncio
from scripts.test_lab_safety import require_isolated_lab
require_isolated_lab()
assert os.environ.get("SHOP_MCP_QA")=="1" and __debug__
data=json.loads(sys.stdin.read())
`;
  return new Promise((resolve, reject) => {
    const child = execFile("docker", ["compose", "-f", compose, "exec", "-T", "api", "python", "-c", prelude + code], {
      encoding:"utf8",timeout:45000,maxBuffer:65536,
    }, (error, stdout) => {
      if(error) reject(new Error("guarded_lab_operation_failed"));
      else resolve(stdout.trim());
    });
    child.stdin.end(JSON.stringify(data));
  });
}
async function check(name, run) {
  try { await run();evidence.checks.push({ name, status: "PASS" });console.log("PASS  " + name); }
  catch (error) { evidence.checks.push({ name, status: "FAIL", reason: error.name });throw error; }
  finally { persist(); }
}

/** Only the unused current synthetic authenticator proof leaves the lab process. */
async function freshOtp() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const value = JSON.parse(await dockerAsync(`import time
from db import session_maker,engine
from models.shop_admin_control import AdminProfile
from services import shop_admin_security as security
async def main():
 async with session_maker() as db:
  row=await db.get(AdminProfile,data["admin_id"])
  now=time.time()
  if int(now//30)<=row.last_totp_step:
   print(json.dumps({"wait":int((30-now%30)*1000)+150}))
  else:
   secret=security.cipher().decrypt(row.mfa_secret.encode()).decode()
   print(json.dumps({"proof":security.totp(secret,now)}))
 await engine.dispose()
asyncio.run(main())`, fixture));
    if (value.proof) return value.proof;
    await new Promise((resolve) => setTimeout(resolve, value.wait));
  }
  throw new Error("fresh_mfa_unavailable");
}


let browser, context, page, roleFixtures;
const errors = [];
const expected404 = new Set();
evidence.expected_console_errors=[];
evidence.network = [];
const fixture = JSON.parse(docker('from pathlib import Path\nprint(Path("/qa/workflow-mcp-fixture.json").read_text())'));
const sizes = [1440, 1024, 768, 390, 320];
const theme = async (value) => {
  await page.emulateMedia({colorScheme:value});
  await page.evaluate((theme) => {
    localStorage.setItem("theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
  }, value);
};
const reflow = async () => {
  assert.equal(await page.locator("html").getAttribute("dir"), "rtl");
  const dimensions = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
  assert(dimensions.scroll <= dimensions.width + 1, `overflow ${dimensions.scroll}/${dimensions.width}`);
};
const assertModalFocus = async (dialog, step) => {
  const state = await dialog.evaluate((node) => ({
    contained:node.contains(document.activeElement),open:node.open,
    tag:document.activeElement?.tagName,id:document.activeElement?.id,
  }));
  assert(state.contained, JSON.stringify({step,...state}));
};
/** Observe mounted client controls before inspecting an SSR page. */
const clientReady = async () => {
  const toggle=page.getByRole("button",{name:"تغییر حالت روشن و تاریک",exact:true});
  if(await toggle.count()) await page.locator('button[aria-label="تغییر حالت روشن و تاریک"]:not([disabled])').waitFor();
  await page.waitForLoadState("networkidle");
};
const shot = async (name) => {
  const path = `${output}/${name}.png`;
  await page.screenshot({path, fullPage:false,caret:"initial",timeout:10000});
  evidence.screenshots.push(name + ".png");
};
/** Change only the synthetic browser's Store selection through the real UI. */
const selectStores = async (selectedLabels, currentLabel) => {
  await page.getByRole("button",{name:"انتخاب یک یا چند فروشگاه فعال",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"انتخاب فروشگاه",exact:true});await dialog.waitFor();
  for(const name of selectedLabels)await dialog.getByRole("checkbox",{name,exact:true}).check();
  await dialog.getByRole("radio",{name:currentLabel,exact:true}).check();
  for(const checkbox of await dialog.getByRole("checkbox").all()) {
    if(!selectedLabels.includes(await checkbox.getAttribute("aria-label")))await checkbox.uncheck();
  }
  await dialog.getByRole("button",{name:"اعمال انتخاب",exact:true}).click();await dialog.waitFor({state:"hidden"});
};
const loggedOut = async () => {
  if (new URL(page.url()).pathname === "/login") return;
  await page.goto(base + "/account");
  await page.getByRole("button", {name:"خروج",exact:true}).click();
  await page.waitForURL("**/login");
};
try {
  const { chromium } = await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({headless:true,args:["--no-sandbox"]});
  evidence.browser_build=browser.version();evidence.browser_mode="chromium-headless-shell";
  context = await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:"block",reducedMotion:"reduce"});
  await context.route("**/*", (route) => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
  page = await context.newPage();page.setDefaultTimeout(25000);page.setDefaultNavigationTimeout(60000);
  page.on("crash", () => {evidence.browser_crashed=true;persist();});
  page.on("pageerror", (error) => errors.push(String(error.message).slice(0,180)));
  page.on("console", message => {
    if(message.type()!=="error")return;
    const text=message.text(),url=message.location().url;
    let path="";try{path=new URL(url).pathname;}catch{}
    if((path==="/api/auth/login"&&/status of (401|428)/.test(text))||(expected404.has(path)&&/status of 404/.test(text))) evidence.expected_console_errors.push({path,text});
    else errors.push(text.slice(0,250));
  });
  page.on("requestfailed", (request) => evidence.network.push({path:new URL(request.url()).pathname, failure:request.failure()?.errorText}));
  page.on("response", (response) => { const path=new URL(response.url()).pathname; if(path.startsWith("/api/auth/")) evidence.network.push({path,status:response.status()}); });
  await check("focused login has no technical or marketing filler", async () => {
    await page.goto(base + "/dashboard", {waitUntil:"domcontentloaded"});assert.equal(new URL(page.url()).pathname,"/login");
    await page.getByRole("heading", {name:"ورود به پنل مدیریت",exact:true}).waitFor();
    // A working reveal control demonstrates client hydration before any screenshots.
    await page.getByRole("button",{name:"نمایش رمز عبور",exact:true}).click();
    assert.equal(await page.locator("#password").getAttribute("type"),"text");
    await page.getByRole("button",{name:"مخفی‌کردن رمز عبور",exact:true}).click();
    assert.equal(await page.locator("#password").getAttribute("type"),"password");
    const text = await page.locator("main").innerText();
    for (const filler of ["HTTPS", "پایگاه داده", "کنترل نقش", "ورود امن", "پیچیدگی", "حساب مدیریتی اختصاصی"]) assert(!text.includes(filler), filler);
    assert.equal(await page.getByRole("button",{name:"ورود",exact:true}).count(),1);
    assert.equal(await page.getByRole("link",{name:/Google|SSO|بازیابی رمز/}).count(),0);
  });
  await check("login reflows at five widths in both themes", async () => {
    for (const mode of ["light","dark"]) {
      await theme(mode);
      for (const width of sizes) {
        await page.setViewportSize({width,height:900});await reflow();await shot(`login-${mode}-${width}`);
      }
    }
  });
  await check("password visibility, failed login and focused error feedback",async () => {
    await page.setViewportSize({width:1280,height:900});await theme("light");
    await page.getByLabel("نام کاربری",{exact:true}).fill("shopadmin");
    await page.getByLabel("رمز عبور",{exact:true}).fill("invalid-qa-password");
    await page.getByRole("button",{name:"نمایش رمز عبور",exact:true}).click();
    assert.equal(await page.locator("#password").getAttribute("type"),"text");
    await page.getByRole("button",{name:"مخفی‌کردن رمز عبور",exact:true}).click();
    await page.getByRole("button",{name:"ورود",exact:true}).click();
    await page.locator("main").getByRole("alert").getByText("ورود انجام نشد",{exact:true}).waitFor();
    assert(await page.locator("main").getByRole("alert").evaluate((node)=>node===document.activeElement));
    assert.equal(await page.locator("#password").inputValue(),"");
  });
  await check("real password and MFA login",async () => {
    await page.getByLabel("رمز عبور",{exact:true}).fill(env.LIVE_ADMIN_PASSWORD);
    await page.getByRole("button",{name:"ورود",exact:true}).click();
    await page.locator("main").getByRole("alert").getByText("تأیید دومرحله‌ای لازم است",{exact:true}).waitFor();
    const proofStart=Date.now();const proof=await freshOtp();evidence.proof_duration_ms=Date.now()-proofStart;
    await page.getByLabel("کد تأیید دومرحله‌ای",{exact:true}).fill(proof);
    await page.getByRole("button",{name:"ورود",exact:true}).click();await page.waitForURL("**/dashboard");
  });
  await check("store dialog traps focus, Escape closes and restores trigger focus",async () => {
    const trigger=page.getByRole("button",{name:"انتخاب یک یا چند فروشگاه فعال",exact:true});
    await trigger.click();const dialog=page.getByRole("dialog",{name:"انتخاب فروشگاه",exact:true});await dialog.waitFor();
    for(let i=0;i<40;i++){await page.keyboard.press(i<20 ? "Tab" : "Shift+Tab");await assertModalFocus(dialog,i);}
    await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    assert(await trigger.evaluate((node)=>node===document.activeElement));
  });
  await check("mobile menu traps focus, closes with Escape and hides on desktop",async () => {
    await page.setViewportSize({width:320,height:900});
    const trigger=page.getByRole("button",{name:"بازکردن منوی مدیریت",exact:true});await trigger.click();
    const dialog=page.getByRole("dialog",{name:"منوی مدیریت",exact:true});await dialog.waitFor();
    for(let i=0;i<80;i++){await page.keyboard.press(i<40 ? "Tab" : "Shift+Tab");await assertModalFocus(dialog,i);}
    const drawer=await dialog.boundingBox();assert(Math.abs(drawer.x+drawer.width-320)<=1,"RTL drawer must remain at the right edge");
    await reflow();await shot("mobile-menu-light-320");
    await theme("dark");await reflow();await shot("mobile-menu-dark-320");await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    assert(await trigger.evaluate((node)=>node===document.activeElement));
    await trigger.click();await page.setViewportSize({width:1280,height:900});await dialog.waitFor({state:"hidden"});await theme("light");
  });
  await check("category dialog shares forward/reverse focus containment and Escape",async () => {
    await page.goto(base+"/products/new",{waitUntil:"domcontentloaded"});
    const picker=page.getByRole("combobox",{name:"جست‌وجو و انتخاب دسته‌بندی",exact:true});await picker.click();
    await page.getByRole("listbox",{name:"دسته‌بندی‌های موجود",exact:true}).getByRole("option").first().click();
    const edit=page.getByRole("button",{name:"ویرایش دسته‌بندی انتخاب‌شده",exact:true});await edit.click();
    const dialog=page.getByRole("dialog",{name:"ویرایش دسته‌بندی",exact:true});await dialog.waitFor();
    for(let i=0;i<12;i++){await page.keyboard.press(i<6 ? "Tab" : "Shift+Tab");await assertModalFocus(dialog,i);}
    await shot("category-dialog-light-1280");await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    assert(await edit.evaluate((node)=>node===document.activeElement));
  });
  const pages = [...new Set(JSON.parse(readFileSync("scripts/dashboard_ui_routes.json","utf8")))];
  const discovered=new Set();
  await check("all static dashboard routes render, reflow and expose page headings",async () => {
    const failures=[];
    for (const route of pages) {
      for (const [width,mode] of [[1280,"light"],[390,"dark"]]) {
        try {
        await page.setViewportSize({width,height:900});await theme(mode);
        const response=await page.goto(base+route,{waitUntil:"domcontentloaded"});assert(response.status()<400,`${route} ${response.status()}`);
        assert.notEqual(new URL(page.url()).pathname,"/login",route);
        await page.locator("main h1").first().waitFor();await clientReady();
        const heading=await page.locator("main h1").first().innerText();
        assert(!/دریافت نشد|بارگذاری نشد|با مشکل|خطا در بارگذاری/.test(heading),route+" "+heading);
        await reflow();
        for(const href of await page.locator('main a[href^="/"]').evaluateAll((links)=>links.map((a)=>a.getAttribute("href")))) if(href && !href.includes("?") && !pages.includes(href)) discovered.add(href);
        const filename=route.replaceAll("/","-").slice(1)||"index";await shot(`${filename}-${mode}-${width}`);
        evidence.routes.push({route,width,theme:mode,heading,status:"PASS",availability:await page.locator("[data-store-scope-unavailable]").count()?"restricted_by_store":"available"});console.log(`PASS route ${route} ${width} ${mode}`);persist();
        } catch(error) {
          const message=String(error.message).slice(0,250);
          failures.push({route,width,message});evidence.routes.push({route,width,theme:mode,status:"FAIL",message});
          console.log(`FAIL route ${route} ${width} ${message}`);persist();
          await shot(`route-failure-${evidence.routes.length}`).catch(()=>{});
          if(evidence.browser_crashed) throw error;
        }
      }
    }
    assert.deepEqual(failures,[]);
  });
  await check("existing detail screens render without horizontal overflow",async () => {
    for(const route of discovered) {
      if(!/^\/(products|customers|store-customers|support-tickets|campaigns|bots|staff|studio\/workflows|studio\/runtime\/runs)\/[a-zA-Z0-9_-]+(?:\/(?:edit|digital|versions|preview|settings|stores))?$/.test(route)) continue;
      await page.setViewportSize({width:390,height:900});const response=await page.goto(base+route,{waitUntil:"domcontentloaded"});
      assert(response.status()<400,`${route} ${response.status()}`);await page.locator("main h1").first().waitFor();await clientReady();await reflow();
      const heading=await page.locator("main h1").first().innerText();assert(!/دریافت نشد|بارگذاری نشد|با مشکل/.test(heading));
      await shot(`detail-${evidence.routes.length}-dark-390`);evidence.routes.push({route,width:390,theme:"dark",heading,status:"PASS"});persist();
    }
  });
  await check("normal reauthentication refreshes the sensitive-operation window",async () => {
    await page.goto(base+"/account");
    const form=page.locator("form").filter({has:page.getByRole("button",{name:"تأیید هویت برای پنج دقیقه",exact:true})});
    await form.getByLabel("رمز فعلی",{exact:true}).fill(env.LIVE_ADMIN_PASSWORD);
    await form.getByLabel("کد احراز هویت یا بازیابی",{exact:true}).fill(await freshOtp());
    await form.getByRole("button",{name:"تأیید هویت برای پنج دقیقه",exact:true}).click();
    await page.locator("main").getByRole("status").filter({hasText:"هویت شما تأیید شد."}).waitFor();
  });
  await check("settings save persists and the original synthetic name is restored",async () => {
    await page.goto(base+"/settings");
    const name=page.getByLabel("نام فروشگاه",{exact:true}), original=await name.inputValue();
    const save=page.getByRole("button",{name:"ذخیره تنظیمات",exact:true});
    try {
      await name.fill("آزمایش رابط مدیریت");await save.click();
      await page.locator("main").getByRole("status").filter({hasText:"تنظیمات ذخیره شد."}).waitFor();
      await page.reload();assert.equal(await name.inputValue(),"آزمایش رابط مدیریت");
    } finally {
      await name.fill(original);await save.click();
      await page.locator("main").getByRole("status").filter({hasText:"تنظیمات ذخیره شد."}).waitFor();
      await page.reload();assert.equal(await name.inputValue(),original);
    }
  });
  await check("retention preview respects Store scope and shows the confirmed count",async () => {
    await page.goto(base+"/customers/retention");
    const legacy=JSON.parse(await dockerAsync(`from db import session_maker,engine
from models.shop_multibot import ShopStore,DEFAULT_STORE_ID
from models.shop_staff_store import ShopStaffStoreAccess
async def main():
 async with session_maker() as db:
  store=await db.get(ShopStore,DEFAULT_STORE_ID)
  grant=await db.get(ShopStaffStoreAccess,(data["admin_id"],DEFAULT_STORE_ID))
  assert store and grant and grant.is_active and grant.access_level=="manager"
  print(json.dumps({"name":store.name}))
 await engine.dispose()
asyncio.run(main())`,fixture));
    await page.getByRole("button",{name:"انتخاب یک یا چند فروشگاه فعال",exact:true}).click();
    const dialog=page.getByRole("dialog",{name:"انتخاب فروشگاه",exact:true});await dialog.waitFor();
    const original=[];
    for(const box of await dialog.getByRole("checkbox").all())if(await box.isChecked())original.push(await box.getAttribute("aria-label"));
    const current=await dialog.locator('input[type="radio"]:checked').getAttribute("aria-label");
    await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    try {
      await selectStores([`فعال‌سازی ${legacy.name}`],`انتخاب ${legacy.name} برای ثبت تغییرات`);
      await page.goto(base+"/customers/retention");
      assert.equal(await page.locator('input[name="confirm"]').isChecked(),false);
      await page.getByRole("button",{name:"اجرای بررسی یا پاکسازی طبق تأیید",exact:true}).click();
      await page.waitForURL("**/customers/retention?saved=preview&count=*");
      assert((await page.locator("main").getByRole("status").innerText()).includes("هیچ یادداشتی حذف نشد"));
    } finally {await selectStores(original,current);}
  });
  await check("key forms, tables, settings and Studio at laptop tablet and 320px",async () => {
    for(const route of ["/dashboard","/products/new","/orders","/settings","/studio/workflows","/studio/runtime"]) {
      for(const width of [1024,768,320]) {await page.setViewportSize({width,height:900});await page.goto(base+route,{waitUntil:"domcontentloaded"});await page.locator("main h1").first().waitFor();await clientReady();await reflow();}
    }
  });
  await check("logout revokes the session and protected routes return to login",async () => {
    await page.setViewportSize({width:1280,height:900});await loggedOut();await page.goto(base+"/settings");assert.equal(new URL(page.url()).pathname,"/login");
  });
  await check("expired-session message remains clear",async () => {
    await page.goto(base+"/login?expired=1");await page.locator("main").getByRole("alert").getByText("نشست شما پایان یافته است",{exact:true}).waitFor();
  });
  await check("invalid account activation link has a clear heading and error",async () => {
    await page.goto(base+"/activate");await page.getByRole("heading",{name:"پذیرش دعوت‌نامهٔ کارکنان",exact:true}).waitFor();
    await page.locator("main").getByRole("alert").waitFor();await reflow();
  });
  await check("disabled staff cannot log in and viewer boundaries remain enforced",async () => {
    roleFixtures=JSON.parse(await dockerAsync(`import secrets
from uuid import uuid4
from scripts.test_lab_app import app
from db import session_maker,engine
from models.shop_staff import ShopStaff
from models.shop_multibot import ShopStore
from models.shop_staff_store import ShopStaffStoreAccess
from utils.utils import hash_password
async def main():
 async with session_maker.begin() as db:
  store=await db.get(ShopStore,data["store_id"])
  assert store is not None and store.slug.startswith("qa-beta-")
  result={}
  for kind,active in (("viewer",True),("disabled",False)):
   password=secrets.token_urlsafe(32)
   row=ShopStaff(username="ui_"+kind+"_"+uuid4().hex[:10],role="viewer",password_hash=hash_password(password),is_active=active,session_version=1)
   db.add(row)
   await db.flush()
   db.add(ShopStaffStoreAccess(staff_id=row.id,store_id=store.id,access_level="viewer",is_active=True,changed_by=data["admin_id"]))
   result[kind]={"id":row.id,"username":row.username,"password":password}
  print(json.dumps(result))
 await engine.dispose()
asyncio.run(main())`,fixture));
    await page.goto(base+"/login");
    await page.getByLabel("نام کاربری",{exact:true}).fill(roleFixtures.disabled.username);
    await page.getByLabel("رمز عبور",{exact:true}).fill(roleFixtures.disabled.password);
    await page.getByRole("button",{name:"ورود",exact:true}).click();
    await page.locator("#login-error").getByText("ورود انجام نشد",{exact:true}).waitFor();
    assert.equal((await context.cookies(base)).filter((cookie)=>cookie.name==="shop_admin_dev").length,0);
    await page.getByLabel("نام کاربری",{exact:true}).fill(roleFixtures.viewer.username);
    await page.getByLabel("رمز عبور",{exact:true}).fill(roleFixtures.viewer.password);
    await page.getByRole("button",{name:"ورود",exact:true}).click();await page.waitForURL("**/dashboard");
    assert.equal(await page.locator('a[href="/finance"]').count(),0);
    for(const route of ["/finance","/settings","/staff"]) {
      expected404.add(route);const response=await page.goto(base+route);assert.equal(response.status(),404,route);
      await page.getByRole("heading",{name:"صفحه مورد نظر پیدا نشد",exact:true}).waitFor();
    }
    await loggedOut();
  });
  await check("no browser runtime exceptions",async()=>assert.deepEqual(errors,[]));
  evidence.status="PASS";persist();
} catch(error) {
  evidence.status="FAIL";evidence.runtime_errors=errors;evidence.failure_headings=page ? await page.locator("main h1").allTextContents().catch(()=>[]) : [];evidence.ui_issue=page ? await page.locator("#login-error").innerText().catch(()=>null) : null;evidence.failure={name:error.name,message:String(error.message).slice(0,1800),url:page ? new URL(page.url()).pathname : null};persist();
  if(page) await shot("failure").catch(()=>{});console.error("FAIL "+JSON.stringify(evidence.failure));process.exitCode=1;
} finally {
  if(page) await loggedOut().catch(()=>{});
  // A browser crash must not leave the synthetic browser session active.
  if(context) {
    try {
      const remaining=(await context.cookies(base)).some((cookie)=>cookie.name==="shop_admin_dev");
      if(remaining) {
        const challenge=await context.request.get(base+"/api/auth/challenge",{headers:{Origin:base,"Sec-Fetch-Site":"same-origin"}});
        assert(challenge.ok());const proof=await challenge.json();
        const response=await context.request.post(base+"/api/auth/logout",{headers:{Origin:base,"Sec-Fetch-Site":"same-origin","X-Shop-Login-Challenge":proof.challenge,Accept:"application/json"}});
        assert(response.ok());assert.equal((await response.json()).ok,true);
      }
      evidence.session_cleanup="PASS";
    } catch {evidence.session_cleanup="FAIL";evidence.status="FAIL";process.exitCode=1;}
  }
  if(roleFixtures) {
    try {
      await dockerAsync(`from datetime import datetime,timezone
from sqlalchemy import select
from scripts.test_lab_app import app
from db import session_maker,engine
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStoreAccess
from models.shop_admin_control import AdminSession
async def main():
 async with session_maker.begin() as db:
  for kind,record in data.items():
   row=await db.get(ShopStaff,record["id"])
   assert row.username==record["username"] and row.username.startswith("ui_"+kind+"_")
   row.is_active=False
   row.session_version+=1
   for grant in (await db.scalars(select(ShopStaffStoreAccess).where(ShopStaffStoreAccess.staff_id==row.id))).all():
    grant.is_active=False
   for session in (await db.scalars(select(AdminSession).where(AdminSession.staff_id==row.id,AdminSession.revoked_at.is_(None)))).all():
    session.revoked_at=datetime.now(timezone.utc)
 await engine.dispose()
asyncio.run(main())`,Object.fromEntries(Object.entries(roleFixtures).map(([kind,row])=>[kind,{id:row.id,username:row.username}])));
      evidence.role_fixture_cleanup="PASS";
    } catch {evidence.role_fixture_cleanup="FAIL";evidence.status="FAIL";process.exitCode=1;}
  }
  if(context) await context.close();if(browser) await browser.close();persist();
}
