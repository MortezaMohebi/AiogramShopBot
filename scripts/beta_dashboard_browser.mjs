/** Verify the running isolated dashboard through a real browser and Next MCP.
 *
 * Run from the Beta QA worktree after the guarded seed and next dev -p3001.
 * Credentials stay in process memory; browser CLI responses to fills are never
 * logged. This script never applies provider settings or starts a campaign.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";

const values = Object.fromEntries(readFileSync(".codespaces/beta-qa.env", "utf8")
  .trim().split("\n").map(line => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]));
if (values.SHOP_BETA_QA !== "1" || values.POSTGRES_DB !== "shop_codespace" || values.TOKEN || values.BALE_BOT_TOKEN) {
  throw new Error("Only the isolated provider-free Beta runtime is permitted");
}
const session = process.env.AGENT_BROWSER_SESSION;
if (!session) throw new Error("Use a worktree-scoped agent-browser session");
const output = "/tmp/beta-dashboard-evidence";
mkdirSync(output, { recursive: true, mode: 0o700 });

function ab(...args) {
  try {
    return execFileSync("agent-browser", ["--session", session, "--restore", session, ...args],
      { encoding: "utf8", timeout: 60000, stdio: ["ignore", "pipe", "pipe"] }).trim();
  } catch {
    // Do not include execFileSync's command/arguments: fills contain secrets.
    throw new Error(`Browser action failed: ${args[0]}`);
  }
}
function assert(value, reason) { if (!value) throw new Error(reason); }
function reference(snapshot, description) {
  const line = snapshot.split("\n").find(line => line.includes(description));
  const ref = line?.match(/ref=(e\d+)/)?.[1];
  assert(ref, `Missing visible control: ${description}`);
  return "@" + ref;
}
function otp() {
  const code = `import asyncio,time
from scripts.beta_storefront_e2e import MANIFEST,session_maker,security
from models.shop_admin_control import AdminProfile
import json
async def main():
 async with session_maker() as db:
  profile=await db.get(AdminProfile,json.loads(MANIFEST.read_text())["admin_id"])
  secret=security.cipher().decrypt(profile.mfa_secret.encode()).decode()
  print(security.totp(secret,time.time()))
asyncio.run(main())`;
  return execFileSync("docker", ["compose", "-f", "compose.beta-qa.yml", "exec", "-T", "api", "python", "-c", code],
    { encoding: "utf8", timeout: 15000, stdio: ["ignore", "pipe", "pipe"] }).trim();
}
async function mcp(name) {
  const response = await fetch("http://localhost:3001/_next/mcp", {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: {} } }),
    signal: AbortSignal.timeout(30000),
  });
  assert(response.ok, "Next MCP unavailable");
  const raw = await response.text();
  const payload = JSON.parse(raw.split("\n").find(line => line.startsWith("data: ")).slice(6));
  assert(!payload.error && !payload.result?.isError, `Next MCP ${name} failed`);
  return payload.result;
}

try {
  ab("set", "viewport", "1440", "1000");
  ab("open", "http://localhost:3001/activate#invite=" + "A".repeat(43));
  ab("wait", "--fn", "location.hash === '' && document.querySelector('form') !== null");
  assert(!ab("get", "url").includes("#"), "Activation capability remained in history URL");
  const activationTree = ab("react", "tree");
  assert(activationTree.split("\n").length > 2, "React debugger did not observe mounted activation components");
  console.log("PASS  Activation: React mounted, fragment scrubbed, no hydration loop");

  ab("open", "http://localhost:3001/login");
  let snapshot = ab("snapshot", "-i");
  ab("fill", reference(snapshot, 'textbox "نام کاربری"'), "shopadmin");
  ab("fill", reference(snapshot, 'textbox "رمز عبور"'), values.LIVE_ADMIN_PASSWORD);
  ab("fill", reference(snapshot, 'textbox "کد احراز هویت'), otp());
  ab("click", reference(snapshot, 'button "ورود امن"'));
  try { ab("wait", "--url", "**/dashboard"); }
  catch {
    writeFileSync(`${output}/login-error.txt`, ab("snapshot", "-i"));
    throw new Error("Real browser login did not reach dashboard; inspect sanitized login-error.txt");
  }
  console.log("PASS  Browser: password + one-time MFA + revocable session login");

  const fixture = JSON.parse(execFileSync("docker", ["compose", "-f", "compose.beta-qa.yml", "exec", "-T", "api", "cat", "/qa/beta-fixture.json"], { encoding: "utf8" }));
  const routes = ["dashboard", "stores", "bots", `bots/${fixture.bots.telegram}`, "products", `products/${fixture.products.file}/digital`, `products/${fixture.products.license}/digital`, "store-customers", "support-tickets", "fulfillments", "digital-deliveries", "customer-notifications", "campaigns", "campaigns/new", "settings", "payment-accounts"];
  const results = [];
  for (const route of routes) {
    ab("open", "http://localhost:3001/" + route);
    ab("wait", "--load", "networkidle");
    const url = ab("get", "url");
    snapshot = ab("snapshot", "-i");
    assert(url.endsWith("/" + route), `Unexpected redirect from ${route}`);
    assert(!/Application error|Internal Server Error|This page could not be found/.test(snapshot), `Runtime failure at ${route}`);
    assert(snapshot.includes("heading"), `No accessible page heading at ${route}`);
    const metrics = JSON.parse(ab("eval", "JSON.stringify({rtl:document.documentElement.dir,width:innerWidth,scroll:document.documentElement.scrollWidth,headings:document.querySelectorAll('h1').length})").replace(/^"|"$/g, "").replace(/\\"/g, '"'));
    assert(metrics.rtl === "rtl", `RTL root missing at ${route}`);
    assert(metrics.scroll <= metrics.width + 1, `Horizontal viewport overflow at ${route}`);
    results.push({ route, desktop: "PASS", rtl: "PASS" });
  }
  ab("screenshot", `${output}/desktop.png`);
  ab("set", "viewport", "390", "844");
  ab("set", "media", "dark");
  for (const route of ["dashboard", "products", "digital-deliveries", "support-tickets"]) {
    ab("open", "http://localhost:3001/" + route);
    ab("wait", "--load", "networkidle");
    const overflow = ab("eval", "document.documentElement.scrollWidth > innerWidth + 1");
    assert(overflow === "false", `Mobile viewport overflow at ${route}`);
  }
  ab("screenshot", `${output}/mobile-dark.png`);
  const errors = await mcp("get_errors");
  const compilation = await mcp("get_compilation_issues");
  writeFileSync(`${output}/next-errors.json`, JSON.stringify({ errors, compilation }, null, 2));
  writeFileSync(`${output}/routes.json`, JSON.stringify(results, null, 2));
  console.log(`PASS  Browser: ${routes.length} routes, desktop RTL, mobile dark layout; Next MCP evidence saved`);
} catch (error) {
  console.error("FAIL  " + error.message);
  process.exitCode = 1;
}
