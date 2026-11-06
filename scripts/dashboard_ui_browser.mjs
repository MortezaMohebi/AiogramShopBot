/** Actual Native consent/withdrawal UI against the dedicated PostgreSQL lab. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
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
async function check(name, run) {
  try { await run();evidence.checks.push({ name, status: "PASS" });console.log("PASS  " + name); }
  catch (error) { evidence.checks.push({ name, status: "FAIL", reason: error.name });throw error; }
  finally { persist(); }
}

/** Only the unused current synthetic authenticator proof leaves the lab process. */
async function freshOtp() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const value = JSON.parse(docker(`import time
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


let browser, context, page;
const errors = [];
evidence.network = [];
const fixture = JSON.parse(docker('from pathlib import Path\nprint(Path("/qa/workflow-mcp-fixture.json").read_text())'));
const sizes = [1440, 1024, 768, 390, 320];
const theme = async (value) => {
  await page.addInitScript((theme) => localStorage.setItem("theme", theme), value);
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
const shot = async (name) => {
  const path = `${output}/${name}.png`;
  await page.screenshot({path, fullPage:false});
  evidence.screenshots.push(name + ".png");
};
const loggedOut = async () => {
  if (new URL(page.url()).pathname === "/login") return;
  await page.goto(base + "/account");
  await page.getByRole("button", {name:"خروج",exact:true}).click();
  await page.waitForURL("**/login");
};
try {
  const { chromium } = await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({headless:true,channel:"chromium",args:["--no-sandbox"]});
  context = await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:"block",reducedMotion:"reduce"});
  await context.route("**/*", (route) => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
  page = await context.newPage();page.setDefaultTimeout(25000);page.setDefaultNavigationTimeout(60000);
  page.setDefaultTimeout(25000);
  page.on("pageerror", (error) => errors.push(String(error.message).slice(0,180)));
  page.on("requestfailed", (request) => evidence.network.push({path:new URL(request.url()).pathname, failure:request.failure()?.errorText}));
  page.on("response", (response) => { const path=new URL(response.url()).pathname; if(path.startsWith("/api/auth/")) evidence.network.push({path,status:response.status()}); });
  await check("focused login has no technical or marketing filler", async () => {
    await page.goto(base + "/dashboard", {waitUntil:"domcontentloaded"});assert.equal(new URL(page.url()).pathname,"/login");
    await page.getByRole("heading", {name:"ورود به پنل مدیریت",exact:true}).waitFor();
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
    for(let i=0;i<14;i++){await page.keyboard.press("Tab");assert(await dialog.evaluate((node)=>node.contains(document.activeElement)));}
    await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    assert(await trigger.evaluate((node)=>node===document.activeElement));
  });
  await check("mobile menu traps focus, closes with Escape and hides on desktop",async () => {
    await page.setViewportSize({width:320,height:900});
    const trigger=page.getByRole("button",{name:"بازکردن منوی مدیریت",exact:true});await trigger.click();
    const dialog=page.getByRole("dialog",{name:"منوی مدیریت",exact:true});await dialog.waitFor();
    for(let i=0;i<35;i++){await page.keyboard.press("Tab");assert(await dialog.evaluate((node)=>node.contains(document.activeElement)));}
    await reflow();await shot("mobile-menu-dark-320");await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    assert(await trigger.evaluate((node)=>node===document.activeElement));
    await trigger.click();await page.setViewportSize({width:1280,height:900});await dialog.waitFor({state:"hidden"});
  });
  const pages = [...new Set(JSON.parse(readFileSync("scripts/dashboard_ui_routes.json","utf8")))];
  const discovered=new Set();
  await check("all static dashboard routes render, reflow and expose page headings",async () => {
    for (const route of pages) {
      for (const [width,mode] of [[1280,"light"],[390,"dark"]]) {
        await page.setViewportSize({width,height:900});await theme(mode);
        const response=await page.goto(base+route,{waitUntil:"domcontentloaded"});assert(response.status()<400,`${route} ${response.status()}`);
        assert.notEqual(new URL(page.url()).pathname,"/login",route);
        await page.locator("main h1").first().waitFor();
        const heading=await page.locator("main h1").first().innerText();
        assert(!/دریافت نشد|بارگذاری نشد|با مشکل|خطا در بارگذاری/.test(heading),route+" "+heading);
        await reflow();
        for(const href of await page.locator('main a[href^="/"]').evaluateAll((links)=>links.map((a)=>a.getAttribute("href")))) if(href && !href.includes("?") && !pages.includes(href)) discovered.add(href);
        const filename=route.replaceAll("/","-").slice(1)||"index";await shot(`${filename}-${mode}-${width}`);
        evidence.routes.push({route,width,theme:mode,heading,status:"PASS"});persist();
      }
    }
  });
  await check("existing detail screens render without horizontal overflow",async () => {
    for(const route of discovered) {
      if(!/^\/(products|customers|store-customers|support-tickets|campaigns|bots|staff|studio\/workflows|studio\/runtime\/runs)\/[a-zA-Z0-9_-]+(?:\/(?:edit|digital|versions|preview|settings|stores))?$/.test(route)) continue;
      await page.setViewportSize({width:390,height:900});const response=await page.goto(base+route,{waitUntil:"domcontentloaded"});
      assert(response.status()<400,`${route} ${response.status()}`);await page.locator("main h1").first().waitFor();await reflow();
      const heading=await page.locator("main h1").first().innerText();assert(!/دریافت نشد|بارگذاری نشد|با مشکل/.test(heading));
      await shot(`detail-${evidence.routes.length}-dark-390`);evidence.routes.push({route,width:390,theme:"dark",heading,status:"PASS"});persist();
    }
  });
  await check("key forms, tables, settings and Studio at laptop tablet and 320px",async () => {
    for(const route of ["/dashboard","/products/new","/orders","/settings","/studio/workflows","/studio/runtime"]) {
      for(const width of [1024,768,320]) {await page.setViewportSize({width,height:900});await page.goto(base+route,{waitUntil:"domcontentloaded"});await page.locator("main h1").first().waitFor();await reflow();}
    }
  });
  await check("logout revokes the session and protected routes return to login",async () => {
    await page.setViewportSize({width:1280,height:900});await loggedOut();await page.goto(base+"/settings");assert.equal(new URL(page.url()).pathname,"/login");
  });
  await check("expired-session message remains clear",async () => {
    await page.goto(base+"/login?expired=1");await page.locator("main").getByRole("alert").getByText("نشست شما پایان یافته است",{exact:true}).waitFor();
  });
  await check("no browser runtime exceptions",async()=>assert.deepEqual(errors,[]));
  evidence.status="PASS";persist();
} catch(error) {
  evidence.status="FAIL";evidence.ui_issue=page ? await page.locator("#login-error").innerText().catch(()=>null) : null;evidence.failure={name:error.name,message:String(error.message).slice(0,400),url:page ? new URL(page.url()).pathname : null};persist();
  if(page) await shot("failure").catch(()=>{});console.error("FAIL "+JSON.stringify(evidence.failure));process.exitCode=1;
} finally {
  if(page) await loggedOut().catch(()=>{});
  if(context) await context.close();if(browser) await browser.close();
}
