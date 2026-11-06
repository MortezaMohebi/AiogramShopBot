/** Independent QA process using the actual durable WPMCP worker and real SQL. */
import { createPrivateKey } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

try {
  const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
  if (config.mode !== "isolated_workflow_mcp_qa" || config.gatewayRoot !== "/workspaces/wpmcp-bot-qa") throw Error();
  const load = (name) => import(pathToFileURL(config.gatewayRoot + "/apps/saas-gateway/dist/" + name + ".js").href);
  const require = createRequire(config.gatewayRoot + "/apps/saas-gateway/package.json");
  const { Pool } = require("pg");
  const pool = new Pool({ connectionString: config.database, max: 3, statement_timeout: 15000 });
  const appPool = { query: async (sql, args) => {
    const client = await pool.connect();
    try { await client.query("SET ROLE aiwb_app");return await client.query(sql, args); }
    finally { client.release(); }
  } };
  const { ProviderStore } = await load("provider-store");
  const { ProviderWorker } = await load("provider-worker");
  const { BotWorkflowClient } = await load("bot-workflow-client");
  const { ProviderDelegationSigner, ProviderApprovalSigner } = await load("provider-proof");
  const { PostgresGatewayAdmission } = await load("gateway-admission");
  const key = (value) => createPrivateKey({ format: "der", type: "pkcs8", key: Buffer.from(value, "base64") });
  const native = new BotWorkflowClient({
    endpoints: new Map([[config.installation, "http://127.0.0.1:8095"]]),
    studioOrigins: new Map([[config.installation, "http://127.0.0.1:3005"]]),
    allowLoopbackHttp: true,
    delegation: new ProviderDelegationSigner({ issuer: config.issuer, keyId: "qa-delegation", privateKey: key(config.delegation) }),
    fetcher: async (url, options) => {
      const response = await fetch(url, options);
      if (String(url).endsWith("/commit") && response.ok) {
        try {
          // Simulate process death after a real Native commit, before its reply.
          writeFileSync(config.crashMarker, JSON.stringify({ checkpoint: "after_native_commit", pid: process.pid }), { flag: "wx", mode: 0o600 });
          process.kill(process.pid, "SIGKILL");
        } catch (error) { if (error.code !== "EEXIST") throw error; }
      }
      return response;
    },
  });
  const worker = new ProviderWorker({ store: new ProviderStore(appPool), native,
    approval: new ProviderApprovalSigner({ issuer: config.issuer, keyId: "qa-approval", privateKey: key(config.approval) }),
    admission: new PostgresGatewayAdmission(appPool), pollMs: 100,
  });
  worker.start();
  const keepAlive = setInterval(() => undefined, 1000);
  process.once("SIGTERM", async () => { clearInterval(keepAlive);await worker.stop();await pool.end(); });
} catch {
  console.error("FAIL  isolated provider worker setup");process.exitCode = 1;
}
