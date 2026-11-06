/** Read-only Next.js runtime cross-check for the isolated dashboard QA server. */
import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
const endpoint = "http://127.0.0.1:3005/_next/mcp";
let id = 0;
async function request(method, params) {
  const response = await fetch(endpoint, {method:"POST",headers:{"content-type":"application/json",accept:"application/json, text/event-stream"},body:JSON.stringify({jsonrpc:"2.0",id:++id,method,params}),signal:AbortSignal.timeout(30000)});
  assert.equal(response.status,200);
  const text = await response.text();
  const line = text.split("\n").find((line)=>line.startsWith("data: "));
  const result = JSON.parse(line ? line.slice(6) : text);
  assert(!result.error);return result.result;
}
const tools = await request("tools/list");
assert(tools.tools.some((tool)=>tool.name==="get_compilation_issues"));
const evidence = {status:"RUNNING",tools:tools.tools.map((tool)=>tool.name),results:{}};
for(const name of ["get_project_metadata","get_routes","get_compilation_issues","get_errors","get_page_metadata"]) {
  const result=await request("tools/call",{name,arguments:{}});assert(!result.isError, name);
  evidence.results[name]=result;
  const content = result.content.find((item) => item.type === "text")?.text;
  if (name === "get_compilation_issues") assert.deepEqual(JSON.parse(content).issues, []);
  if (name === "get_errors") {
    const errors=JSON.parse(content);
    assert.deepEqual(errors.configErrors, []);
    assert.deepEqual(errors.sessionErrors, []);
  }
  console.log("PASS " + name);
}
evidence.status="PASS";
writeFileSync("/tmp/ui-next-probe.json",JSON.stringify(evidence,null,2),{mode:0o600});
