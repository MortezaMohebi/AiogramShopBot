/**
 * Exercise the real Runtime dashboard in the isolated PostgreSQL QA stack.
 *
 * Run from the repository root with WORKFLOW_PLAYWRIGHT_MODULE pointing to the
 * existing playwright-core/index.mjs. The only browser origin is localhost:3004;
 * its signed bridge must target compose.workflow-runtime-qa.yml on port 8094.
 * Credentials, MFA proofs, customer answers and session cookies stay in memory.
 * Only a post-commit browser response is corrupted for uncertainty scenarios.
 */
import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { pathToFileURL } from "node:url";

const base = "http://localhost:3004";
const compose = "compose.workflow-runtime-qa.yml";
const output = "/tmp/workflow-runtime-browser";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const checks = [
  "isolated Runtime compose and matching Next checkout",
  "normal password and MFA login",
  "all Runtime tabs and private Run detail",
  "uncertain delivery has no retry capability",
  "real read-only account and absent Store gate",
  "hostile closed BFF requests and Store isolation",
  "exact saved publication preview and explicit approval",
  "new publication and explicit rollback preserve pinned Runs",
  "fresh authentication denial and normal account reauthentication",
  "malformed successful gate receipt stays unknown without replay",
  "mismatched successful gate receipt stays unknown without replay",
  "known suspended Run requires capability and explicit recovery",
  "desktop and mobile light/dark RTL without overflow",
  "no browser or Next application errors",
  "protected PostgreSQL fixtures remain unchanged",
  "test sessions end through normal logout",
];

/** An allowlisted diagnostic code never incorporates a response or a secret. */
class CheckFailure extends Error {
  constructor(code) {
    super(code);
    this.name = "CheckFailure";
    this.code = code;
  }
}
function requireSafe(condition, code) {
  if (!condition) throw new CheckFailure(code);
}

/** Parse the existing unquoted lab env format, rejecting ambiguous duplicates. */
function readLabEnvironment() {
  const result = {};
  for (const raw of readFileSync(".codespaces/beta-qa.env", "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const index = line.indexOf("=");
    requireSafe(index > 0, "lab_env_format");
    const key = line.slice(0, index);
    requireSafe(/^[A-Z][A-Z0-9_]*$/.test(key), "lab_env_key");
    requireSafe(!Object.hasOwn(result, key), "lab_env_duplicate_key");
    result[key] = line.slice(index + 1);
  }
  return result;
}

/** Mirror require_isolated_lab before Docker, app imports or browser startup. */
function requireLabEnvironment(env) {
  const exact = {
    SHOP_BETA_QA: "1",
    CODESPACE_FRESH_SCHEMA: "true",
    SHOP_TEST_LAB: "1",
    POSTGRES_DB: "shop_codespace",
    POSTGRES_USER: "shop_codespace",
    DB_HOST: "postgres",
    WEBHOOK_HOST: "https://disabled.invalid",
    NEXT_ADMIN_BRIDGE_ENABLED: "true",
    SHOP_CAMPAIGN_DISPATCH_ENABLED: "false",
    SHOP_BROADCAST_WORKER_ENABLED: "false",
    BALE_BROADCAST_PAID_ENABLED: "false",
    TELEGRAM_STARS_REFUNDS_ENABLED: "false",
    TELEGRAM_STARS_CHECKOUT_ENABLED: "false",
    TELEGRAM_FIAT_CHECKOUT_ENABLED: "false",
    BALE_WALLET_CHECKOUT_ENABLED: "false",
    CRYPTO_FORWARDING_MODE: "false",
    SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR: "0",
    BALE_BROADCAST_PREPARE_CHAT_ID: "0",
  };
  for (const [key, value] of Object.entries(exact)) {
    requireSafe(env[key] === value, "unsafe_lab_environment");
    requireSafe(
      process.env[key] === undefined || process.env[key] === value,
      "unsafe_host_override",
    );
  }
  for (const key of [
    "SHOP_BROADCAST_REGISTRY_ENABLED",
    "MULTIBOT_V2_RUNTIME_ENABLED",
    "SHOP_DIGITAL_DELIVERY_ENABLED",
    "SHOP_CUSTOMER_NOTIFICATIONS_ENABLED",
    "SHOP_RELAY_POOL_ENABLED",
  ]) {
    requireSafe((env[key] ?? "false") === "false", "unsafe_worker_environment");
    requireSafe(
      (process.env[key] ?? "false") === "false",
      "unsafe_worker_override",
    );
  }
  for (const key of [
    "TOKEN",
    "BALE_BOT_TOKEN",
    "BALE_WALLET_PROVIDER_TOKEN",
    "TELEGRAM_FIAT_PROVIDER_TOKEN",
    "TELEGRAM_WORKER_SECRET",
    "BALE_WEBHOOK_SECRET",
    "KRYPTO_EXPRESS_API_KEY",
  ]) {
    requireSafe(!env[key]?.trim(), "provider_credential_present");
    requireSafe(!process.env[key]?.trim(), "host_provider_credential_present");
  }
  for (const key of ["NEXT_ADMIN_BRIDGE_SECRET", "JWT_SECRET_KEY"]) {
    requireSafe(env[key]?.length >= 32, "lab_secret_missing");
  }
  requireSafe(env.LIVE_ADMIN_PASSWORD?.length >= 16, "lab_password_missing");
  for (const [key, value] of Object.entries({
    SHOP_RUNTIME_QA: "1",
    SHOP_WORKFLOW_RUNTIME_ENABLED: "true",
    SHOP_WORKFLOW_RUNTIME_KILL_SWITCH: "false",
  })) {
    requireSafe(env[key] === undefined || env[key] === value, "unsafe_runtime_env");
    requireSafe(
      process.env[key] === undefined || process.env[key] === value,
      "unsafe_runtime_override",
    );
  }
  requireSafe(
    !process.env.WORKFLOW_QA_COMPOSE || process.env.WORKFLOW_QA_COMPOSE === compose,
    "wrong_compose_override",
  );
  requireSafe(
    !process.env.PYTHONOPTIMIZE || process.env.PYTHONOPTIMIZE === "0",
    "optimized_python_forbidden",
  );
}

// Safety errors deliberately produce only a stable code, never a stack trace.
let env;
try {
  env = readLabEnvironment();
  requireLabEnvironment(env);
} catch (error) {
  console.error("FAIL  " + (error instanceof CheckFailure ? error.code : "lab_env_unavailable"));
  process.exit(1);
}
if (process.argv.includes("--guards-only")) {
  console.log("PASS  environment guards only; browser and PostgreSQL not executed");
  process.exit(0);
}
requireSafe(process.argv.length === 2, "unknown_runner_argument");

mkdirSync(output, { recursive: true, mode: 0o700 });
const evidence = {
  origin: base,
  compose_project: "aiogram-workflow-runtime-qa",
  checks: checks.map((check) => ({ check, status: "BLOCKED" })),
  screenshots: [],
  fixtures: {},
  denied_browser_requests: 0,
  status: "RUNNING",
};
const evidencePath = output + "/evidence.json";
const persist = () =>
  writeFileSync(evidencePath, JSON.stringify(evidence, null, 2), { mode: 0o600 });
persist();
let stage = "bootstrap";
let browser;
let admin;
let viewer;
let fixture;
let protectedBefore;
let browserWorkflow;
let browserRunId;
let firstPublication;
let finalPublication;
let privacyFailures = 0;
const privateValues = new Set();
privateValues.add(env.LIVE_ADMIN_PASSWORD);
const pageErrors = [];
const consoleErrors = [];
const mutationRequests = [];
const responseChecks = new Set();
const expectedUiFailures = new Set();

/** Capture Docker output privately; child exceptions must never reach stdout. */
function docker(code, input = {}) {
  const prelude = `import os,sys,json,asyncio
from scripts.test_lab_safety import require_isolated_lab
require_isolated_lab()
if os.environ.get("SHOP_RUNTIME_QA")!="1" or not __debug__:
 raise RuntimeError("runtime_qa_required")
if os.environ.get("SHOP_WORKFLOW_RUNTIME_ENABLED")!="true" or os.environ.get("SHOP_WORKFLOW_RUNTIME_KILL_SWITCH","false")!="false":
 raise RuntimeError("runtime_flags_required")
data=json.loads(sys.stdin.read())
`;
  try {
    return execFileSync(
      "docker",
      ["compose", "-f", compose, "exec", "-T", "api", "python", "-c", prelude + code],
      {
        input: JSON.stringify(input),
        encoding: "utf8",
        timeout: 45000,
        maxBuffer: 4 * 1024 * 1024,
        stdio: ["pipe", "pipe", "pipe"],
      },
    ).trim();
  } catch {
    throw new CheckFailure("guarded_docker_operation_failed");
  }
}

async function check(name, operation) {
  stage = name;
  const item = evidence.checks.find((row) => row.check === name);
  try {
    await operation();
    item.status = "PASS";
    console.log("PASS  " + name);
    return true;
  } catch (error) {
    item.status = "FAIL";
    item.reason = error instanceof CheckFailure ? error.code : error.name || "Error";
    console.error("FAIL  " + name + ": " + item.reason);
    return false;
  } finally {
    persist();
  }
}

/** Keep scalar canaries in memory; never persist the data used to detect leaks. */
function rememberPrivate(value) {
  if (Array.isArray(value)) value.forEach(rememberPrivate);
  else if (value && typeof value === "object") Object.values(value).forEach(rememberPrivate);
  else if (value !== null && value !== undefined && typeof value !== "boolean" && String(value).length >= 4)
    privateValues.add(String(value));
}
function hasPrivate(value) {
  if (Array.isArray(value)) return value.some(hasPrivate);
  if (value && typeof value === "object") return Object.values(value).some(hasPrivate);
  if (value === null || value === undefined) return false;
  const text = String(value);
  return privateValues.has(text) || [...privateValues].some((secret) => secret.length >= 8 && text.includes(secret));
}
function assertPrivate(value) {
  requireSafe(!hasPrivate(value), "private_runtime_data_exposed");
}

/** The Compose plan is checked as structured data, with no secret output. */
function requireRuntimeCompose() {
  let config;
  try {
    config = JSON.parse(
      execFileSync("docker", ["compose", "-f", compose, "config", "--format", "json"], {
        encoding: "utf8",
        timeout: 15000,
        maxBuffer: 1024 * 1024,
        stdio: ["ignore", "pipe", "pipe"],
      }),
    );
  } catch {
    throw new CheckFailure("runtime_compose_unavailable");
  }
  requireSafe(config.name === "aiogram-workflow-runtime-qa", "wrong_runtime_project");
  requireSafe(
    Object.keys(config.services).sort().join(",") === "api,bootstrap,postgres,redis",
    "unexpected_runtime_service",
  );
  const api = config.services.api;
  requireLabEnvironment({ ...env, ...api.environment });
  requireSafe(api.environment.SHOP_RUNTIME_QA === "1", "runtime_qa_not_enabled");
  requireSafe(api.environment.SHOP_WORKFLOW_RUNTIME_ENABLED === "true", "runtime_not_enabled");
  requireSafe(api.environment.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH === "false", "runtime_killed");
  requireSafe(
    api.ports?.length === 1 && api.ports[0].host_ip === "127.0.0.1" &&
      String(api.ports[0].published) === "8094" && Number(api.ports[0].target) === 5000,
    "wrong_runtime_api_binding",
  );
  requireSafe(config.networks.private.internal === true, "runtime_network_not_private");
  requireSafe(api.command?.join(" ").includes("scripts.test_lab_app:app"), "unexpected_api_process");
}

/** Bound both JSON and SSE responses; MCP streams must not keep acceptance open. */
async function nextRpc(method, params) {
  const response = await fetch(base + "/_next/mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    signal: AbortSignal.timeout(30000),
  });
  requireSafe(response.ok, "next_mcp_unavailable");
  let payload;
  if (response.headers.get("content-type")?.includes("application/json")) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let text = "";
    let total = 0;
    try {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        total += part.value.length;
        requireSafe(total <= 1024 * 1024, "next_mcp_body_limit");
        text += decoder.decode(part.value, { stream: true });
      }
      text += decoder.decode();
      payload = JSON.parse(text);
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
  } else {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    let total = 0;
    try {
      while (!payload) {
        const part = await reader.read();
        requireSafe(!part.done, "next_mcp_stream_ended");
        total += part.value.length;
        requireSafe(total <= 1024 * 1024, "next_mcp_body_limit");
        buffered += decoder.decode(part.value, { stream: true });
        buffered = buffered.replace(/\r\n/g, "\n");
        let end;
        while ((end = buffered.indexOf("\n\n")) >= 0) {
          const event = buffered.slice(0, end);
          buffered = buffered.slice(end + 2);
          const data = event.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (!data) continue;
          const message = JSON.parse(data);
          if (message.id === 1) payload = message;
        }
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
  }
  requireSafe(payload.result && !payload.result.isError, "next_mcp_tool_failed");
  return payload.result;
}
const nextTool = (name) => nextRpc("tools/call", { name, arguments: {} });

/** Validate installed Next 16.4 structured results, never success-like prose. */
function assertNextClean(result, tool) {
  const code = tool === "get_errors" ? "next_application_error" : "next_compilation_issue";
  requireSafe(result && !result.isError && result.content?.length === 1 && result.content[0].type === "text", code);
  let value;
  try { value = JSON.parse(result.content[0].text); }
  catch { throw new CheckFailure(code); }
  requireSafe(value && typeof value === "object" && !Array.isArray(value) && !Object.hasOwn(value, "error"), code);
  if (tool === "get_errors") {
    requireSafe(Array.isArray(value.configErrors) && value.configErrors.length === 0 && Array.isArray(value.sessionErrors) && value.sessionErrors.length === 0, code);
  } else {
    requireSafe(tool === "get_compilation_issues" && Array.isArray(value.issues) && value.issues.length === 0, code);
  }
}

/** Wait for a fresh TOTP step rather than reuse the parent's consumed proof. */
async function freshOtp() {
  const deadline = Date.now() + 40000;
  while (Date.now() < deadline) {
    const value = JSON.parse(docker(`import time
from scripts.beta_storefront_e2e import MANIFEST,session_maker,security,engine
from models.shop_admin_control import AdminProfile
async def main():
 async with session_maker() as db:
  profile=await db.get(AdminProfile,json.loads(MANIFEST.read_text())["admin_id"])
  assert profile and profile.mfa_secret
  now=time.time()
  if int(now//30)<=profile.last_totp_step:
   print(json.dumps({"wait_ms":min(31000,int((30-now%30)*1000)+150)}))
  else:
   secret=security.cipher().decrypt(profile.mfa_secret.encode()).decode()
   print(json.dumps({"proof":security.totp(secret,now)}))
 await engine.dispose()
asyncio.run(main())`));
    if (value.proof) {
      rememberPrivate(value.proof);
      return value.proof;
    }
    await new Promise((resolve) => setTimeout(resolve, value.wait_ms));
  }
  throw new CheckFailure("fresh_mfa_step_unavailable");
}

/** Read protected Run/binding pointers without private state or global counts. */
function protectedSnapshot() {
  return JSON.parse(docker(`from sqlalchemy import select
from scripts.beta_storefront_e2e import session_maker,engine
from models.shop_workflow_runtime import WorkflowRun,RuntimeBinding
async def main():
 async with session_maker() as db:
  ids=[r["run_id"] for r in data["runs"]]
  rows=(await db.scalars(select(WorkflowRun).where(WorkflowRun.id.in_(ids)).order_by(WorkflowRun.id))).all()
  bindings=(await db.scalars(select(RuntimeBinding).where(RuntimeBinding.workflow_id==data["workflow_id"]).order_by(RuntimeBinding.id))).all()
  print(json.dumps({"runs":[[r.id,r.publication_id,r.node_id,r.status,r.lock_version] for r in rows],"bindings":[[b.id,b.publication_id,b.version,b.enabled] for b in bindings]}))
 await engine.dispose()
asyncio.run(main())`, fixture.fixture));
}

/** Add only disposable QA principals and an uncredentialed synthetic Bot. */
function bootstrapFixtures() {
  const username = "runtime_viewer_" + randomBytes(6).toString("hex");
  const password = randomBytes(32).toString("base64url");
  rememberPrivate(password);
  const result = JSON.parse(docker(`from pathlib import Path
from uuid import uuid4
from sqlalchemy import select,text
from scripts.beta_storefront_e2e import MANIFEST,session_maker,engine
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStoreAccess
from models.shop_multibot import ShopBot,ShopStore
from models.shop_workflow_runtime import WorkflowRun,WorkflowUpload,RuntimeGate
from utils.utils import hash_password
async def main():
 manifest=json.loads(MANIFEST.read_text())
 fixture=json.loads(Path("/qa/workflow-runtime-fixture.json").read_text())
 assert fixture["store_id"]==manifest["stores"][0]
 assert fixture["runs"] and fixture["workflow_id"] and fixture["publication_id"]
 async with session_maker() as db:
  assert (await db.execute(text("select current_database()"))).scalar_one()=="shop_codespace"
  staff=await db.get(ShopStaff,manifest["admin_id"])
  assert staff and staff.username=="shopadmin" and staff.role=="superadmin"
  stores=(await db.scalars(select(ShopStore).where(ShopStore.id.in_([fixture["store_id"],fixture["foreign_store_id"]])))).all()
  assert len(stores)==2
  store_names={s.id:s.name for s in stores}
  own_store=ShopStore(id=str(uuid4()),slug="browser-default-"+str(uuid4())[:12],name="فروشگاه بدون مجوز Runtime مرورگر",state="active")
  db.add(own_store)
  account=ShopStaff(username=data["username"],password_hash=hash_password(data["password"]),role="viewer",is_active=True,session_version=1)
  db.add(account)
  await db.flush()
  for store_id in (fixture["store_id"],own_store.id):
   db.add(ShopStaffStoreAccess(staff_id=account.id,store_id=store_id,access_level="viewer",is_active=True,changed_by=staff.id))
  bot_id=str(uuid4())
  bot=ShopBot(id=bot_id,store_id=fixture["store_id"],slug="runtime-browser-"+bot_id[:12],name="ربات مصنوعی Runtime مرورگر "+bot_id[:8],platform="telegram",status="active",runtime_owner="registry",credential_version=1,version=1)
  db.add(bot)
  rows=(await db.scalars(select(WorkflowRun).where(WorkflowRun.id.in_([r["run_id"] for r in fixture["runs"]])))).all()
  private=[r.values for r in rows]
  private.extend((await db.scalars(select(WorkflowUpload.file_id).where(WorkflowUpload.store_id==fixture["store_id"]))).all())
  assert await db.scalar(select(RuntimeGate.scope_key).where(RuntimeGate.store_id==own_store.id)) is None
  await db.commit()
  print(json.dumps({"fixture":fixture,"store_names":store_names,"viewer_store_id":own_store.id,"viewer_store_name":own_store.name,"viewer_id":account.id,"bot_id":bot.id,"bot_name":bot.name,"private_values":private}))
 await engine.dispose()
asyncio.run(main())`, { username, password }));
  rememberPrivate(result.private_values);
  delete result.private_values;
  return { ...result, username, password };
}

/** All Playwright pages share the same fail-closed loopback network boundary. */
async function newSession(chromiumBrowser) {
  const context = await chromiumBrowser.newContext({
    viewport: { width: 1100, height: 1000 },
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  await context.route("**/*", async (route) => {
    if (new URL(route.request().url()).origin === base) await route.continue();
    else {
      evidence.denied_browser_requests++;
      await route.abort("blockedbyclient");
    }
  });
  if (typeof context.routeWebSocket === "function") {
    await context.routeWebSocket("**/*", (socket) => {
      const url = new URL(socket.url());
      if (url.protocol === "ws:" && url.host === new URL(base).host) socket.connectToServer();
      else {
        evidence.denied_browser_requests++;
        socket.close();
      }
    });
  }
  const session = { context, page: null, loggedIn: false, viewport: { width: 1100, height: 1000 } };
  context.on("page", (page) => observePage(page));
  session.page = await context.newPage();
  return session;
}

/** Diagnostics retain paths/types/counts, never console text or raw exception data. */
function observePage(page) {
  page.setDefaultTimeout(30000);
  page.setDefaultNavigationTimeout(60000);
  page.on("pageerror", () => pageErrors.push({ type: "pageerror" }));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    let path = "";
    try { path = new URL(message.location().url).pathname; } catch { /* Browser-internal source. */ }
    consoleErrors.push({ path, resource: /^Failed to load resource:/.test(message.text()) });
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === base && url.pathname.startsWith("/api/admin/workflow-runtime") && request.method() === "POST") {
      // Intent payloads are needed only in memory for exact audit matching.
      mutationRequests.push({ path: url.pathname, payload: request.postDataJSON() });
    }
  });
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (!path.startsWith("/api/admin/workflow-runtime") || !response.ok()) return;
    const task = response.json().then((value) => {
      if (hasPrivate(value)) privacyFailures++;
    }).catch(() => undefined).finally(() => responseChecks.delete(task));
    responseChecks.add(task);
  });
}

async function ready(page) {
  await page.waitForFunction(() => {
    const button = document.querySelector('[aria-label="تغییر حالت روشن و تاریک"]');
    return button && !button.disabled;
  });
}
async function open(session, path) {
  requireSafe(path.startsWith("/studio/runtime") || path === "/account", "unexpected_ui_path");
  if (session.page) await session.page.close();
  session.page = await session.context.newPage();
  await session.page.setViewportSize(session.viewport);
  await session.page.goto(base + path);
  requireSafe(!new URL(session.page.url()).pathname.startsWith("/login"), "session_expired");
  await session.page.locator("main h1").waitFor();
  await ready(session.page);
  return session.page;
}
async function login(session, username, password, factor = false) {
  const page = session.page;
  await page.goto(base + "/studio/runtime");
  requireSafe(new URL(page.url()).pathname === "/login", "normal_login_not_required");
  await page.getByLabel("نام کاربری", { exact: true }).fill(username);
  await page.getByLabel("رمز عبور", { exact: true }).fill(password);
  if (factor)
    await page.getByLabel("کد احراز هویت یا بازیابی (اگر فعال است)", { exact: true }).fill(await freshOtp());
  await page.getByRole("button", { name: "ورود امن", exact: true }).click();
  await page.waitForURL("**/dashboard");
  session.loggedIn = true;
  session.username = username;
  session.freshAt = Date.now();
  session.backendToken = await ownSessionToken(session);
  await ready(page);
}
async function chooseStore(session, name) {
  const page = session.page;
  await page.getByRole("button", { name: "انتخاب یک یا چند فروشگاه فعال", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Store Switcher", exact: true });
  await dialog.getByRole("radio", { name: `انتخاب ${name} برای ثبت تغییرات`, exact: true }).check();
  await dialog.getByRole("button", { name: "اعمال انتخاب", exact: true }).click();
  await dialog.waitFor({ state: "hidden" });
  await ready(page);
}

/** API requests use only the local BFF and its normal session/CSRF challenge. */
async function bff(session, path, { method = "GET", body, headers = {}, challenge = method !== "GET", status = 200, raw } = {}) {
  requireSafe(/^\/api\/(admin|auth)\//.test(path) && !path.includes("://"), "unexpected_bff_path");
  const merged = { Origin: base, "sec-fetch-site": "same-origin", ...headers };
  if (challenge) {
    const response = await session.context.request.get(base + "/api/auth/challenge", {
      headers: { Origin: base, "sec-fetch-site": "same-origin" }, timeout: 30000,
    });
    requireSafe(response.status() === 200, "csrf_challenge_unavailable");
    const value = await response.json();
    requireSafe(/^[A-Za-z0-9_-]{43}$/.test(value.challenge), "csrf_challenge_invalid");
    rememberPrivate(value.challenge);
    merged["x-shop-login-challenge"] = value.challenge;
  }
  if (method !== "GET" && !Object.hasOwn(merged, "Content-Type")) merged["Content-Type"] = "application/json";
  const response = await session.context.request.fetch(base + path, {
    method, headers: merged, data: raw ?? (body === undefined ? undefined : JSON.stringify(body)),
    timeout: 30000, maxRedirects: 0,
  });
  requireSafe(response.status() === status, "unexpected_bff_status");
  const value = await response.json();
  if (path.startsWith("/api/admin/workflow-runtime")) assertPrivate(value);
  return value;
}

/** Compare visible private-free overview aggregates with the signed Store read. */
async function assertOperationalOverview(page, overview) {
  requireSafe(overview.metrics_scope?.window === "all_retained_history" && overview.metrics_scope.store_id === fixture.fixture.store_id, "runtime_metrics_scope_missing");
  const metrics = page.locator("section").filter({ has: page.getByRole("heading", { name: "آمار عملیاتی فروشگاه", exact: true }) });
  requireSafe((await metrics.innerText()).includes("تمام تاریخچهٔ نگهداری‌شدهٔ فروشگاه جاری"), "runtime_metrics_scope_not_rendered");
  const fields = [
    ["runs_started", "اجراهای آغازشده"], ["runs_completed", "اجراهای تکمیل‌شده"],
    ["runs_cancelled", "اجراهای لغوشده"], ["runs_failed", "اجراهای ناموفق"],
    ["node_transitions", "عبور از گره‌ها"], ["input_validation_errors", "خطاهای اعتبارسنجی ورودی"],
    ["action_failures", "خطاهای Action"], ["timeouts", "پایان مهلت‌ها"],
    ["duplicate_events", "رویدادهای تکراری"], ["outbox_retries", "تلاش‌های مجدد ارسال"],
    ["outbox_deadletters", "ارسال‌های متوقف‌شده پس از خطا"],
  ];
  const shown = (label) => metrics.locator("dl > div").filter({ has: page.getByText(label, { exact: true }) }).locator("dd").innerText();
  for (const [key, label] of fields) {
    const value = overview.metrics?.[key];
    requireSafe(Number.isFinite(value) && value >= 0 && await shown(label) === value.toLocaleString("fa-IR"), "runtime_metric_not_exact");
  }
  const duration = overview.metrics.completed_duration_seconds_avg;
  requireSafe(duration === null || (Number.isFinite(duration) && duration >= 0), "runtime_metric_duration_invalid");
  const durationText = duration === null ? "نمونهٔ تکمیل‌شده‌ای وجود ندارد" : `${duration.toLocaleString("fa-IR", { maximumFractionDigits: 2 })} ثانیه`;
  requireSafe(await shown("میانگین مدت اجرای تکمیل‌شده") === durationText, "runtime_metric_duration_not_exact");
  requireSafe(overview.metrics.delivery_failures_by_platform && typeof overview.metrics.delivery_failures_by_platform === "object", "runtime_metric_delivery_missing");
  for (const [platform, label] of [["telegram", "تلگرام"], ["bale", "بله"]]) {
    const value = overview.metrics.delivery_failures_by_platform[platform] ?? 0;
    requireSafe(Number.isFinite(value) && value >= 0 && await shown(label) === value.toLocaleString("fa-IR"), "runtime_metric_delivery_not_exact");
  }
  const groups = overview.active_groups;
  requireSafe(Array.isArray(groups) && groups.length <= 100 && typeof overview.active_groups_has_more === "boolean", "runtime_active_groups_invalid");
  const panel = page.locator("section").filter({ has: page.getByRole("heading", { name: "اجراهای فعال بر اساس فرایند و انتشار", exact: true }) });
  requireSafe(await panel.locator("li").count() === groups.length, "runtime_active_groups_not_exact");
  for (const [index, group] of groups.entries()) {
    const row = panel.locator("li").nth(index);
    for (const [label, expected] of [["فرایند", group.workflow_id], ["انتشار", group.publication_id], ["نسخه", group.revision.toLocaleString("fa-IR")], ["تعداد اجرای فعال", group.active_runs.toLocaleString("fa-IR")]]) {
      requireSafe(await row.locator("dl > div").filter({ has: page.getByText(label, { exact: true }) }).locator("dd").innerText() === expected, "runtime_active_group_metadata_not_exact");
    }
    const query = new URLSearchParams({ tab: "runs", workflow_id: group.workflow_id, publication_id: group.publication_id });
    requireSafe(await row.getByRole("link", { name: "اجراهای این فرایند و انتشار", exact: true }).getAttribute("href") === `/studio/runtime?${query}`, "runtime_active_group_filter_not_exact");
  }
  if (!groups.length) requireSafe((await panel.innerText()).includes("اجرای فعالی در این گروه‌بندی وجود ندارد"), "runtime_active_groups_empty_missing");
  requireSafe((await panel.innerText()).includes("فقط ۱۰۰ گروه اول") === overview.active_groups_has_more, "runtime_active_groups_truncation_not_exact");
}

/** Privacy is verified before any image is written; account/login are excluded. */
async function capture(session, name) {
  const page = session.page;
  requireSafe(session.loggedIn && new URL(page.url()).pathname.startsWith("/studio/runtime"), "credential_capture_forbidden");
  requireSafe(await page.locator('input[type="password"]').count() === 0, "password_capture_forbidden");
  assertPrivate(await page.content());
  const textNodes = await page.locator("main").evaluate((main) => {
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    const values = [];
    while (walker.nextNode()) values.push(walker.currentNode.textContent.trim());
    return values;
  });
  assertPrivate(textNodes);
  const metrics = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    rtl: document.documentElement.dir,
    dark: document.documentElement.classList.contains("dark"),
  }));
  requireSafe(metrics.rtl === "rtl", "runtime_not_rtl");
  requireSafe(metrics.document <= metrics.viewport + 1 && metrics.body <= metrics.viewport + 1, "runtime_horizontal_overflow");
  await page.screenshot({
    path: `${output}/${name}.png`,
    animations: "disabled",
    mask: session.username ? [page.getByText(session.username, { exact: true })] : [],
  });
  writeFileSync(`${output}/${name}.json`, JSON.stringify(metrics, null, 2), { mode: 0o600 });
  evidence.screenshots.push({ name: name + ".png", ...metrics });
  persist();
}

function gateRow(page, title) {
  return page.locator("div.rounded-lg.border.p-4").filter({ has: page.getByRole("heading", { level: 3, name: title, exact: true }) });
}
async function currentGate(session, botId) {
  const overview = await bff(session, "/api/admin/workflow-runtime");
  return overview.gates.find((gate) => gate.bot_id === botId) ?? { version: 0, enabled: false, killed: false };
}
async function setOwnGate(session, changes) {
  const gate = await currentGate(session, fixture.bot_id);
  if (Object.entries(changes).every(([key, value]) => gate[key] === value)) return gate;
  if (session === admin && Date.now() - session.freshAt > 4 * 60 * 1000) await reauthenticate();
  return bff(session, "/api/admin/workflow-runtime/gates", {
    method: "POST",
    body: { bot_id: fixture.bot_id, expected_version: gate.version, enabled: gate.enabled, killed: gate.killed, ...changes, operation_id: randomUUID() },
  });
}
const countWrites = (path) => mutationRequests.filter((request) => request.path === path).length;

/** Wait for exactly one deliberate UI mutation and inspect its real response. */
async function uiMutation(page, path, click) {
  const result = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await click();
  const response = await result;
  requireSafe(response.status() === 200, "ui_mutation_rejected");
  const value = await response.json();
  assertPrivate(value);
  return value;
}

/** Start from a named saved revision; publication controls remain the real UI. */
async function loadPublicationSource(record) {
  const page = await open(admin, `/studio/runtime?tab=publications&workflow_id=${record.id}`);
  await page.getByLabel("جستجوی فرایند", { exact: true }).fill(record.name);
  const listed = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/admin/workflows" && response.request().method() === "GET");
  await page.getByRole("button", { name: "جستجو", exact: true }).click();
  await listed;
  await page.getByRole("combobox", { name: "فرایند برای انتشار", exact: true }).selectOption(record.id);
  await page.getByRole("button", { name: "ساخت پیش‌نمایش انتشار", exact: true }).waitFor();
  // Accessible labels include the Bot, platform and exact declared entry.
  const label = page.locator("label").filter({ hasText: `command:${record.definition.entry_points[0].key} → start` }).filter({ hasText: fixture.bot_name });
  await label.getByRole("checkbox").check();
  requireSafe(await label.count() === 1, "publication_entry_not_exact");
  return page;
}

async function approveSelectedPublication(page, record, screenshot) {
  const activates = countWrites("/api/admin/workflow-runtime/publications/activate");
  const preview = await uiMutation(page, "/api/admin/workflow-runtime/publications/preview", () => page.getByRole("button", { name: "ساخت پیش‌نمایش انتشار", exact: true }).click());
  requireSafe(preview.ready === true && uuid.test(preview.preview_id), "publication_preview_not_ready");
  requireSafe(preview.diff.next_revision === record.revision, "publication_revision_not_exact");
  requireSafe(preview.diff.next_bindings.length === 1 && preview.diff.next_bindings[0].bot_id === fixture.bot_id && preview.diff.next_bindings[0].key === record.definition.entry_points[0].key, "publication_scope_not_exact");
  requireSafe(preview.dependencies.some((dep) => dep.key === "wholesale.create_application" && dep.version === "1.0.0"), "publication_action_dependency_missing");
  const activate = page.getByRole("button", { name: "تأیید و فعال‌سازی همین پیش‌نمایش", exact: true });
  await activate.waitFor();
  requireSafe(await activate.isDisabled(), "publication_approved_implicitly");
  requireSafe(countWrites("/api/admin/workflow-runtime/publications/activate") === activates, "publication_activated_before_approval");
  const section = page.getByRole("region", { name: "پیش‌نمایش انتشار", exact: true });
  await section.getByRole("checkbox").check();
  await capture(admin, screenshot);
  const receipt = await uiMutation(page, "/api/admin/workflow-runtime/publications/activate", () => activate.click());
  const request = mutationRequests.filter((item) => item.path === "/api/admin/workflow-runtime/publications/activate").at(-1);
  requireSafe(request?.payload.preview_id === preview.preview_id && request.payload.approved === true, "activation_intent_not_exact");
  requireSafe(receipt.preview_id === preview.preview_id && receipt.revision === record.revision && uuid.test(receipt.publication_id), "activation_receipt_not_exact");
  requireSafe(countWrites("/api/admin/workflow-runtime/publications/activate") === activates + 1, "activation_replayed");
  return receipt.publication_id;
}

/** Corrupt a real committed response, then withhold only its audit projection. */
async function uncertainGate(mode) {
  await setOwnGate(admin, { enabled: false, killed: true });
  const page = await open(admin, "/studio/runtime?tab=overview");
  const row = gateRow(page, fixture.bot_name);
  await row.getByRole("checkbox", { name: "توقف اضطراری و بازگشت مسیریابی به Legacy", exact: true }).uncheck();
  await row.getByRole("checkbox", { name: "تغییر مجوز همین محدوده را تأیید می‌کنم.", exact: true }).check();
  const path = "/api/admin/workflow-runtime/gates";
  const before = countWrites(path);
  let intent;
  let intercepted = 0;
  const routeHandler = async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    intent = route.request().postDataJSON();
    requireSafe(intent.bot_id === fixture.bot_id && intent.enabled === false, "fault_injection_wrong_scope");
    intercepted++;
    const response = await route.fetch();
    requireSafe(response.status() === 200, "real_fault_write_failed");
    const receipt = await response.json();
    requireSafe(receipt.operation_id === intent.operation_id, "real_fault_receipt_mismatch");
    await route.fulfill({ response, json: mode === "empty" ? {} : { ...receipt, operation_id: randomUUID() } });
  };
  const historyHandler = async (route) => {
    const response = await route.fetch();
    requireSafe(response.status() === 200, "real_history_unavailable");
    const history = await response.json();
    requireSafe(history.items.some((item) => item.id === intent.operation_id), "committed_audit_missing");
    const items = history.items.filter((item) => item.id !== intent.operation_id);
    requireSafe(items.some((item) => item.action === "gate" && item.target_id === `bot:${fixture.bot_id}`), "unrelated_real_audit_missing");
    await route.fulfill({ response, json: { ...history, items } });
  };
  await admin.context.route(base + path, routeHandler);
  try {
    await row.getByRole("button", { name: "ثبت تنظیم اجرا", exact: true }).click();
    await row.getByRole("button", { name: "بررسی نتیجه در تاریخچه", exact: true }).waitFor();
    requireSafe((await row.getByRole("alert").innerText()).includes("نامعلوم"), "malformed_receipt_not_unknown");
    requireSafe(await row.getByRole("button", { name: "ثبت تنظیم اجرا", exact: true }).isDisabled(), "unknown_write_not_locked");
    requireSafe(intercepted === 1 && countWrites(path) === before + 1, "unknown_write_replayed");
    await capture(admin, `unknown-${mode}`);
    await admin.context.route(base + "/api/admin/workflow-runtime/history", historyHandler);
    try {
      await row.getByRole("button", { name: "بررسی نتیجه در تاریخچه", exact: true }).click();
      await row.getByText("در آخرین صفحهٔ تاریخچه نتیجهٔ قطعی پیدا نشد.", { exact: false }).waitFor();
      // A completed RSC refresh must not erase a frozen unknown operation.
      await page.waitForLoadState("networkidle");
      requireSafe(await row.getByRole("button", { name: "بررسی نتیجه در تاریخچه", exact: true }).isVisible(), "unmatched_audit_lost_unknown_state");
      requireSafe(await row.getByRole("button", { name: "ثبت تنظیم اجرا", exact: true }).isDisabled(), "unmatched_audit_unlocked_write");
      requireSafe(countWrites(path) === before + 1, "history_inspection_replayed_write");
    } finally {
      await admin.context.unroute(base + "/api/admin/workflow-runtime/history", historyHandler);
    }
    const exactHistory = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/admin/workflow-runtime/history");
    await row.getByRole("button", { name: "بررسی نتیجه در تاریخچه", exact: true }).click();
    const audit = await (await exactHistory).json();
    requireSafe(audit.items.some((item) => item.id === intent.operation_id && item.action === "gate" && item.target_id === `bot:${fixture.bot_id}`), "exact_audit_not_observed");
    await page.waitForLoadState("networkidle");
    requireSafe(await row.getByRole("alert").count() === 0 && await row.getByRole("button", { name: "بررسی نتیجه در تاریخچه", exact: true }).count() === 0, "exact_audit_did_not_resolve_unknown");
    requireSafe(countWrites(path) === before + 1 && intercepted === 1, "exact_audit_replayed_write");
    requireSafe((await currentGate(admin, fixture.bot_id)).killed === false, "committed_gate_not_observed");
  } finally {
    await admin.context.unroute(base + path, routeHandler);
  }
}

/** Read only this context's normal cookie, without exposing it to page scripts. */
async function ownSessionToken(session) {
  const cookie = (await session.context.cookies(base)).find((item) => ["shop_admin_dev", "__Host-shop_admin"].includes(item.name));
  requireSafe(cookie, "browser_session_cookie_missing");
  const claims = JSON.parse(Buffer.from(cookie.value.split(".")[0], "base64url").toString("utf8"));
  requireSafe(/^[A-Za-z0-9_-]{43}$/.test(claims.sid), "browser_session_cookie_invalid");
  rememberPrivate(claims.sid);
  return claims.sid;
}

/** Age only this runner's real session so the ordinary reauth route is tested. */
async function expireOwnFreshAuthentication() {
  const token = await ownSessionToken(admin);
  docker(`import hashlib
from datetime import timedelta
from sqlalchemy import select
from scripts.beta_storefront_e2e import MANIFEST,session_maker,security,engine
from models.shop_admin_control import AdminSession
async def main():
 async with session_maker() as db:
  row=await db.scalar(select(AdminSession).where(AdminSession.token_hash==hashlib.sha256(data["token"].encode()).hexdigest()).with_for_update())
  assert row and row.staff_id==json.loads(MANIFEST.read_text())["admin_id"] and row.revoked_at is None
  row.reauthenticated_at=security.clock()-timedelta(minutes=6)
  await db.commit()
 await engine.dispose()
 print("ok")
asyncio.run(main())`, { token });
}

async function reauthenticate() {
  const page = await open(admin, "/account");
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "تأیید هویت برای پنج دقیقه", exact: true }) });
  await form.getByLabel("رمز فعلی", { exact: true }).fill(env.LIVE_ADMIN_PASSWORD);
  await form.getByLabel("کد احراز هویت یا بازیابی", { exact: true }).fill(await freshOtp());
  await form.getByRole("button", { name: "تأیید هویت برای پنج دقیقه", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "عملیات ثبت شد و وضعیت حساب به‌روز شد." }).waitFor();
  admin.freshAt = Date.now();
  await open(admin, "/studio/runtime?tab=overview");
}

/** Create a suspended input Run through real ingress; no sender is started. */
function createSuspendedRun() {
  const canary = "runtime_browser_private_" + randomBytes(12).toString("hex");
  rememberPrivate(canary);
  return JSON.parse(docker(`from sqlalchemy import select
from scripts.workflow_runtime_e2e import NetworkFence,FakeTelegram
from scripts.beta_storefront_e2e import session_maker,engine
from services.shop_bot_context import resolve_bot_context
from services.shop_runtime import ingress
from models.shop_workflow_runtime import WorkflowRun
from channels.contracts import Platform
async def main():
 async with session_maker() as db:
  context=await resolve_bot_context(db,authenticated_bot_id=data["bot_id"],authenticated_platform=Platform.TELEGRAM,authenticated_provider_bot_id=None)
 user_id=int(data["user_id"])
 for index,value in enumerate(["/"+data["entry_key"],data["canary"],"/cart"]):
  payload={"update_id":user_id+index,"message":{"message_id":user_id+index,"date":0,"chat":{"id":user_id,"type":"private"},"from":{"id":user_id,"is_bot":False,"first_name":"Synthetic browser fixture"},"text":value}}
  await ingress.try_ingress(context,payload,client=FakeTelegram())
 async with session_maker() as db:
  run=await db.scalar(select(WorkflowRun).where(WorkflowRun.bot_id==data["bot_id"],WorkflowRun.user_id==user_id))
  assert run and run.status=="suspended" and run.values.get("name")==data["canary"]
  print(json.dumps({"run_id":run.id,"lock_version":run.lock_version}))
 await engine.dispose()
with NetworkFence().install():
 asyncio.run(main())`, { bot_id: fixture.bot_id, user_id: 700000000000 + Math.floor(Math.random() * 1000000000), entry_key: browserWorkflow.definition.entry_points[0].key, canary }));
}

/** Normal logout revokes backend state; closing a context alone is insufficient. */
async function logout(session) {
  if (!session) return;
  if (!session.loggedIn) {
    const cookies = await session.context.cookies(base);
    if (!cookies.some((item) => ["shop_admin_dev", "__Host-shop_admin"].includes(item.name))) return;
    session.backendToken = await ownSessionToken(session);
    session.loggedIn = true;
    await open(session, "/studio/runtime");
  }
  let page = session.page;
  if (!page || page.isClosed()) {
    page = await session.context.newPage();
    session.page = page;
    await page.goto(base + "/studio/runtime");
  }
  // The responsive sweep ends at 390px with the navigation drawer closed.
  // Restore the supported desktop navigation before using its normal control.
  session.viewport = { width: 1100, height: 1000 };
  await page.setViewportSize(session.viewport);
  if (new URL(page.url()).pathname === "/login") {
    // Prove the cookie cannot perform an authenticated read after expiry.
    await bff(session, "/api/admin/workflow-runtime", { status: 401 });
  } else {
    await ready(page);
    const control = page.getByRole("button", { name: "خروج امن", exact: true });
    await control.waitFor({ state: "visible" });
    await control.click();
    await page.waitForURL("**/login");
    await bff(session, "/api/admin/workflow-runtime", { status: 401 });
  }
  if (session.backendToken) docker(`import hashlib
from sqlalchemy import select
from scripts.beta_storefront_e2e import session_maker,engine
from models.shop_admin_control import AdminSession
async def main():
 async with session_maker() as db:
  row=await db.scalar(select(AdminSession).where(AdminSession.token_hash==hashlib.sha256(data["token"].encode()).hexdigest()))
  assert row is not None and row.revoked_at is not None
 await engine.dispose()
 print("ok")
asyncio.run(main())`, { token: session.backendToken });
  session.loggedIn = false;
}

try {
  const initialized = await check(checks[0], async () => {
    requireRuntimeCompose();
    const tools = await nextRpc("tools/list", {});
    for (const name of ["get_errors", "get_compilation_issues"]) {
      const tool = tools.tools?.find((item) => item.name === name);
      requireSafe(tool?.inputSchema?.type === "object" && !tool.inputSchema.required?.length, "next_tool_schema_unsupported");
    }
    assertNextClean(await nextTool("get_compilation_issues"), "get_compilation_issues");
    const metadata = await nextTool("get_project_metadata");
    requireSafe(JSON.stringify(metadata).includes(realpathSync("dashboard-next")), "wrong_next_checkout");
    fixture = bootstrapFixtures();
    requireSafe(uuid.test(fixture.fixture.workflow_id) && uuid.test(fixture.bot_id), "runtime_fixture_invalid");
    protectedBefore = protectedSnapshot();
    evidence.fixtures = { ...fixture.fixture, browser_bot_id: fixture.bot_id, viewer_store_id: fixture.viewer_store_id };
    const modulePath = process.env.WORKFLOW_PLAYWRIGHT_MODULE;
    requireSafe(modulePath && /playwright-core\/index\.mjs$/.test(realpathSync(modulePath)), "playwright_module_missing");
    const { chromium } = await import(pathToFileURL(realpathSync(modulePath)).href);
    browser = await chromium.launch({ headless: true, channel: "chromium", args: ["--disable-background-networking", "--disable-component-update", "--disable-domain-reliability", "--disable-sync", "--no-first-run"] });
    admin = await newSession(browser);
    viewer = await newSession(browser);
  });
  requireSafe(initialized, "runtime_browser_bootstrap_failed");
  const authenticated = await check(checks[1], async () => {
    await login(admin, "shopadmin", env.LIVE_ADMIN_PASSWORD, true);
    await chooseStore(admin, fixture.store_names[fixture.fixture.store_id]);
    await open(admin, "/studio/runtime");
    const overview = await bff(admin, "/api/admin/workflow-runtime");
    requireSafe(overview.global_enabled && !overview.global_killed && overview.can_manage && overview.can_publish, "wrong_runtime_bridge_or_capability");
    requireSafe(overview.gates.some((gate) => gate.scope_key === `store:${fixture.fixture.store_id}` && gate.enabled), "runtime_store_gate_missing");
  });
  requireSafe(authenticated, "normal_runtime_login_failed");

  await check(checks[2], async () => {
    for (const tab of ["overview", "publications", "bindings", "runs", "outbox", "history"]) {
      const page = await open(admin, "/studio/runtime?tab=" + tab);
      requireSafe(await page.getByRole("navigation", { name: "بخش‌های Runtime", exact: true }).getByRole("link").count() === 6, "runtime_tabs_missing");
      if (tab === "overview") await assertOperationalOverview(page, await bff(admin, "/api/admin/workflow-runtime"));
      await capture(admin, "initial-" + tab);
    }
    for (const platform of ["telegram", "bale"]) {
      const ref = fixture.fixture.runs.find((run) => run.platform === platform);
      requireSafe(ref, "platform_run_fixture_missing");
      const detail = await bff(admin, `/api/admin/workflow-runtime/runs/${ref.run_id}`);
      requireSafe(detail.variables.every((variable) => variable.value === "[private]"), "variable_projection_not_private");
      const page = await open(admin, `/studio/runtime/runs/${ref.run_id}`);
      await page.getByRole("heading", { name: "جزئیات اجرا", exact: true }).waitFor();
      await page.getByRole("heading", { name: "متغیرها", exact: true }).waitFor();
      requireSafe((await page.locator("main").innerText()).includes(ref.run_id), "wrong_run_detail");
      await capture(admin, "private-run-" + platform);
    }
  });

  await check(checks[3], async () => {
    // Unknown physical outcomes are quarantined as dead letters. Select the
    // actual current PostgreSQL fixture rather than inventing a queue state.
    const rows = await bff(admin, "/api/admin/workflow-runtime/outbox?status=dead_letter");
    const fixtureRuns = new Set(fixture.fixture.runs.map((run) => run.run_id));
    const item = rows.items.find((row) => fixtureRuns.has(row.run_id) &&
      row.status === "dead_letter" && row.error_code === "runtime_delivery_unknown");
    requireSafe(item, "uncertain_fixture_missing");
    requireSafe(item.can_retry === false, "uncertain_server_offers_retry");
    const page = await open(admin, "/studio/runtime?tab=outbox&status=dead_letter");
    const article = page.locator("article").filter({ has: page.getByText(item.id, { exact: true }) });
    requireSafe(await article.getByRole("button", { name: "ثبت تلاش مجدد ارسال", exact: true }).count() === 0, "uncertain_ui_offers_retry");
    await article.getByText("نتیجه هنوز قطعی نیست؛ ارسال دوباره ارائه نمی‌شود.", { exact: true }).waitFor();
    const denied = await bff(admin, `/api/admin/workflow-runtime/outbox/${item.id}/retry`, { method: "POST", status: 409, body: { expected_attempts: item.attempts, operation_id: randomUUID() } });
    requireSafe(denied.code === "runtime_delivery_replay_forbidden", "uncertain_retry_not_denied");
    await capture(admin, "uncertain-no-retry");
  });

  await check(checks[4], async () => {
    await login(viewer, fixture.username, fixture.password);
    await chooseStore(viewer, fixture.viewer_store_name);
    let page = await open(viewer, "/studio/runtime?tab=overview");
    const overview = await bff(viewer, "/api/admin/workflow-runtime");
    requireSafe(!overview.can_manage && !overview.can_publish && overview.gates.length === 0, "viewer_or_absent_gate_not_real");
    const row = gateRow(page, "فروشگاه جاری");
    await row.getByText("غیرفعال", { exact: true }).waitFor();
    requireSafe((await row.innerText()).includes("۰"), "absent_gate_version_not_zero");
    requireSafe(await page.locator("main input[type=checkbox]").count() === 0 && await page.getByRole("button", { name: "ثبت تنظیم اجرا", exact: true }).count() === 0, "readonly_gate_controls_present");
    await capture(viewer, "readonly-default-absent-store");
    const result = await bff(viewer, "/api/admin/workflow-runtime/gates", { method: "POST", status: 403, body: { bot_id: null, expected_version: 0, enabled: true, killed: false, operation_id: randomUUID() } });
    requireSafe(result.code === "permission_denied", "viewer_write_not_denied");
    await chooseStore(viewer, fixture.store_names[fixture.fixture.store_id]);
    page = await open(viewer, `/studio/runtime/runs/${fixture.fixture.runs[0].run_id}`);
    requireSafe(await page.getByRole("combobox", { name: "عملیات بازیابی", exact: true }).count() === 0, "viewer_recovery_control_present");
    await page.getByText("دسترسی مدیریت Runtime برای بازیابی لازم است.", { exact: true }).waitFor();
    page = await open(viewer, "/studio/runtime?tab=publications");
    requireSafe(await page.getByRole("combobox", { name: "فرایند برای انتشار", exact: true }).count() === 0, "viewer_publication_control_present");
  });

  await check(checks[5], async () => {
    for (const path of ["/gates", "/%2e%2e%2fstaff", "/runs/not-a-uuid", "?unknown=1", "/runs?page=1&page=2", "/runs?url=https%3A%2F%2Fexample.invalid"]) {
      await bff(admin, "/api/admin/workflow-runtime" + path, { status: 404 });
    }
    const gate = { bot_id: fixture.bot_id, expected_version: 0, enabled: false, killed: false, operation_id: randomUUID() };
    await bff(admin, "/api/admin/workflow-runtime/gates", { method: "POST", body: gate, challenge: false, status: 403 });
    await bff(admin, "/api/admin/workflow-runtime/gates", { method: "POST", body: gate, headers: { "sec-fetch-site": "cross-site", Origin: "https://hostile.invalid" }, status: 403 });
    await bff(admin, "/api/admin/workflow-runtime/gates", { method: "POST", raw: "[]", status: 422 });
    await bff(admin, "/api/admin/workflow-runtime/gates", { method: "POST", raw: "{}", headers: { "Content-Type": "text/plain" }, status: 415 });
    await bff(admin, "/api/admin/workflow-runtime/gates", { method: "POST", raw: JSON.stringify({ overflow: "x".repeat(262144) }), status: 413 });
    try {
      await chooseStore(admin, fixture.store_names[fixture.fixture.foreign_store_id]);
      await open(admin, "/studio/runtime");
      await bff(admin, `/api/admin/workflow-runtime/runs/${fixture.fixture.runs[0].run_id}`, { status: 404 });
      await bff(admin, "/api/admin/workflow-runtime/gates", { method: "POST", body: gate, status: 404 });
    } finally {
      await chooseStore(admin, fixture.store_names[fixture.fixture.store_id]);
      await open(admin, "/studio/runtime");
    }
  });

  const published = await check(checks[6], async () => {
    const id = randomUUID();
    const key = "browser_runtime_" + randomBytes(8).toString("hex");
    const created = await bff(admin, "/api/admin/workflows", { method: "POST", status: 201, body: { id, operation_id: randomUUID(), key, name: "آزمون اختصاصی انتشار Runtime مرورگر " + key.slice(-8), description: "Disposable provider-free browser acceptance", template: "wholesale_application" } });
    requireSafe(created.id === id && created.revision === 1, "browser_draft_not_created");
    const definition = structuredClone(created.definition);
    definition.assignment = { mode: "selected", bot_ids: [fixture.bot_id] };
    // This UI publication owns a Telegram-only synthetic Bot. The separate
    // PostgreSQL flow and Run-detail checks still cover both messengers.
    definition.target_platforms = ["telegram"];
    definition.entry_points.forEach((entry) => { entry.key = key; if (entry.kind === "command") entry.command = key; });
    browserWorkflow = await bff(admin, `/api/admin/workflows/${id}`, { method: "PATCH", body: { operation_id: randomUUID(), expected_revision: created.revision, name: created.name, description: created.description, definition, layout: created.layout } });
    evidence.fixtures.browser_workflow_id = id;
    firstPublication = await approveSelectedPublication(await loadPublicationSource(browserWorkflow), browserWorkflow, "exact-publication-preview");
    evidence.fixtures.browser_first_publication_id = firstPublication;
    finalPublication = firstPublication;
  });
  if (published) await check(checks[7], async () => {
    const previous = structuredClone(browserWorkflow);
    const definition = structuredClone(previous.definition);
    definition.nodes.find((node) => node.id === "name").config.prompt += " نسخهٔ آزمایشی دوم";
    browserWorkflow = await bff(admin, `/api/admin/workflows/${previous.id}`, { method: "PATCH", body: { operation_id: randomUUID(), expected_revision: previous.revision, name: previous.name, description: previous.description, definition, layout: previous.layout } });
    const next = await approveSelectedPublication(await loadPublicationSource(browserWorkflow), browserWorkflow, "new-publication-preview");
    requireSafe(next !== firstPublication, "new_publication_not_immutable");
    const page = await open(admin, `/studio/runtime?tab=publications&workflow_id=${previous.id}`);
    const article = page.locator("article").filter({ has: page.getByText(firstPublication, { exact: true }) });
    await article.getByRole("button", { name: "بررسی بازگشت به این نسخه", exact: true }).click();
    await page.getByRole("button", { name: "ساخت پیش‌نمایش انتشار", exact: true }).waitFor();
    finalPublication = await approveSelectedPublication(page, previous, "rollback-preview");
    requireSafe(finalPublication === firstPublication, "rollback_did_not_select_original_snapshot");
    const bindings = await bff(admin, "/api/admin/workflow-runtime/bindings");
    requireSafe(bindings.items.some((binding) => binding.workflow_id === previous.id && binding.bot_id === fixture.bot_id && binding.publication_id === firstPublication && binding.key === previous.definition.entry_points[0].key), "rollback_binding_not_exact");
    evidence.fixtures.browser_new_publication_id = next;
    evidence.fixtures.browser_final_publication_id = finalPublication;
    requireSafe(JSON.stringify(protectedSnapshot()) === JSON.stringify(protectedBefore), "pinned_fixture_changed_by_rollback");
  });

  await check(checks[8], async () => {
    await expireOwnFreshAuthentication();
    const page = await open(admin, "/studio/runtime?tab=overview");
    const row = gateRow(page, fixture.bot_name);
    const existing = await currentGate(admin, fixture.bot_id);
    await row.getByRole("checkbox", { name: "توقف اضطراری و بازگشت مسیریابی به Legacy", exact: true }).setChecked(!existing.killed);
    await row.getByRole("checkbox", { name: "تغییر مجوز همین محدوده را تأیید می‌کنم.", exact: true }).check();
    expectedUiFailures.add("/api/admin/workflow-runtime/gates");
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/admin/workflow-runtime/gates" && response.request().method() === "POST");
    await row.getByRole("button", { name: "ثبت تنظیم اجرا", exact: true }).click();
    const response = await responsePromise;
    requireSafe(response.status() === 403 && (await response.json()).code === "reauthentication_required", "stale_auth_not_denied");
    await row.getByRole("link", { name: "تأیید دوبارهٔ هویت در حساب من", exact: true }).waitFor();
    requireSafe((await currentGate(admin, fixture.bot_id)).version === existing.version, "stale_auth_changed_gate");
    await capture(admin, "fresh-auth-required");
    await reauthenticate();
    await setOwnGate(admin, { enabled: false, killed: false });
  });

  await check(checks[9], () => uncertainGate("empty"));
  await check(checks[10], () => uncertainGate("mismatched"));

  if (published) await check(checks[11], async () => {
    await setOwnGate(admin, { enabled: true, killed: false });
    const created = createSuspendedRun();
    browserRunId = created.run_id;
    evidence.fixtures.browser_recovery_run_id = browserRunId;
    const original = await bff(admin, `/api/admin/workflow-runtime/runs/${browserRunId}`);
    requireSafe(original.status === "suspended", "browser_run_not_suspended");
    await bff(viewer, `/api/admin/workflow-runtime/runs/${browserRunId}/recover`, { method: "POST", status: 403, body: { expected_version: original.lock_version, operation: "resume", operation_id: randomUUID() } });
    const page = await open(admin, `/studio/runtime/runs/${browserRunId}`);
    await page.getByRole("combobox", { name: "عملیات بازیابی", exact: true }).selectOption("resume");
    const recover = page.getByRole("button", { name: "ادامهٔ اجرای متوقف‌شده", exact: true });
    requireSafe(await recover.isDisabled(), "recovery_missing_confirmation");
    await page.getByRole("checkbox", { name: "ادامهٔ اجرای متوقف‌شده را تأیید می‌کنم.", exact: true }).check();
    await capture(admin, "explicit-suspended-recovery");
    const receipt = await uiMutation(page, `/api/admin/workflow-runtime/runs/${browserRunId}/recover`, () => recover.click());
    requireSafe(receipt.id === browserRunId && receipt.lock_version > original.lock_version, "recovery_receipt_not_exact");
    const restored = await bff(admin, `/api/admin/workflow-runtime/runs/${browserRunId}`);
    requireSafe(restored.status === "waiting_input" && restored.publication_id === original.publication_id && restored.node_id === original.node_id, "recovery_did_not_restore_pinned_input");
    await setOwnGate(admin, { enabled: false, killed: false });
  });

  await check(checks[12], async () => {
    const routes = ["overview", "publications", "bindings", "runs", "outbox", "history"].map((tab) => [tab, "/studio/runtime?tab=" + tab]);
    routes.push(["detail", `/studio/runtime/runs/${fixture.fixture.runs[0].run_id}`]);
    for (const [width, label] of [[1100, "desktop"], [390, "mobile390"]]) {
      admin.viewport = { width, height: 1000 };
      for (const dark of [false, true]) {
        for (const [name, path] of routes) {
          const page = await open(admin, path);
          if (await page.locator("html").evaluate((html) => html.classList.contains("dark")) !== dark)
            await page.getByRole("button", { name: "تغییر حالت روشن و تاریک", exact: true }).click();
          await page.waitForFunction((value) => document.documentElement.classList.contains("dark") === value, dark);
          await capture(admin, `${label}-${dark ? "dark" : "light"}-${name}`);
        }
      }
    }
  });

  await check(checks[13], async () => {
    await Promise.all([...responseChecks]);
    requireSafe(privacyFailures === 0, "private_runtime_response_exposed");
    requireSafe(pageErrors.length === 0, "browser_application_error");
    const unexpected = consoleErrors.filter((error) => !(error.resource && expectedUiFailures.has(error.path)));
    requireSafe(unexpected.length === 0, "browser_console_error");
    requireSafe(evidence.denied_browser_requests === 0, "browser_attempted_external_request");
    // Keep the final navigated page alive while Next queries its HMR session.
    await ready(admin.page);
    assertNextClean(await nextTool("get_compilation_issues"), "get_compilation_issues");
    assertNextClean(await nextTool("get_errors"), "get_errors");
    evidence.browser_error_counts = { page: pageErrors.length, unexpected_console: unexpected.length, private_response: privacyFailures };
  });
  await check(checks[14], async () => {
    requireSafe(JSON.stringify(protectedSnapshot()) === JSON.stringify(protectedBefore), "protected_pg_fixture_changed");
    // Browser-only Runtime remains off after the acceptance mutation scenarios.
    await setOwnGate(admin, { enabled: false, killed: false });
    const gate = await currentGate(admin, fixture.bot_id);
    requireSafe(gate.enabled === false && gate.killed === false, "disposable_bot_gate_not_disabled");
  });
} catch (error) {
  evidence.fatal = { stage, reason: error instanceof CheckFailure ? error.code : error.name || "Error" };
  console.error("FAIL  runtime browser stopped: " + evidence.fatal.reason);
} finally {
  if (admin || viewer) {
    await check(checks[15], async () => {
      const results = await Promise.allSettled([logout(viewer), logout(admin)]);
      requireSafe(results.every((result) => result.status === "fulfilled"), "normal_logout_failed");
    });
  }
  const closed = await Promise.allSettled([viewer?.context.close(), admin?.context.close()]);
  if (closed.some((result) => result.status === "rejected")) evidence.close_failed = true;
  if (browser) await browser.close().catch(() => { evidence.close_failed = true; });
  evidence.status = !evidence.fatal && !evidence.close_failed && evidence.checks.every((item) => item.status === "PASS") ? "PASS" : "FAIL";
  persist();
  console.log(evidence.status + "  Runtime browser evidence: " + evidencePath);
  if (evidence.status !== "PASS") process.exitCode = 1;
}
