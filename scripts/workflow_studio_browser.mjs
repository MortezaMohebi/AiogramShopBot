/** Run real Studio UI acceptance only against its isolated, provider-free QA lab. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";

const env = Object.fromEntries(
  readFileSync(".codespaces/beta-qa.env", "utf8")
    .split("\n")
    .filter((line) => line && !line.startsWith("#") && line.includes("="))
    .map((line) => {
      const i = line.indexOf("=");
      return [line.slice(0, i), line.slice(i + 1)];
    }),
);
const forbidden = [
  "TOKEN",
  "BALE_BOT_TOKEN",
  "BALE_WALLET_PROVIDER_TOKEN",
  "TELEGRAM_FIAT_PROVIDER_TOKEN",
  "TELEGRAM_WORKER_SECRET",
  "BALE_WEBHOOK_SECRET",
  "KRYPTO_EXPRESS_API_KEY",
];
assert(
  env.SHOP_BETA_QA === "1" &&
    env.POSTGRES_DB === "shop_codespace" &&
    env.SHOP_TEST_LAB === "1" &&
    forbidden.every((key) => !env[key]?.trim()),
  "Use only isolated provider-free Workflow QA",
);
const modulePath = process.env.WORKFLOW_PLAYWRIGHT_MODULE;
assert(
  modulePath,
  "Set WORKFLOW_PLAYWRIGHT_MODULE to the installed playwright-core/index.mjs",
);
const { chromium } = await import(pathToFileURL(modulePath).href);
const base = "http://localhost:3002",
  output = "/tmp/workflow-studio-browser";
const phase = process.env.WORKFLOW_BROWSER_STAGE || "all",
  evidence = [];
mkdirSync(output, { recursive: true, mode: 0o700 });
const statePath = output + "/acceptance-state.json";
let state = (() => {
  try {
    return JSON.parse(readFileSync(statePath, "utf8"));
  } catch {
    return {};
  }
})();
const persist = () => writeFileSync(statePath, JSON.stringify(state, null, 2));
function pass(check) {
  evidence.push({ check, status: "PASS" });
  console.log("PASS  " + check);
}
/** Credentials/OTP never leave this child-process result or appear in diagnostics. */
function docker(code) {
  return execFileSync(
    "docker",
    [
      "compose",
      "-f",
      "compose.workflow-qa.yml",
      "exec",
      "-T",
      "api",
      "python",
      "-c",
      code,
    ],
    { encoding: "utf8", timeout: 45000, stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}
function otp() {
  return docker(`import asyncio,time,json
from scripts.beta_storefront_e2e import MANIFEST,session_maker,security
from models.shop_admin_control import AdminProfile
async def main():
 async with session_maker() as db:
  profile=await db.get(AdminProfile,json.loads(MANIFEST.read_text())["admin_id"])
  secret=security.cipher().decrypt(profile.mfa_secret.encode()).decode()
  print(security.totp(secret,time.time()))
asyncio.run(main())`);
}
function businessCounts() {
  return JSON.parse(
    docker(`import asyncio,json
from scripts.workflow_studio_e2e import business_counts,engine
async def main():
 print(json.dumps(await business_counts()))
 await engine.dispose()
asyncio.run(main())`),
  );
}
async function mcp(name) {
  const response = await fetch(base + "/_next/mcp", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name, arguments: {} },
    }),
    signal: AbortSignal.timeout(30000),
  });
  assert(response.ok, "Next MCP unavailable");
  let payload;
  if (response.headers.get("content-type")?.includes("application/json"))
    payload = await response.json();
  else {
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffered = "";
    try {
      while (!payload) {
        const part = await reader.read();
        assert(!part.done, "MCP stream ended early");
        buffered += decoder.decode(part.value, { stream: true });
        buffered = buffered.replace(/\r\n/g, "\n");
        assert(buffered.length <= 1024 * 1024, "MCP response exceeded limit");
        let boundary;
        while ((boundary = buffered.indexOf("\n\n")) !== -1) {
          const event = buffered.slice(0, boundary);
          buffered = buffered.slice(boundary + 2);
          const data = event
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (!data) continue;
          const message = JSON.parse(data);
          if (message.id === 1) {
            payload = message;
            break;
          }
        }
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
  }
  assert(payload.result && !payload.result.isError, "MCP tool failed");
  return payload.result;
}
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1100, height: 1000 },
  reducedMotion: "reduce",
});
// The browser may reach only its own Next server; successful responses remain real.
await context.route("**/*", (route) =>
  new URL(route.request().url()).origin === base
    ? route.continue()
    : route.abort(),
);
const page = await context.newPage();
const runtimeErrors = [];
let secondFactor = "",
  authStage = "initial navigation";
const authResponses = [];
page.on("response", (response) => {
  const path = new URL(response.url()).pathname;
  if (path.startsWith("/api/auth/"))
    authResponses.push({ path, status: response.status() });
});
page.on("pageerror", (error) => runtimeErrors.push(error.message));
page.setDefaultTimeout(30000);
page.setDefaultNavigationTimeout(60000);
const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const button = (name) =>
  page.getByRole("button", { name: new RegExp("^" + escapeRegex(name)) });
const field = (label) => page.locator(`[aria-label=${JSON.stringify(label)}]`);
async function click(name) {
  await button(name).click();
}
async function fill(label, value) {
  await field(label).fill(String(value));
}
async function select(label, value) {
  await page
    .locator(`select[aria-label=${JSON.stringify(label)}]`)
    .selectOption(String(value));
}
async function read(expression) {
  return page.evaluate(expression);
}
async function wait(expression) {
  await page.waitForFunction(expression);
}
async function waitText(text) {
  await page
    .getByText(text, { exact: false })
    .filter({ visible: true })
    .first()
    .waitFor({ state: "visible" });
}
async function ready() {
  await page.waitForFunction(() => {
    const toggle = document.querySelector(
      '[aria-label="تغییر حالت روشن و تاریک"]',
    );
    return toggle && !toggle.disabled;
  });
}
async function open(path) {
  await page.goto(base + path);
  assert(!page.url().includes("/login"), "Session expired");
  await page.locator("main h1").waitFor();
  await ready();
}
async function editor(path) {
  await open(path);
  await field("جستجوی گره").waitFor();
}
async function saved() {
  await waitText("همهٔ تغییرات تأیید شده‌اند");
}
async function counts() {
  return read(
    `(()=>{const steps=[...document.querySelectorAll('[aria-label="فهرست مراحل"] > button')];return {nodes:steps.length,edges:steps.reduce((n,s)=>n+Number.parseInt(s.lastElementChild.innerText,10),0)}})()`,
  );
}
async function expectCounts(nodes, edges) {
  await page.waitForFunction(
    ({ nodes, edges }) => {
      const steps = [
        ...document.querySelectorAll('[aria-label="فهرست مراحل"] > button'),
      ];
      return (
        steps.length === nodes &&
        (edges === undefined ||
          steps.reduce(
            (n, s) => n + Number.parseInt(s.lastElementChild.innerText, 10),
            0,
          ) === edges)
      );
    },
    { nodes, edges },
  );
  const actual = await counts();
  assert.equal(actual.nodes, nodes);
  if (edges !== undefined) assert.equal(actual.edges, edges);
}
async function metrics() {
  return read(
    `({width:innerWidth,scroll:document.documentElement.scrollWidth,rtl:document.documentElement.dir,nodes:[...document.querySelectorAll('.react-flow__node')].map(n=>({id:n.dataset.id,visibility:getComputedStyle(n).visibility,width:n.getBoundingClientRect().width})),edges:document.querySelectorAll('.react-flow__edge').length})`,
  );
}
async function capture(name) {
  assert(!page.url().includes("/login"), "Never capture credential forms");
  const m = await metrics();
  assert.equal(m.width, m.scroll, "Horizontal overflow: " + name);
  assert.equal(m.rtl, "rtl");
  await page.screenshot({ path: output + "/" + name + ".png" });
  writeFileSync(output + "/" + name + ".json", JSON.stringify(m, null, 2));
  writeFileSync(
    output + "/" + name + ".txt",
    await page.locator("body").innerText(),
  );
  return m;
}
async function node(index) {
  const row = page
    .locator('[aria-label="فهرست مراحل"] > button')
    .nth(index - 1);
  const label = (await row.locator("span").first().innerText()).replace(
    /^\d+\.\s*/,
    "",
  );
  await row.click();
  await wait(
    `document.querySelector('[aria-label="عنوان گره"]')?.value===${JSON.stringify(label)}`,
  );
}
async function add(description, label, type) {
  const before = await counts();
  await click(description);
  await wait(
    `document.querySelectorAll('[aria-label="فهرست مراحل"] > button').length===${before.nodes + 1}`,
  );
  const code = await page.locator("fieldset code").innerText();
  assert(code.endsWith(" · " + type), "Wrong node type: " + type);
  await fill("عنوان گره", label);
  return code.split(" · ")[0];
}
async function begin(platform, path) {
  await open(path);
  await select("پلتفرم شبیه‌سازی", platform);
  await click("شروع شبیه‌سازی");
}
try {
  const metadata = await mcp("get_project_metadata");
  assert(
    JSON.stringify(metadata).includes(realpathSync("dashboard-next")),
    "Next dev is serving another checkout",
  );
  writeFileSync(
    output + "/next-project.json",
    JSON.stringify(metadata, null, 2),
  );
  pass("Next MCP confirms this checkout and running dev server");
  await page.goto(base + "/studio/workflows");
  await page.locator("h1").first().waitFor();
  if (page.url().includes("/login")) {
    authStage = "username";
    await page.getByLabel("نام کاربری", { exact: true }).fill("shopadmin");
    authStage = "password";
    await page
      .getByLabel("رمز عبور", { exact: true })
      .fill(env.LIVE_ADMIN_PASSWORD);
    authStage = "MFA";
    secondFactor = otp();
    await page
      .getByLabel("کد احراز هویت یا بازیابی (اگر فعال است)", { exact: true })
      .fill(secondFactor);
    authStage = "submit and redirect";
    await click("ورود امن");
    await page.waitForURL("**/dashboard");
    pass("Normal password and MFA browser login");
  }
  await ready();
  await click("انتخاب یک یا چند فروشگاه فعال");
  await page.getByRole("dialog").waitFor();
  await page.getByRole("radio", { name: /^انتخاب فروشگاه آزمایشی 1 / }).check();
  await click("اعمال انتخاب");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  const fixture = JSON.parse(
    docker(
      "from pathlib import Path; print(Path('/qa/workflow-studio-fixture.json').read_text())",
    ),
  );
  state.sampleId = fixture.workflow_id;
  const before = businessCounts();
  if (phase === "all" || phase === "editor") {
    await open("/studio/workflows/new");
    await fill("نام فرایند جدید", "آزمون مرورگر Studio");
    await fill("کلید فرایند", "qa_browser_" + Date.now());
    await click("ساخت پیش‌نویس");
    await field("جستجوی گره").waitFor();
    state.id = page.url().split("/").at(-1);
    persist();
    const start = await add("شروع و کنترل شروع", "QA_START", "start");
    const end = await add("شروع و کنترل پایان", "QA_END", "end");
    const message = await add("پیام پیام متنی", "QA_MESSAGE", "send_text");
    await fill("متن پیام", "پیام آزمایشی نسخهٔ اول");
    const buttons = await add(
      "تعامل پیام و دکمه",
      "QA_BUTTONS",
      "show_buttons",
    );
    await fill("متن پیام", "یک مسیر آزمایشی انتخاب کنید.");
    await click("افزودن دکمه");
    await fill("متن دکمه 1", "ادامهٔ آزمایشی");
    const branch = await add("شروع و کنترل شرط", "QA_BRANCH", "condition");
    await click("افزودن شرط");
    await select("متغیر شرط", "context.platform");
    await fill("مقدار مقایسه", "telegram");
    await select("مقصد true", end);
    await select("مقصد false", end);
    await node(1);
    await select("مقصد next", message);
    await node(3);
    await select("مقصد next", buttons);
    await node(4);
    await select("مقصد دکمه 1", branch);
    await click("چیدمان خودکار");
    await saved();
    await click("بررسی تعریف فعلی");
    await waitText("تعریف در آخرین بررسی معتبر بود");
    await expectCounts(5, 5);
    await page.reload();
    await field("جستجوی گره").waitFor();
    await saved();
    await expectCounts(5, 5);
    await node(3);
    assert.equal(
      await field("متن پیام").inputValue(),
      "پیام آزمایشی نسخهٔ اول",
    );
    state.nodes = { start, end, message, buttons, branch };
    persist();
    pass(
      "Create Start, End, message, buttons and condition; connect, validate, autosave and reload",
    );
    await click("کپی گره‌های انتخاب‌شده");
    await click("حذف گره‌های انتخاب‌شده");
    await expectCounts(4);
    await click("Paste");
    await expectCounts(5);
    await click("Undo");
    await expectCounts(4);
    await click("Undo");
    await expectCounts(5);
    await click("Redo");
    await expectCounts(4);
    await click("Undo");
    await saved();
    pass("Copy snapshot, delete, paste, Undo and Redo preserve graph");
    await node(3);
    await fill("متن پیام", "پیام آزمایشی نسخهٔ دوم");
    await saved();
    pass("Modify message and save a fresh revision");
    // Exercise the actual keyboard shortcuts with focus outside form controls.
    await click("شروع و کنترل لغو");
    await expectCounts(6);
    await page.locator("main h1").click();
    await page.keyboard.press("Control+z");
    await expectCounts(5);
    await page.keyboard.press("Control+Shift+z");
    await expectCounts(6);
    await page.keyboard.press("Control+z");
    await expectCounts(5);
    assert(
      await button("کپی گره‌های انتخاب‌شده").isDisabled(),
      "Undo left a removed node selected in the toolbar",
    );
    await saved();
    pass("Keyboard Undo/Redo and removal of stale selection");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await wait("document.querySelectorAll('.react-flow__edge').length===5");
    await click("نمایش همهٔ گره‌ها");
    await saved();
    const m = await capture("editor-desktop");
    assert.equal(m.nodes.length, 5);
    assert.equal(m.edges, 5);
    assert(m.nodes.every((n) => n.width > 0 && n.visibility === "visible"));
    pass("Desktop Canvas renders every node and connection without overflow");
  }
  assert(state.id, "Run editor stage first");
  const path = `/studio/workflows/${state.id}`;
  if (phase === "all" || phase === "preview") {
    for (const platform of ["telegram", "bale"]) {
      await begin(platform, path + "/preview");
      await waitText("ادامهٔ آزمایشی");
      await click("ادامهٔ آزمایشی");
      await waitText("completed");
      pass(
        "Created workflow preview traverses platform condition: " + platform,
      );
    }
    for (const platform of ["telegram", "bale"]) {
      await begin(platform, `/studio/workflows/${state.sampleId}/preview`);
      await waitText("سفارش آزمایشی 90001");
      await click("سفارش آزمایشی 90001");
      await waitText("محصول آزمایشی 90011");
      await click("محصول آزمایشی 90011");
      await waitText("کالا آسیب دیده");
      await click("کالا آسیب دیده");
      await waitText("توضیح کوتاهی اضافه کنید");
      await fill("پاسخ مشتری نمونه", "بسته‌بندی آزمایشی آسیب دیده");
      await click("ارسال نمونه");
      await waitText("ارسال تصویر آزمایشی");
      await click("ارسال تصویر آزمایشی");
      await waitText("این درخواست آزمایشی تأیید می‌شود");
      await click("تأیید");
      await waitText("completed");
      await page.getByText("متغیرها و مراحل", { exact: true }).click();
      const detail = JSON.parse(
        await page.locator("details[open] pre").innerText(),
      );
      assert.equal(detail.values.reason, "damaged");
      assert.deepEqual(detail.values.order, { kind: "order", id: 90001 });
      assert(detail.stub_actions.includes("create_return_request"));
      await waitText("create_return_request");
      await waitText("درخواست مرجوعی واقعی ایجاد نشد");
      await capture("return-preview-" + platform);
      pass(
        "Full synthetic Return Request, typed input, photo metadata and explicit stub: " +
          platform,
      );
    }
    await begin("telegram", `/studio/workflows/${state.sampleId}/preview`);
    await waitText("سفارش آزمایشی 90001");
    await click("سفارش آزمایشی 90001");
    await waitText("محصول آزمایشی 90011");
    await click("بازگشت");
    await button("سفارش آزمایشی 90001").waitFor();
    await click("لغو");
    await waitText("cancelled");
    pass("Preview Back and Cancel");
    await open(`/studio/workflows/${state.sampleId}/preview`);
    await select("سناریوی داده", "no_orders");
    await click("شروع شبیه‌سازی");
    await waitText("گزینهٔ آزمایشی واجد شرایطی وجود ندارد");
    await click("لغو");
    await waitText("cancelled");
    pass("Empty-order scenario remains cancellable");
  }
  if (phase === "all" || phase === "versions") {
    await open(path + "/versions");
    await click("مقایسه");
    await waitText("Metadata:");
    const articles = page.locator("article");
    const oldRevision = Number(
      (await articles.nth(1).locator("h2").innerText()).match(
        /Revision (\d+)/,
      )[1],
    );
    await articles
      .nth(1)
      .getByRole("button", { name: /^Restore/ })
      .click();
    await wait(
      "document.querySelector('article h2')?.innerText.includes('restore')===true",
    );
    assert.equal(
      Number(
        (await articles.first().locator("h2").innerText()).match(
          /Revision (\d+)/,
        )[1],
      ),
      oldRevision + 2,
    );
    await articles
      .first()
      .getByRole("button", { name: /^مشاهدهٔ Snapshot/ })
      .click();
    await waitText("Snapshot r");
    const snapshot = JSON.parse(await page.locator("section pre").innerText());
    await capture("versions-desktop");
    await editor(path);
    await saved();
    const downloadReady = page.waitForEvent("download");
    await click("دریافت JSON");
    const download = await downloadReady,
      stream = await download.createReadStream(),
      chunks = [];
    assert(stream);
    for await (const chunk of stream) chunks.push(chunk);
    const exported = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    assert.deepEqual(exported.definition, snapshot.definition);
    assert.deepEqual(exported.layout.positions, snapshot.layout.positions);
    assert.equal(exported.name, snapshot.name);
    pass(
      "Compare immutable versions, inspect Snapshot and restore as a new revision",
    );
  }
  if (phase === "all" || phase === "recovery") {
    await page.setViewportSize({ width: 1100, height: 1000 });
    await editor(path);
    await saved();
    await node(3);
    const previous = Number(
      (await page.locator("main").innerText()).match(/Revision (\d+)/)[1],
    );
    const pattern = `**/api/admin/workflows/${state.id}`;
    await context.route(pattern, (route) => route.abort());
    await fill("متن پیام", "بررسی بازیابی پس از قطع ارتباط");
    await waitText("نتیجهٔ ذخیره نامشخص");
    await click("بررسی رسید ذخیره");
    await waitText("هنوز رسیدی یافت نشد");
    assert.equal(
      await field("متن پیام").inputValue(),
      "بررسی بازیابی پس از قطع ارتباط",
    );
    await context.unroute(pattern);
    await click("تکرار همان عملیات");
    await saved();
    assert.equal(
      Number(
        (await page.locator("main").innerText()).match(/Revision (\d+)/)[1],
      ),
      previous + 1,
    );
    pass(
      "Abort save, inspect missing receipt, retain local text and retry exact operation once",
    );
  }
  if (phase === "all" || phase === "access") {
    await page.setViewportSize({ width: 1100, height: 1000 });
    await editor(path);
    await saved();
    await click("انتخاب یک یا چند فروشگاه فعال");
    await page.getByRole("dialog").waitFor();
    await page
      .getByRole("radio", { name: /^انتخاب فروشگاه آزمایشی 2 / })
      .check();
    await click("اعمال انتخاب");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await waitText("این نسخه فقط خواندنی است");
    assert(
      await page
        .locator("button[draggable]")
        .evaluateAll(
          (items) => items.length > 0 && items.every((b) => b.disabled),
        ),
    );
    await click("انتخاب یک یا چند فروشگاه فعال");
    await page.getByRole("dialog").waitFor();
    await page
      .getByRole("radio", { name: /^انتخاب فروشگاه آزمایشی 1 / })
      .check();
    await click("اعمال انتخاب");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await wait(
      "[...document.querySelectorAll('button[draggable]')].some(b=>!b.disabled)",
    );
    pass(
      "Store context refresh remounts owned workflow read-only and restores eligible editing",
    );
  }
  if (phase === "all" || phase === "layout") {
    const routes = [
      ["list", "/studio/workflows"],
      ["create", "/studio/workflows/new"],
      ["editor", path],
      ["settings", path + "/settings"],
      ["preview", path + "/preview"],
      ["versions", path + "/versions"],
    ];
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const [name, route] of routes) {
        await open(route);
        for (const theme of ["light", "dark"]) {
          if (
            (await read(
              "document.documentElement.classList.contains('dark')",
            )) !==
            (theme === "dark")
          )
            await click("تغییر حالت روشن و تاریک");
          await wait(
            `document.documentElement.classList.contains('dark')===${theme === "dark"}`,
          );
          const m = await metrics();
          assert.equal(m.width, m.scroll, `${name}/${width}/${theme} overflow`);
          assert.equal(m.rtl, "rtl");
          if (
            (width === 390 && theme === "dark") ||
            (width === 1440 && theme === "light")
          )
            await capture(`${name}-${width}-${theme}`);
        }
      }
      pass(`Six Studio routes, RTL, light and dark themes at ${width}px`);
    }
  }
  assert.deepEqual(
    businessCounts(),
    before,
    "Browser simulation changed business rows",
  );
  pass("Customer, cart, order, payment and support table counts unchanged");
  const errors = await mcp("get_errors");
  writeFileSync(output + "/next-errors.json", JSON.stringify(errors, null, 2));
  const reports = errors.content
    .filter((item) => item.type === "text")
    .map((item) => JSON.parse(item.text));
  assert(
    reports.every(
      (item) => !item.configErrors?.length && !item.sessionErrors?.length,
    ),
  );
  assert.deepEqual(runtimeErrors, [], "Uncaught browser runtime errors");
  pass("Next MCP reports no configuration or browser session errors");
  writeFileSync(
    output + "/acceptance-" + phase + ".json",
    JSON.stringify(
      {
        phase,
        driver: "Playwright",
        source_commit: execFileSync("git", ["rev-parse", "HEAD"], {
          encoding: "utf8",
        }).trim(),
        checks: evidence,
        live_provider_calls: 0,
        runtime_enabled: false,
      },
      null,
      2,
    ),
  );
} catch (error) {
  if (!page.url().includes("/login")) {
    try {
      writeFileSync(
        output + "/failure.txt",
        await page.locator("body").innerText(),
      );
      await page.screenshot({ path: output + "/failure.png" });
    } catch {}
  }
  const privateValues = [
    ...Object.entries(env)
      .filter(
        ([key, value]) =>
          /password|secret|token|key/i.test(key) && value.length >= 8,
      )
      .map(([, value]) => value),
    secondFactor,
  ].filter(Boolean);
  const message = privateValues.reduce(
    (text, value) => text.replaceAll(value, "[private]"),
    String(error.message),
  );
  if (page.url().includes("/login")) {
    const diagnostic = {
      stage: authStage,
      error: error.name,
      message,
      responses: authResponses,
      labels: await page.locator("label").allTextContents(),
      alerts: await page.locator('[role="alert"]').allTextContents(),
    };
    writeFileSync(
      output + "/auth-diagnostic.json",
      JSON.stringify(diagnostic, null, 2),
    );
    console.error(
      "FAIL  QA login: " +
        authStage +
        " " +
        error.name +
        "; see private diagnostic",
    );
  } else console.error("FAIL  " + message);
  process.exitCode = 1;
} finally {
  persist();
  // Revoke this runner's normal browser session through the existing logout UI.
  try {
    if (!page.url().includes("/login"))
      await button("خروج امن").click({ timeout: 3000 });
  } catch {}
  await context.close();
  await browser.close();
}
