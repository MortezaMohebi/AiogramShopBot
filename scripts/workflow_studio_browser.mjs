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
  try {
    return execFileSync(
      "agent-browser",
      ["--session", session, "--restore", session, ...args],
      { encoding: "utf8", timeout: 60000, stdio: ["ignore", "pipe", "pipe"] },
    ).trim();
  } catch {
    throw Error(`Browser action failed: ${args[0]}`);
  }
}
function assert(value, message) {
  if (!value) throw Error(message);
}
function reference(snapshot, description) {
  const line = snapshot.split("\n").find((line) => line.includes(description));
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
try {
  ab("set", "viewport", "1440", "1000");
  ab("open", base + "/studio/workflows");
  ab("wait", "--fn", "document.querySelector('h1') !== null");
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
    console.log("PASS  Normal password + MFA browser login", true);
  }
  const reactTree = ab("react", "tree");
  writeFileSync(output + "/react-tree.txt", reactTree);
  assert(
    reactTree.includes("StoreSwitcher"),
    "Store Switcher is not yet mounted",
  );
  tree = snapshot();
  ab("click", reference(tree, 'button "انتخاب یک یا چند فروشگاه فعال"'));
  ab("wait", '[role="dialog"]');
  tree = ab("snapshot", "-i", "-s", '[role="dialog"]');
  ab("click", reference(tree, 'radio "انتخاب فروشگاه آزمایشی 1 '));
  tree = ab("snapshot", "-i", "-s", '[role="dialog"]');
  ab("click", reference(tree, 'button "اعمال انتخاب"'));
  ab("wait", "--fn", "document.querySelector('[role=dialog]')===null");
  const fixture = JSON.parse(
    docker(
      "from pathlib import Path; print(Path('/qa/workflow-studio-fixture.json').read_text())",
    ),
  );
  ab("open", `${base}/studio/workflows/${fixture.workflow_id}`);
  ab("wait", "--fn", "document.querySelector('h1') !== null");
  tree = snapshot();
  writeFileSync(output + "/editor-probe.txt", tree);
  ab("screenshot", output + "/editor-probe.png");
  writeFileSync(
    output + "/editor-metrics.json",
    JSON.stringify(metrics(), null, 2),
  );
  console.log("PASS  Editor loaded; probe artifacts recorded");
  const errors = await mcp("get_errors");
  writeFileSync(output + "/next-errors.json", JSON.stringify(errors, null, 2));
  console.log("NEXT_MCP", JSON.stringify(errors));
} catch (error) {
  try {
    writeFileSync(output + "/failure.txt", snapshot());
    ab("screenshot", output + "/failure.png");
  } catch {}
  console.error(error.message);
  process.exitCode = 1;
}
