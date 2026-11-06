/** Real MCP SDK, private HTTP, PostgreSQL and controlled human UI acceptance. */
import assert from "node:assert/strict";
import { createHash, createPrivateKey, randomBytes, randomUUID } from "node:crypto";
import { execFile, execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

const root = "/workspaces/wpmcp-bot-qa";
const compose = "compose.workflow-mcp-qa.yml";
const nativeOrigin = "http://127.0.0.1:3005";
const gatewayOrigin = "http://127.0.0.1:8096";
const output = "/tmp/workflow-mcp-gateway-" + randomUUID();
const env = Object.fromEntries(readFileSync(".codespaces/mcp-qa.env", "utf8").trim().split("\n")
  .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]));
assert.equal(env.SHOP_MCP_QA, "1");assert.equal(env.POSTGRES_DB, "shop_codespace");
assert.equal(env.SHOP_FASTAPI_INTERNAL_URL, "http://127.0.0.1:8095");
for (const key of ["TOKEN", "BALE_BOT_TOKEN", "BALE_WALLET_PROVIDER_TOKEN", "TELEGRAM_FIAT_PROVIDER_TOKEN"])
  assert.equal(env[key], "");
const manifest = JSON.parse(readFileSync("docs/qa/workflow-mcp/gateway-runtime-manifest.json", "utf8"));
for (const [path, expected] of Object.entries(manifest.files))
  assert.equal(createHash("sha256").update(readFileSync(root + "/" + path)).digest("hex"), expected, "gateway_checkpoint_mismatch");
mkdirSync(output, { recursive: true, mode: 0o700 });
const evidence = { status: "RUNNING", checks: [], database: "PostgreSQL", fake_providers_only: true, controlled_human_decisions: 0 };
const persist = () => writeFileSync(output + "/evidence.json", JSON.stringify(evidence, null, 2), { mode: 0o600 });
const load = (name) => import(pathToFileURL(root + "/apps/saas-gateway/dist/" + name + ".js").href);
const require = createRequire(root + "/apps/saas-gateway/package.json");
const { Client, Pool } = require("pg");
const controlUrl = new URL("postgresql://127.0.0.1:5485/shop_codespace");
controlUrl.username = env.POSTGRES_USER;controlUrl.password = env.POSTGRES_PASSWORD;
const databaseName = "aiwb_workflow_mcp_" + randomUUID().replaceAll("-", "");
const databaseUrl = new URL(controlUrl);databaseUrl.pathname = "/" + databaseName;
let control, owner, pool, app, browser, nativeContext, gatewayContext, nativePage, gatewayPage;
const workers = [];
let current = "bootstrap", connectionId, grantId, saved, category, graph, captured, searchQuery;
const installation = env.SHOP_MCP_INSTALLATION_ID;
const subject = "mcp-qa-requester", clientId = "aiwb-local-client", token = randomBytes(36).toString("base64url");
const workspaceId = randomUUID(), tenantId = randomUUID();
const { ProviderStore } = await load("provider-store");
const { BotWorkflowClient } = await load("bot-workflow-client");
const { BotWorkflowService } = await load("bot-workflow-tools");
const { BotWorkflowConnections } = await load("bot-workflow-connections");
const { ProviderDelegationSigner } = await load("provider-proof");
const { PostgresGatewayAdmission } = await load("gateway-admission");
const { PostgresUsageMeter } = await load("usage-meter");
const { DashboardRepository } = await load("dashboard-repository");
const { PostgresOperationStore } = await load("postgres-operation-store");
const { registerDashboardRoutes } = await load("dashboard-routes");
const { buildGatewayHttpApp, LocalTokenVerifier, MCP_PROTOCOL_VERSION, loadMigrationCatalog } = await load("index");

/** Only the named synthetic lab can run these fixed test helpers. */
function docker(code, data = {}) {
  const prelude = `import os,sys,json,asyncio
from scripts.test_lab_safety import require_isolated_lab
require_isolated_lab()
assert os.environ.get("SHOP_MCP_QA")=="1" and __debug__
data=json.loads(sys.stdin.read())
`;
  try { return execFileSync("docker", ["compose", "-f", compose, "exec", "-T", "api", "python", "-c", prelude + code],
    { input: JSON.stringify(data), encoding: "utf8", timeout: 120000, stdio: ["pipe", "pipe", "pipe"] }).trim(); }
  catch { throw new Error("guarded_lab_operation_failed"); }
}
const fixture = JSON.parse(docker('from pathlib import Path\nprint(Path("/qa/workflow-mcp-fixture.json").read_text())'));
async function check(name, run) {
  current = name;
  try { await run();evidence.checks.push({ name, status: "PASS" });console.log("PASS  " + name); }
  catch (error) { evidence.checks.push({ name, status: "FAIL", reason: error.code ?? error.name });throw error; }
  finally { persist(); }
}
let rpcId = 0;
async function rpc(method, params = {}, bearer = token) {
  const response = await fetch(gatewayOrigin + "/mcp", { method: "POST", headers: {
    "content-type": "application/json", Accept: "application/json, text/event-stream",
    "mcp-protocol-version": MCP_PROTOCOL_VERSION, "mcp-method": method,
    ...(params.name || params.uri ? { "mcp-name": params.name ?? params.uri } : {}), authorization: "Bearer " + bearer,
  }, body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method, params: { ...params, _meta: {
    "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": { name: "workflow-mcp-qa", version: "1.0.0" },
    "io.modelcontextprotocol/clientCapabilities": {},
  } } }), signal: AbortSignal.timeout(30000) });
  if (response.status === 401) return { unauthorized: true };
  assert.equal(response.status, 200);return (await response.json());
}
async function call(name, args = {}, expectError = false) {
  const response = await rpc("tools/call", { name: "bot." + name, arguments: { connection_id: connectionId, ...args } });
  if (expectError) { assert(response.error || response.result?.isError);return response; }
  if (response.error || response.result?.isError) {
    const error = new Error("mcp_call_rejected");error.code = response.result?.structuredContent?.code ?? response.error?.code ?? "MCP_ERROR";throw error;
  }
  return response.result.structuredContent.data;
}
async function freshOtp() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const result = JSON.parse(docker(`import time
from db import session_maker,engine
from models.shop_admin_control import AdminProfile
from services import shop_admin_security as security
async def main():
 async with session_maker() as db:
  row=await db.get(AdminProfile,data["admin_id"]);now=time.time()
  value={"wait":int((30-now%30)*1000)+150} if int(now//30)<=row.last_totp_step else {"proof":security.totp(security.cipher().decrypt(row.mfa_secret.encode()).decode(),now)}
  print(json.dumps(value))
 await engine.dispose()
asyncio.run(main())`, fixture));
    if (result.proof) return result.proof;
    await new Promise((resolve) => setTimeout(resolve, result.wait));
  }
  throw Error("fresh_mfa_unavailable");
}
const nativeArgs = (extra = {}) => ({ store_id: fixture.store_id, ...extra });
try {
  await check("separate real PostgreSQL database and restricted gateway role", async () => {
    control = new Client({ connectionString: controlUrl.href });await control.connect();
    assert.equal((await control.query("SELECT current_database() name")).rows[0].name, "shop_codespace");
    await control.query(`CREATE DATABASE ${databaseName}`);
    owner = new Client({ connectionString: databaseUrl.href });await owner.connect();
    await owner.query("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aiwb_app') THEN CREATE ROLE aiwb_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;END IF;END $$");
    for (const migration of await loadMigrationCatalog()) await owner.query(migration.sql);
    pool = new Pool({ connectionString: databaseUrl.href, max: 8, statement_timeout: 15000 });
    const appPool = { query: async (sql, args) => {
      const client = await pool.connect();try { await client.query("SET ROLE aiwb_app");return await client.query(sql, args); }
      finally { client.release(); }
    } };
    assert.equal((await appPool.query("SELECT current_user name")).rows[0].name, "aiwb_app");
    const dashboard = new DashboardRepository(appPool), user = await dashboard.createIdentity({ issuer: "urn:aiwb:local", subject, displayName: "MCP QA" });
    await owner.query("INSERT INTO aiwb.tenants(tenant_id,slug,display_name) VALUES($1,'mcp-qa','MCP QA')", [tenantId]);
    await owner.query("INSERT INTO aiwb.workspaces(workspace_id,tenant_id,slug,display_name) VALUES($1,$2,'workflow-qa','Workflow QA')", [workspaceId, tenantId]);
    await owner.query("INSERT INTO aiwb.memberships(tenant_id,workspace_id,user_id,role) VALUES($1,$2,$3,'owner')", [tenantId, workspaceId, user]);
    const privateKey = createPrivateKey({ format: "der", type: "pkcs8", key: Buffer.from(env.MCP_QA_DELEGATION_PRIVATE_KEY, "base64") });
    const native = new BotWorkflowClient({ endpoints: new Map([[installation, "http://127.0.0.1:8095"]]),
      studioOrigins: new Map([[installation, nativeOrigin]]), allowLoopbackHttp: true,
      delegation: new ProviderDelegationSigner({ issuer: env.SHOP_MCP_GATEWAY_ISSUER, keyId: "qa-delegation", privateKey }),
      fetcher: async (url, options) => { captured = { url, options };return fetch(url, options); },
    });
    const store = new ProviderStore(appPool), operations = new PostgresOperationStore(appPool);
    const service = new BotWorkflowService({ store, native, usage: new PostgresUsageMeter(appPool),
      admission: new PostgresGatewayAdmission(appPool), dashboardOrigin: gatewayOrigin });
    const resource = new URL(gatewayOrigin + "/mcp");
    app = buildGatewayHttpApp({ runtime: { connections: {}, botWorkflows: service, operations }, auth: {
      mode: "local", expectedResource: resource, requiredScopes: ["aiwb:read"], verifier: new LocalTokenVerifier(token, resource, subject),
    } });
    registerDashboardRoutes(app, { auth: { mode: "local", baseUrl: new URL(gatewayOrigin + "/dashboard"), sessionKey: randomBytes(32),
      secureCookies: false, sessionTtlSeconds: 3600, accessToken: token, subject }, repository: dashboard,
      connections: {}, operations, botWorkflows: service, botConnections: new BotWorkflowConnections({ store, native }) });
    await app.listen({ host: "127.0.0.1", port: 8096 });
  });
  const { chromium } = await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ headless: true, channel: "chromium", args: ["--no-sandbox"] });
  nativeContext = await browser.newContext();gatewayContext = await browser.newContext();
  for (const context of [nativeContext, gatewayContext]) await context.route("**/*", (route) =>
    [nativeOrigin, gatewayOrigin].includes(new URL(route.request().url()).origin) ? route.continue() : route.abort());
  nativePage = await nativeContext.newPage();gatewayPage = await gatewayContext.newPage();
  await check("normal independent Native MFA and gateway dashboard login", async () => {
    await nativePage.goto(nativeOrigin + "/studio/mcp");
    await nativePage.getByLabel("نام کاربری", { exact: true }).fill("shopadmin");
    await nativePage.getByLabel("رمز عبور", { exact: true }).fill(env.LIVE_ADMIN_PASSWORD);
    await nativePage.getByLabel("کد احراز هویت یا بازیابی (اگر فعال است)", { exact: true }).fill(await freshOtp());
    await nativePage.getByRole("button", { name: "ورود امن", exact: true }).click();await nativePage.waitForURL("**/dashboard");
    await gatewayPage.goto(gatewayOrigin + "/dashboard/login");await gatewayPage.getByLabel("توکن توسعه").fill(token);
    await gatewayPage.getByRole("button", { name: "ادامه", exact: true }).click();await gatewayPage.waitForURL(gatewayOrigin + "/dashboard");
  });
  await check("human enrollment verifies exact Native consent before activation", async () => {
    await gatewayPage.goto(gatewayOrigin + "/dashboard/bot-connections?workspace=" + workspaceId);
    await gatewayPage.locator('[name="display_name"]').fill("QA product inquiry");
    await gatewayPage.locator('[name="client_id"]').fill(clientId);
    await gatewayPage.locator('[name="store_ids"]').fill(fixture.store_id);
    for (const input of await gatewayPage.locator('input[type="checkbox"]').all()) await input.check();
    await gatewayPage.getByRole("button", { name: "ساخت درخواست همین اتصال", exact: true }).click();
    await gatewayPage.getByRole("heading", { name: "QA product inquiry", exact: true }).waitFor();
    connectionId = new URL(gatewayPage.url()).pathname.split("/").at(-1);
    const link = await gatewayPage.getByRole("link", { name: "بررسی همین درخواست در Native Studio", exact: true }).getAttribute("href");
    assert.equal(new URL(link).origin, nativeOrigin);grantId = new URL(link).searchParams.get("pairing");
    await nativePage.goto(link);await nativePage.getByRole("button", { name: "ثبت همین دسترسی اتصال", exact: true }).click();
    await nativePage.getByText("دسترسی همین اتصال ثبت شد. ادامهٔ اتصال را در WPMCP بررسی کنید.", { exact: true }).waitFor();
    await gatewayPage.getByRole("button", { name: "بررسی تأیید Native", exact: true }).click();
    await gatewayPage.getByText("اتصال در Gateway ثبت شده", { exact: true }).waitFor();
  });
  await check("authenticated MCP tool/resource/prompt and real catalog discovery", async () => {
    assert.equal((await rpc("tools/list", {}, "wrong-token")).unauthorized, true);
    const tools = (await rpc("tools/list")).result.tools;assert(tools.some((tool) => tool.name === "bot.workflow.prepare_publish"));
    assert(tools.some((tool) => tool.name === "site.inspect"));assert(!tools.some((tool) => /bot\..*(approve|execute_sql)/.test(tool.name)));
    assert((await rpc("resources/templates/list")).result.resourceTemplates.some((row) => row.name === "bot.node_catalog"));
    assert((await rpc("prompts/list")).result.prompts.some((row) => row.name === "bot.design_customer_workflow"));
    const catalog = await rpc("resources/read", { uri: `bot-workflows://${connectionId}/${fixture.store_id}/action_catalog` });
    assert.match(catalog.result.contents[0].text, /display_text/);
    const prompt = await rpc("prompts/get", { name: "bot.design_customer_workflow", arguments: {
      connection_id: connectionId, store_id: fixture.store_id, requirements: "Product inquiry with safe preview and human-reviewed publication",
    } });assert(prompt.result.messages.length > 0);
    const profile = await call("context.get_profile");assert.deepEqual(profile.store_ids, [fixture.store_id]);
    const stores = await call("context.list_stores");assert.deepEqual(stores.items.map((row) => row.id), [fixture.store_id]);
    const bots = await call("bots.list", nativeArgs());assert(bots.items.some((row) => row.id === fixture.bots.telegram));
    const actions = await call("actions.list", nativeArgs({ bot_id: fixture.bots.telegram }));
    assert(actions.items.some((row) => row.key === "catalog.search_products" && row.version === "2.0.0"));
    const categories = await call("catalog.list_categories", nativeArgs({ bot_id: fixture.bots.telegram }));category = categories.items[0];assert(category);
    const products = await call("catalog.search_products", nativeArgs({ bot_id: fixture.bots.telegram, category_id: category.id }));assert(products.items.length);
    searchQuery = products.items[0].name.slice(0, 10);
    evidence.discovered = { bot_tools: tools.filter((row) => row.name.startsWith("bot.")).length, catalog_products: products.items.length };
  });
  await check("private signature replay and foreign Store requests fail closed", async () => {
    const previous = captured;const response = await fetch(previous.url, previous.options);assert.equal(response.status, 409);
    await call("bots.list", { store_id: fixture.foreign_store_id }, true);
  });
  await check("official Inspector performs an authenticated native profile call", async () => {
    const result = await promisify(execFile)("/workspaces/beta-qa-tools/inspector/node_modules/.bin/mcp-inspector", [
      "--cli", gatewayOrigin + "/mcp", "--transport", "http", "--method", "tools/call",
      "--tool-name", "bot.context.get_profile", "--tool-arg", "connection_id=" + connectionId,
      "--header", "Authorization: Bearer " + token,
    ], { encoding: "utf8", timeout: 45000, maxBuffer: 4 * 1024 * 1024 });
    const value = JSON.parse(result.stdout);
    assert.equal((value.structuredContent ?? value.result?.structuredContent).data.native_staff_id, fixture.admin_id);
    evidence.inspector_version = readFileSync("/tmp/l4-inspector-version", "utf8").trim();
  });
  await check("MCP draft retry, altered retry and concurrent revision conflict", async () => {
    const create = nativeArgs({ id: randomUUID(), operation_id: randomUUID(), expected_revision: 0,
      key: "qa_inquiry_" + randomBytes(5).toString("hex"), name: "استعلام محصول", template: "blank" });
    saved = await call("workflow.create_draft", create);const replay = await call("workflow.create_draft", create);
    assert.equal(replay.id, saved.id);assert.equal(replay.revision, saved.revision);
    await call("workflow.create_draft", { ...create, name: "Changed retry" }, true);
    const base = saved.revision;
    const results = await Promise.all(["A", "B"].map((suffix) => rpc("tools/call", { name: "bot.workflow.update_metadata", arguments: {
      connection_id: connectionId, ...nativeArgs({ workflow_id: saved.id, expected_revision: base, operation_id: randomUUID(), name: "استعلام محصول " + suffix }),
    } })));
    assert.equal(results.filter((r) => !r.error && !r.result?.isError).length, 1);
    saved = await call("workflow.get", nativeArgs({ workflow_id: saved.id }));
  });
  await check("exact Change Set and product inquiry graph through real MCP", async () => {
    const nodes = [
      { id: "start", type: "start", config: {} },
      { id: "question", type: "ask_text", config: { prompt: "چه محصولی می‌خواهید؟", variable: "query", min_length: 2, max_length: 100 } },
      { id: "category", type: "ask_choice", config: { prompt: "دسته را انتخاب کنید.", variable: "category", choices: [{ key: "selected", label: category.name, value: category.id }] } },
      { id: "search", type: "action", config: { action_key: "catalog.search_products", action_version: "2.0.0", input_mapping: {
        query: { kind: "variable", name: "query" }, category_id: { kind: "variable", name: "category" }, page_size: { kind: "constant", value: 5 },
      }, output_mapping: { display_text: "results" } } },
      { id: "results", type: "send_text", config: { text: "{{results}}" } },
      { id: "phone", type: "ask_phone", config: { prompt: "Contact متعلق به خودتان را بفرستید.", variable: "phone", contact_only: true } },
      { id: "confirm", type: "confirm", config: { prompt: "پاسخ شما دریافت شد. استعلام را پایان می‌دهید؟", confirm_label: "پایان استعلام", cancel_label: "انصراف" } },
      { id: "end", type: "end", config: { message: "استعلام به پایان رسید." } },
      { id: "cancel", type: "cancel", config: { message: "استعلام لغو شد." } },
    ];
    graph = { schema_version: 1, target_platforms: ["telegram", "bale"], assignment: { mode: "selected", bot_ids: [fixture.bots.telegram, fixture.bots.bale] },
      entry_points: [{ kind: "command", key: "inquiry", command: "inquiry", node_id: "start" }], nodes,
      edges: [["start", "question", "next"], ["question", "category", "next"], ["category", "search", "next"], ["search", "results", "success"],
        ["search", "cancel", "error"], ["search", "cancel", "unavailable"], ["search", "cancel", "retry"], ["search", "cancel", "pending_approval"],
        ["results", "phone", "next"], ["phone", "confirm", "next"], ["confirm", "end", "confirm"], ["confirm", "cancel", "cancel"]]
        .map(([source, target, port], i) => ({ id: "edge_" + i, source, target, port })),
      variables: [{ name: "query", type: "string" }, { name: "category", type: "integer" }, { name: "results", type: "string" }, { name: "phone", type: "string" }],
    };
    const proposal = await call("changes.create", nativeArgs({ workflow_id: saved.id, expected_revision: saved.revision,
      id: randomUUID(), operation_id: randomUUID(), definition: graph }));
    assert.equal(proposal.status, "draft");assert.equal(proposal.proposal.definition.nodes.length, nodes.length);
    assert.notDeepEqual(proposal.base.definition, proposal.proposal.definition);
    await call("workflow.validate_change_set", nativeArgs({ change_set_id: proposal.id }));
    saved = await call("changes.apply", nativeArgs({ change_set_id: proposal.id, expected_version: proposal.version, operation_id: randomUUID() }));
    assert(!saved.requires_approval);
  });
  await check("Runtime incompatibility is rejected and corrected through typed MCP", async () => {
    const invalid = structuredClone(graph);invalid.nodes.find((node) => node.id === "category").config.choices_source = "simulation_products";
    saved = await call("workflow.replace_definition", nativeArgs({ workflow_id: saved.id, expected_revision: saved.revision,
      operation_id: randomUUID(), definition: invalid }));
    const bindings = ["telegram", "bale"].map((platform) => ({ bot_id: fixture.bots[platform], kind: "command", key: "inquiry", node_id: "start" }));
    const rejected = await call("workflow.prepare_publish", nativeArgs({ workflow_id: saved.id, expected_revision: saved.revision,
      revision: saved.revision, operation_id: randomUUID(), bindings }), true);
    assert.match(JSON.stringify(rejected), /runtime_publication_not_ready/);
    assert.equal((await owner.query("SELECT count(*)::int n FROM aiwb.gateway_approval_requests")).rows[0].n, 0);
    saved = await call("workflow.replace_definition", nativeArgs({ workflow_id: saved.id, expected_revision: saved.revision,
      operation_id: randomUUID(), definition: graph }));
    saved = await call("workflow.assign_bots", nativeArgs({ workflow_id: saved.id, expected_revision: saved.revision,
      operation_id: randomUUID(), assignment: graph.assignment }));
  });
  await check("saved inquiry simulates on Telegram and Bale without commerce effects", async () => {
    for (const platform of ["telegram", "bale"]) {
      const simulation = await call("workflow.simulate", nativeArgs({ workflow_id: saved.id, revision: saved.revision, platform, bot_id: fixture.bots[platform],
        events: [{ kind: "input", value: "محصول" }, { kind: "button", key: "selected" }, { kind: "input", value: "+989121234567" }, { kind: "button", key: "confirm" }] }));
      assert.equal(simulation.status, "completed");
    }
  });
  await check("one controlled gateway decision automatically publishes after a worker crash", async () => {
    const bindings = ["telegram", "bale"].map((platform) => ({ bot_id: fixture.bots[platform], kind: "command", key: "inquiry", node_id: "start" }));
    const prepared = await call("workflow.prepare_publish", nativeArgs({ workflow_id: saved.id, revision: saved.revision,
      expected_revision: saved.revision, operation_id: randomUUID(), bindings }));
    assert.equal(prepared.state, "PENDING_APPROVAL");
    const crashMarker = output + "/worker-crash.json";
    const configPath = output + "/worker-private.json";
    writeFileSync(configPath, JSON.stringify({ mode: "isolated_workflow_mcp_qa", gatewayRoot: root, database: databaseUrl.href,
      installation, issuer: env.SHOP_MCP_GATEWAY_ISSUER, delegation: env.MCP_QA_DELEGATION_PRIVATE_KEY, approval: env.MCP_QA_APPROVAL_PRIVATE_KEY, crashMarker }), { mode: 0o600 });
    for (let i = 0; i < 2; i++) workers.push(spawn(process.execPath, [new URL("./workflow_mcp_gateway_worker.mjs", import.meta.url).pathname, configPath], { stdio: "ignore" }));
    await gatewayPage.goto(gatewayOrigin + new URL(prepared.review_url).pathname + "?workspace=" + workspaceId);
    await gatewayPage.getByRole("button", { name: "بله، این درخواست را تأیید می‌کنم", exact: true }).click();evidence.controlled_human_decisions++;
    for (let i = 0; i < 200 && !existsSync(crashMarker); i++) await new Promise((resolve) => setTimeout(resolve, 100));
    assert(existsSync(crashMarker));
    await owner.query("UPDATE aiwb.provider_operation_payloads SET claim_expires_at=clock_timestamp()-interval '1 second' WHERE operation_id=$1", [prepared.operation_id]);
    let status;
    for (let i = 0; i < 100; i++) {
      const result = await rpc("tools/call", { name: "bot.operations.status", arguments: { operation_id: prepared.operation_id } });
      status = result.result.structuredContent.data;if (status.state === "SUCCEEDED") break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(status.state, "SUCCEEDED");assert.equal(status.result_facts.reconciled, true);
    evidence.operation_id = prepared.operation_id;evidence.publication_id = status.result_facts.publication_id;evidence.workflow_id = saved.id;
    const decisions = await owner.query("SELECT count(*)::int n FROM aiwb.gateway_approval_requests WHERE decision='APPROVED'");assert.equal(decisions.rows[0].n, 1);
    const native = JSON.parse(docker(`from sqlalchemy import select,func
from db import session_maker,engine
from models.shop_workflow_runtime import PublishedWorkflow
async def main():
 async with session_maker() as db: print(json.dumps({"count":await db.scalar(select(func.count()).select_from(PublishedWorkflow).where(PublishedWorkflow.workflow_id==data["workflow_id"]))}))
 await engine.dispose()
asyncio.run(main())`, { workflow_id: saved.id }));assert.equal(native.count, 1);
  });
  await check("Fake Telegram/Bale Runtime consumes the actual published inquiry", async () => {
    const result = JSON.parse(docker(`from scripts.workflow_mcp_runtime_e2e import run
print(json.dumps(asyncio.run(run(data))))`, { workflow_id: saved.id, publication_id: evidence.publication_id,
      category: category.id, category_name: category.name, query: searchQuery }));
    assert.equal(result.status, "PASS");evidence.runtime = result;
  });
  await check("public Runtime inspection excludes customer answers", async () => {
    const runs = await call("runtime.list_runs", nativeArgs({ workflow_id: saved.id }));assert.equal(runs.items.length, 2);
    for (const run of runs.items) {
      const result = await call("runtime.get_run", nativeArgs({ run_id: run.id }));
      assert(!JSON.stringify(result).includes("QA_PRIVATE"));assert(!JSON.stringify(result).includes("+98912"));
    }
  });
  evidence.status = "PASS";
} catch (error) {
  evidence.status = "FAIL";evidence.stage = current;evidence.reason = error.code ?? error.name;
  console.error("FAIL  " + current + ": " + evidence.reason);process.exitCode = 1;
} finally {
  persist();writeFileSync("/tmp/l4-mcp-gateway-output", output, { mode: 0o600 });
  for (const worker of workers) if (worker.exitCode === null && worker.signalCode === null) worker.kill("SIGTERM");
  await nativeContext?.close();await gatewayContext?.close();await browser?.close();await app?.close();
  await pool?.end();await owner?.end();await control?.end();
}
