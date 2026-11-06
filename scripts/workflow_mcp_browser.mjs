/** Actual Native consent/withdrawal UI against the dedicated PostgreSQL lab. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const base = "http://127.0.0.1:3005";
const compose = "compose.workflow-mcp-qa.yml";
const output = "/tmp/workflow-mcp-browser";
const env = Object.fromEntries(readFileSync(".codespaces/mcp-qa.env", "utf8").trim().split("\n")
  .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]));
assert.equal(env.SHOP_MCP_QA, "1");assert.equal(env.SHOP_BETA_QA, "1");
assert.equal(env.SHOP_FASTAPI_INTERNAL_URL, "http://127.0.0.1:8095");
for (const key of ["TOKEN", "BALE_BOT_TOKEN", "BALE_WALLET_PROVIDER_TOKEN", "TELEGRAM_FIAT_PROVIDER_TOKEN"])
  if (env[key] !== "") throw Error("live_provider_credentials_not_allowed");
mkdirSync(output, { recursive: true, mode: 0o700 });
const evidence = { status: "RUNNING", origin: base, checks: [], screenshots: [], mutation_posts: 0 };
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
let stage = "guard";
const fixture = JSON.parse(docker('from pathlib import Path\nprint(Path("/qa/workflow-mcp-fixture.json").read_text())'));
try {
  await check("dedicated PostgreSQL/API and matching bridge", async () => {
    const plan = JSON.parse(execFileSync("docker", ["compose", "-f", compose, "config", "--format", "json"], { encoding: "utf8" }));
    assert.equal(plan.name, "aiogram-workflow-mcp-qa");assert.equal(plan.networks.private.internal, true);
    assert.equal(plan.services.api.ports[0].host_ip, "127.0.0.1");
    assert.equal(String(plan.services.api.ports[0].published), "8095");
    const health = await fetch("http://127.0.0.1:8095/__lab/health");assert.equal(health.status, 200);
  });
  const { chromium } = await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
  stage = "browser_launch";
  browser = await chromium.launch({ headless: true, channel: "chromium", args: ["--no-sandbox"] });
  context = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block", reducedMotion: "reduce" });
  await context.route("**/*", (route) => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
  page = await context.newPage();page.setDefaultTimeout(30000);page.setDefaultNavigationTimeout(60000);
  page.on("pageerror", () => errors.push("pageerror"));
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.startsWith("/api/admin/mcp/")) {
      evidence.mutation_posts++;assert(request.headers()["x-shop-login-challenge"]);
    }
  });
  await check("normal password and MFA login", async () => {
    stage = "login";await page.goto(base + "/studio/mcp");
    assert.equal(new URL(page.url()).pathname, "/login");
    await page.getByLabel("نام کاربری", { exact: true }).fill("shopadmin");
    await page.getByLabel("رمز عبور", { exact: true }).fill(env.LIVE_ADMIN_PASSWORD);
    await page.getByLabel("کد احراز هویت یا بازیابی (اگر فعال است)", { exact: true }).fill(await freshOtp());
    await page.getByRole("button", { name: "ورود امن", exact: true }).click();
    await page.waitForURL("**/dashboard");
  });
  await check("exact pending Native identity and explicit consent", async () => {
    stage = "consent";await page.goto(base + "/studio/mcp?pairing=" + fixture.pairing_id);
    await page.getByRole("heading", { name: "بررسی دسترسی اتصال", exact: true }).waitFor();
    assert((await page.locator("main").innerText()).includes(fixture.pairing_id));
    const before = evidence.mutation_posts;
    await page.getByRole("button", { name: "ثبت همین دسترسی اتصال", exact: true }).click();
    await page.getByText("دسترسی همین اتصال ثبت شد. ادامهٔ اتصال را در WPMCP بررسی کنید.", { exact: true }).waitFor();
    assert.equal(evidence.mutation_posts, before + 1);
  });
  await check("MCP BFF denies model-callable business approval routes", async () => {
    for (const suffix of ["approve", "deny", "commit"]) {
      const response = await context.request.post(base + `/api/admin/mcp/owned-grants/${fixture.pairing_id}/${suffix}`, { data: {} });
      assert.equal(response.status(), 404);
    }
  });
  await check("malformed post-commit withdrawal stays unknown until exact read", async () => {
    stage = "withdrawal";await page.goto(base + "/account/mcp?grant=" + fixture.pairing_id);
    await page.getByRole("button", { name: "بررسی وضعیت همین اتصال", exact: true }).click();
    const consent = page.getByRole("checkbox", { name: "لغو دسترسی همین اتصال را تأیید می‌کنم", exact: true });
    await consent.check();const before = evidence.mutation_posts;
    const target = `**/api/admin/mcp/owned-grants/${fixture.pairing_id}/revoke`;
    await page.route(target, async (route) => {
      const actual = await route.fetch();assert.equal(actual.status(), 200);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "foreign", version: 2, revoked: true }) });
    });
    await page.getByRole("button", { name: "لغو دسترسی همین اتصال", exact: true }).click();
    await page.getByText("پاسخ قطعی دریافت نشد. وضعیت همین شناسه را بخوانید؛ لغو دوباره‌ای خودکار ارسال نمی‌شود.", { exact: true }).waitFor();
    assert.equal(evidence.mutation_posts, before + 1);
    await page.unroute(target);
    await page.getByRole("button", { name: "بررسی وضعیت همین اتصال", exact: true }).click();
    await page.getByText("رسید لغو همین دسترسی دریافت شد.", { exact: true }).waitFor();
    assert.equal(evidence.mutation_posts, before + 1);
  });
  await check("desktop/mobile light/dark Persian RTL without overflow", async () => {
    stage = "layout";
    for (const theme of ["light", "dark"]) for (const width of [390, 1280]) {
      await context.addInitScript((value) => localStorage.setItem("theme", value), theme);
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/studio/mcp", "/account/mcp?grant=" + fixture.pairing_id]) {
        await page.goto(base + path);await page.locator("main h1").waitFor();
        await page.waitForFunction((value) => document.documentElement.classList.contains(value), theme);
        const layout = await page.evaluate(() => ({ dir: document.documentElement.dir,
          overflow: document.documentElement.scrollWidth - window.innerWidth }));
        assert.equal(layout.dir, "rtl");assert(layout.overflow <= 1);
        const name = `${path.startsWith("/studio") ? "connections" : "withdrawal"}-${theme}-${width}.png`;
        await page.screenshot({ path: output + "/" + name });evidence.screenshots.push(name);
      }
    }
  });
  await check("no browser application error and authoritative withdrawn receipt", async () => {
    assert.deepEqual(errors, []);
    const result = JSON.parse(docker(`from db import session_maker,engine
from models.shop_mcp import McpGrant
async def main():
 async with session_maker() as db:
  row=await db.get(McpGrant,data["pairing_id"])
  print(json.dumps({"revoked":row.revoked_at is not None,"version":row.version}))
 await engine.dispose()
asyncio.run(main())`, fixture));
    assert.equal(result.revoked, true);assert.equal(result.version, 2);
  });
  evidence.status = "PASS";
} catch (error) {
  evidence.status = "FAIL";evidence.stage = stage;evidence.reason = error.name;
  console.error("FAIL  " + stage + ": " + error.name);process.exitCode = 1;
} finally {
  if (page && new URL(page.url()).pathname !== "/login") {
    try {
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto(base + "/dashboard");
      if (new URL(page.url()).pathname !== "/login") {
        await page.getByRole("button", { name: "خروج امن", exact: true }).click({ timeout: 10000 });
        await page.waitForURL("**/login", { timeout: 10000 });
      }
    } catch { evidence.cleanup_unconfirmed = true; }
  }
  persist();await context?.close();await browser?.close();
}
