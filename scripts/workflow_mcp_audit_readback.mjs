/** Verify durable audit rows for the isolated, already approved QA operation. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const root = "/workspaces/wpmcp-bot-qa";
const output = readFileSync("/tmp/l4-mcp-gateway-output", "utf8").trim();
assert.match(output, /^\/tmp\/workflow-mcp-gateway-[a-f0-9-]{36}$/);
const evidence = JSON.parse(readFileSync(output + "/evidence.json", "utf8"));
assert.equal(evidence.status, "PASS");assert.equal(evidence.controlled_human_decisions, 1);
const config = JSON.parse(readFileSync(output + "/worker-private.json", "utf8"));
assert.equal(config.mode, "isolated_workflow_mcp_qa");assert.equal(config.gatewayRoot, root);
const database = new URL(config.database);
assert.equal(database.hostname, "127.0.0.1");assert.equal(database.port, "5485");
assert.match(database.pathname, /^\/aiwb_workflow_mcp_[a-f0-9]{32}$/);
const { Client } = createRequire(root + "/apps/saas-gateway/package.json")("pg");
const client = new Client({ connectionString: database.href });
try {
  await client.connect();
  const rows = (await client.query("SELECT event_type,count(*)::int n FROM aiwb.gateway_operation_events WHERE operation_id=$1 AND event_type IN ('approval.decided','operation.completed') GROUP BY event_type", [evidence.operation_id])).rows;
  const counts = Object.fromEntries(rows.map((row) => [row.event_type, row.n]));
  assert.equal(counts["approval.decided"], 1);assert.equal(counts["operation.completed"], 1);
  const code = `import asyncio,json,os,sys
from sqlalchemy import select,func
from scripts.test_lab_safety import require_isolated_lab
require_isolated_lab()
assert os.environ.get("SHOP_MCP_QA")=="1"
from db import session_maker,engine
from models.shop_workflow_runtime import RuntimeAudit
data=json.loads(sys.stdin.read())
async def main():
 async with session_maker() as db:
  count=await db.scalar(select(func.count()).select_from(RuntimeAudit).where(RuntimeAudit.target_id==data["publication_id"],RuntimeAudit.action=="activate"))
  print(json.dumps({"activation_audits":count}))
 await engine.dispose()
asyncio.run(main())`;
  const native = JSON.parse(execFileSync("docker", ["compose", "-f", "compose.workflow-mcp-qa.yml", "exec", "-T", "api", "python", "-c", code],
    { input: JSON.stringify({ publication_id: evidence.publication_id }), encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }));
  assert.equal(native.activation_audits, 1);
  const result = { status: "PASS", gateway_approval_audits: counts["approval.decided"], gateway_completion_audits: counts["operation.completed"],
    native_activation_audits: native.activation_audits, operation_id: evidence.operation_id, publication_id: evidence.publication_id };
  writeFileSync("docs/qa/workflow-mcp/audit-readback.json", JSON.stringify(result, null, 2) + "\n");
  console.log("PASS  One persisted human decision, gateway completion and Native activation audit");
} finally { await client.end(); }
