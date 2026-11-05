/** Real, provider-free Studio QA. Run against own Next dev:3002 / API:8092. */
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
const values = Object.fromEntries(
  readFileSync(".codespaces/beta-qa.env", "utf8")
    .trim()
    .split("\n")
    .map((line) => [
      line.slice(0, line.indexOf("=")),
      line.slice(line.indexOf("=") + 1),
    ]),
);
if (
  values.SHOP_BETA_QA !== "1" ||
  values.POSTGRES_DB !== "shop_codespace" ||
  values.TOKEN ||
  values.BALE_BOT_TOKEN
)
  throw Error("Use only isolated provider-free Workflow QA");
const session = process.env.AGENT_BROWSER_SESSION;
if (!session) throw Error("Use the worktree-scoped browser session");
const base = "http://localhost:3002",
  output = "/tmp/workflow-studio-browser";
mkdirSync(output, { recursive: true, mode: 0o700 });
function ab(...args) {
  // Control names aid QA diagnosis; filled values (including MFA) stay private.
  console.log("STEP", args[0], String(args[1] ?? "").slice(0, 100));
  try {
    return execFileSync(
      "agent-browser",
      ["--session", session, "--restore", session, ...args],
      { encoding: "utf8", timeout: 60000, stdio: ["ignore", "pipe", "pipe"] },
    ).trim();
  } catch (error) {
    if (args[0] !== "fill")
      console.log(String(error.stderr ?? error.code ?? "").slice(0, 500));
    throw Error(`Browser action failed: ${args[0]}`);
  }
}
function assert(value, message) {
  if (!value) throw Error(message);
}
function reference(snapshot, description) {
  const normalize = (value) => value.replace(/[\u200b\u200c\u200d]/g, "");
  const line = snapshot
    .split("\n")
    .find((line) => normalize(line).includes(normalize(description)));
  const ref = line?.match(/ref=(e\d+)/)?.[1];
  assert(ref, `Visible control missing: ${description}`);
  return "@" + ref;
}
function snapshot() {
  return ab("snapshot", "-i");
}
function read(expression) {
  let value = JSON.parse(ab("eval", `JSON.stringify(${expression})`));
  if (typeof value === "string") value = JSON.parse(value);
  return value;
}
function docker(code) {
  try {
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
  } catch {
    throw Error("Guarded QA database read failed");
  }
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
function metrics() {
  return read(
    "({width:innerWidth,scroll:document.documentElement.scrollWidth,rtl:document.documentElement.dir,headings:document.querySelectorAll('h1').length,nodes:[...document.querySelectorAll('.react-flow__node')].map(n=>({id:n.getAttribute('data-id'),visibility:getComputedStyle(n).visibility,width:n.getBoundingClientRect().width})),edges:document.querySelectorAll('.react-flow__edge').length})",
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
/** DOM-only observations and user-visible controls; no React state injection. */
const evidence = [],
  statePath = output + "/acceptance-state.json";
const phase = process.env.WORKFLOW_BROWSER_STAGE || "all";
let state = (() => {
  try {
    return JSON.parse(readFileSync(statePath, "utf8"));
  } catch {
    return {};
  }
})();
const saveState = () =>
  writeFileSync(statePath, JSON.stringify(state, null, 2));
function pass(check) {
  evidence.push({ check, status: "PASS" });
  console.log("PASS  " + check);
}
function wait(expression) {
  ab("wait", "--fn", expression);
}
function text() {
  return read("document.body.innerText");
}
function waitText(value) {
  wait(`document.body.innerText.includes(${JSON.stringify(value)})`);
}
function click(name) {
  ab("click", reference(snapshot(), `button "${name}`));
}
function fill(label, value) {
  ab("fill", `[aria-label=${JSON.stringify(label)}]`, String(value));
}
function select(label, value) {
  ab("select", `select[aria-label=${JSON.stringify(label)}]`, String(value));
}
function open(path) {
  ab("open", base + path);
  wait("document.querySelector('main h1')!==null");
  assert(!ab("get", "url").includes("/login"), "Session expired");
  ab("react", "tree");
}
function saved() {
  waitText("همهٔ تغییرات تأیید شده‌اند");
}
function editor(path) {
  open(path);
  wait("document.querySelector('[aria-label=\"جستجوی گره\"]')!==null");
}
function capture(name) {
  assert(
    !ab("get", "url").includes("/login"),
    "Never capture credential forms",
  );
  writeFileSync(output + "/" + name + ".txt", snapshot());
  ab("screenshot", output + "/" + name + ".png");
  const m = metrics();
  writeFileSync(output + "/" + name + ".json", JSON.stringify(m, null, 2));
  assert(
    m.width === m.scroll,
    `Horizontal overflow on ${name}: ${m.width}/${m.scroll}`,
  );
  assert(m.rtl === "rtl", `RTL missing on ${name}`);
  return m;
}
function node(index) {
  ab("click", `[aria-label="فهرست مراحل"] > button:nth-of-type(${index})`);
}
function add(description, label) {
  ab("click", reference(snapshot(), `button "${description}`));
  fill("عنوان گره", label);
  return read(
    "[...document.querySelectorAll('.react-flow__node')].at(-1).getAttribute('data-id')",
  );
}
function counts() {
  return read(
    "({nodes:document.querySelectorAll('.react-flow__node').length,edges:document.querySelectorAll('.react-flow__edge').length})",
  );
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
function begin(platform, path) {
  open(path);
  select("پلتفرم شبیه‌سازی", platform);
  click("شروع شبیه‌سازی");
}
try {
  ab("set", "viewport", "1100", "1000");
  ab("open", base + "/studio/workflows");
  wait("document.querySelector('h1')!==null");
  let tree = snapshot();
  if (ab("get", "url").includes("/login")) {
    ab("fill", reference(tree, 'textbox "نام کاربری"'), "shopadmin");
    ab(
      "fill",
      reference(tree, 'textbox "رمز عبور"'),
      values.LIVE_ADMIN_PASSWORD,
    );
    ab("fill", reference(tree, 'textbox "کد احراز هویت'), otp());
    ab("click", reference(tree, 'button "ورود امن"'));
    ab("wait", "--url", "**/dashboard");
    pass("Normal password and MFA login");
  }
  assert(
    ab("react", "tree").includes("StoreSwitcher"),
    "Store switcher not hydrated",
  );
  click("انتخاب یک یا چند فروشگاه فعال");
  ab("wait", '[role="dialog"]');
  tree = ab("snapshot", "-i", "-s", '[role="dialog"]');
  ab("click", reference(tree, 'radio "انتخاب فروشگاه آزمایشی 1 '));
  click("اعمال انتخاب");
  wait("document.querySelector('[role=dialog]')===null");
  const fixture = JSON.parse(
    docker(
      "from pathlib import Path; print(Path('/qa/workflow-studio-fixture.json').read_text())",
    ),
  );
  state.sampleId = fixture.workflow_id;
  const before = businessCounts();

  if (phase === "all" || phase === "editor") {
    open("/studio/workflows/new");
    fill("نام فرایند جدید", "آزمون مرورگر Studio");
    fill("کلید فرایند", "qa_browser_" + Date.now());
    click("ساخت پیش‌نویس");
    wait("document.querySelector('[aria-label=\"جستجوی گره\"]')!==null");
    state.id = ab("get", "url").split("/").at(-1);
    saveState();
    const start = add("شروع و کنترل شروع", "QA_START");
    const end = add("شروع و کنترل پایان", "QA_END");
    const message = add("پیام پیام متنی", "QA_MESSAGE");
    fill("متن پیام", "پیام آزمایشی نسخهٔ اول");
    const buttons = add("تعامل پیام و دکمه", "QA_BUTTONS");
    fill("متن پیام", "یک مسیر آزمایشی انتخاب کنید.");
    click("افزودن دکمه");
    fill("متن دکمه 1", "ادامهٔ آزمایشی");
    const branch = add("شروع و کنترل شرط", "QA_BRANCH");
    click("افزودن شرط");
    select("متغیر شرط", "context.platform");
    fill("مقدار مقایسه", "telegram");
    select("مقصد true", end);
    select("مقصد false", end);
    node(1);
    select("مقصد next", message);
    node(3);
    select("مقصد next", buttons);
    node(4);
    select("مقصد دکمه 1", branch);
    click("چیدمان خودکار");
    saved();
    click("بررسی تعریف فعلی");
    waitText("تعریف در آخرین بررسی معتبر بود");
    assert(
      counts().nodes === 5 && counts().edges === 5,
      "Graph topology mismatch",
    );
    ab("reload");
    wait("document.querySelector('[aria-label=\"جستجوی گره\"]')!==null");
    saved();
    assert(
      counts().nodes === 5 && counts().edges === 5,
      "Saved graph did not survive reload",
    );
    node(3);
    assert(
      read("document.querySelector('[aria-label=\"متن پیام\"]').value") ===
        "پیام آزمایشی نسخهٔ اول",
      "Edited text not persisted",
    );
    pass(
      "Create Start, End, message, buttons and condition; connect, validate, autosave and reload",
    );
    state.nodes = { start, end, message, buttons, branch };
    saveState();
    // A copied snapshot survives deletion of the selected source.
    click("کپی گره‌های انتخاب‌شده");
    click("حذف گره‌های انتخاب‌شده");
    assert(counts().nodes === 4, "Node delete failed");
    click("Paste");
    assert(counts().nodes === 5, "Clipboard lost its deleted source");
    click("Undo");
    assert(counts().nodes === 4, "Paste undo failed");
    click("Undo");
    assert(counts().nodes === 5, "Delete undo failed");
    click("Redo");
    assert(counts().nodes === 4, "Delete redo failed");
    click("Undo");
    saved();
    pass("Copy snapshot, delete, paste, Undo and Redo preserve graph");
    node(3);
    fill("متن پیام", "پیام آزمایشی نسخهٔ دوم");
    saved();
    pass("Modify message and save a fresh revision");
    ab("set", "viewport", "1440", "1000");
    wait(
      "[...document.querySelectorAll('.react-flow__node')].every(n=>getComputedStyle(n).visibility==='visible')",
    );
    const m = capture("editor-desktop");
    assert(m.nodes.length === 5 && m.edges === 5, "Visible Canvas mismatch");
    pass("Desktop Canvas renders every node and connection without overflow");
  }
  assert(state.id, "Run editor stage first");
  const path = `/studio/workflows/${state.id}`;
  if (phase === "all" || phase === "preview") {
    for (const platform of ["telegram", "bale"]) {
      begin(platform, path + "/preview");
      waitText("ادامهٔ آزمایشی");
      click("ادامهٔ آزمایشی");
      waitText("completed");
      assert(
        !text().includes("invalid_definition"),
        "Created graph cannot simulate",
      );
      pass(
        `Created workflow preview traverses platform condition: ${platform}`,
      );
    }
    for (const platform of ["telegram", "bale"]) {
      begin(platform, `/studio/workflows/${state.sampleId}/preview`);
      waitText("سفارش آزمایشی 90001");
      click("سفارش آزمایشی 90001");
      waitText("محصول آزمایشی 90011");
      click("محصول آزمایشی 90011");
      waitText("کالا آسیب دیده");
      click("کالا آسیب دیده");
      waitText("توضیح کوتاهی اضافه کنید");
      fill("پاسخ مشتری نمونه", "بسته‌بندی آزمایشی آسیب دیده");
      click("ارسال نمونه");
      waitText("ارسال تصویر آزمایشی");
      click("ارسال تصویر آزمایشی");
      waitText("این درخواست آزمایشی تأیید می‌شود");
      click("تأیید");
      waitText("completed");
      waitText("create_return_request");
      assert(
        text().includes("درخواست مرجوعی واقعی ایجاد نشد"),
        "Simulation did not finish safely",
      );
      capture("return-preview-" + platform);
      pass(
        `Full synthetic Return Request with typed input, photo metadata and explicit stub: ${platform}`,
      );
    }
    begin("telegram", `/studio/workflows/${state.sampleId}/preview`);
    waitText("سفارش آزمایشی 90001");
    click("سفارش آزمایشی 90001");
    waitText("محصول آزمایشی 90011");
    click("بازگشت");
    wait(
      "[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='سفارش آزمایشی 90001'&&!b.disabled)",
    );
    click("لغو");
    waitText("cancelled");
    pass("Preview Back and Cancel");
    open(`/studio/workflows/${state.sampleId}/preview`);
    select("سناریوی داده", "no_orders");
    click("شروع شبیه‌سازی");
    waitText("گزینهٔ آزمایشی واجد شرایطی وجود ندارد");
    click("لغو");
    waitText("cancelled");
    pass("Empty-order scenario remains cancellable");
  }
  if (phase === "all" || phase === "versions") {
    open(path + "/versions");
    click("مقایسه");
    waitText("Metadata:");
    const oldRevision = read(
      "Number(document.querySelectorAll('article h2')[1].innerText.match(/Revision (\\d+)/)[1])",
    );
    ab("click", "article:nth-of-type(2) button:last-child");
    wait(
      "document.querySelector('article h2')?.innerText.includes('restore')===true",
    );
    ab("click", "article:first-of-type button:first-child");
    waitText("Snapshot r");
    capture("versions-desktop");
    editor(path);
    saved();
    assert(
      read("document.querySelector('main').innerText").includes(
        "Revision " + (oldRevision + 2),
      ),
      "Restore did not append a revision",
    );
    pass(
      "Compare immutable versions, inspect Snapshot and restore as a new revision",
    );
  }
  if (phase === "all" || phase === "recovery") {
    ab("set", "viewport", "1100", "1000");
    editor(path);
    saved();
    node(3);
    const previous = read(
      "Number(document.querySelector('main').innerText.match(/Revision (\\d+)/)[1])",
    );
    const pattern = `**/api/admin/workflows/${state.id}`;
    ab("network", "route", pattern, "--abort");
    fill("متن پیام", "بررسی بازیابی پس از قطع ارتباط");
    waitText("نتیجهٔ ذخیره نامشخص");
    click("بررسی رسید ذخیره");
    waitText("هنوز رسیدی یافت نشد");
    assert(
      read("document.querySelector('[aria-label=\"متن پیام\"]').value") ===
        "بررسی بازیابی پس از قطع ارتباط",
      "Unknown save lost the local document",
    );
    ab("network", "unroute", pattern);
    click("تکرار همان عملیات");
    saved();
    assert(
      read(
        "Number(document.querySelector('main').innerText.match(/Revision (\\d+)/)[1])",
      ) ===
        previous + 1,
      "An exact retry appended multiple revisions",
    );
    pass(
      "Abort save, inspect missing receipt, preserve local text and retry exact operation once",
    );
  }
  if (phase === "all" || phase === "access") {
    ab("set", "viewport", "1100", "1000");
    editor(path);
    saved();
    click("انتخاب یک یا چند فروشگاه فعال");
    ab("wait", '[role="dialog"]');
    tree = ab("snapshot", "-i", "-s", '[role="dialog"]');
    ab("click", reference(tree, 'radio "انتخاب فروشگاه آزمایشی 2 '));
    click("اعمال انتخاب");
    wait("document.querySelector('[role=dialog]')===null");
    waitText("این نسخه فقط خواندنی است");
    assert(
      read(
        "document.querySelector('[aria-label=\"جستجوی گره\"]').parentElement.querySelector('button[draggable]')?.disabled ?? [...document.querySelectorAll('button[draggable]')].every(b=>b.disabled)",
      ),
      "Wrong current Store retained editor controls",
    );
    click("انتخاب یک یا چند فروشگاه فعال");
    ab("wait", '[role="dialog"]');
    tree = ab("snapshot", "-i", "-s", '[role="dialog"]');
    ab("click", reference(tree, 'radio "انتخاب فروشگاه آزمایشی 1 '));
    click("اعمال انتخاب");
    wait("document.querySelector('[role=dialog]')===null");
    wait(
      "[...document.querySelectorAll('button[draggable]')].some(b=>!b.disabled)",
    );
    pass(
      "Store context refresh remounts owned workflow read-only, then restores eligible editing",
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
      ab("set", "viewport", String(width), "1000");
      for (const [name, route] of routes) {
        open(route);
        for (const theme of ["light", "dark"]) {
          if (
            read("document.documentElement.classList.contains('dark')") !==
            (theme === "dark")
          )
            click("تغییر حالت روشن و تاریک");
          wait(
            `document.documentElement.classList.contains('dark')===${theme === "dark"}`,
          );
          const m = metrics();
          assert(
            m.width === m.scroll,
            `${name}/${width}/${theme} overflow ${m.scroll}`,
          );
          assert(m.rtl === "rtl", "RTL missing");
          if (
            (width === 390 && theme === "dark") ||
            (width === 1440 && theme === "light")
          )
            capture(`${name}-${width}-${theme}`);
        }
      }
      pass(`Six Studio routes, RTL, light and dark themes at ${width}px`);
    }
  }
  assert(
    JSON.stringify(businessCounts()) === JSON.stringify(before),
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
    "Next MCP reported errors",
  );
  pass("Next MCP reports no configuration or browser session errors");
  writeFileSync(
    output + "/acceptance-" + phase + ".json",
    JSON.stringify(
      {
        phase,
        checks: evidence,
        live_provider_calls: 0,
        runtime_enabled: false,
      },
      null,
      2,
    ),
  );
} catch (error) {
  try {
    writeFileSync(output + "/failure.txt", snapshot());
    ab("screenshot", output + "/failure.png");
  } catch {}
  console.error("FAIL  " + error.message);
  process.exitCode = 1;
} finally {
  saveState();
}
