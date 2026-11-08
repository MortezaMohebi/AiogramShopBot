import assert from "node:assert/strict";
import { test } from "node:test";
import { gateStatus, recoveryOperations, deliveryState, canRetryDelivery, canApproveAction, validBindingChoices, publicationCanActivate } from "../lib/runtime/state.ts";
import type { RuntimeOverview, RunDetail, OutboxItem, PublicationPreview } from "../lib/runtime/types.ts";
import { parseScalar } from "../lib/workflows/scalar.ts";
const overview = { global_enabled: true, global_killed: false, can_manage: true, gates: [] } as unknown as RuntimeOverview;
test("global, Store and Bot opt-in are all required and kill wins", () => {
 assert.equal(gateStatus(overview, "b"), "store_disabled");
 const on = { ...overview, gates: [{scope_key:"s", bot_id:null, enabled:true, killed:false, version:1}, {scope_key:"b", bot_id:"b", enabled:true, killed:false, version:1}] };
 assert.equal(gateStatus(on, "b"), "enabled");
 assert.equal(gateStatus({...on, global_enabled:false}, "b"), "global_disabled");
 assert.equal(gateStatus({...on, global_killed:true}, "b"), "global_killed");
 assert.equal(gateStatus({...on, gates:on.gates.map(g=>({...g,killed:true}))}, "b"), "store_killed");
 assert.equal(gateStatus(on, "unselected"), "bot_disabled");
});
test("recovery keeps unknown Actions fenced and terminal Runs closed", () => {
 const run = { status:"suspended", expires_at:"2099-01-01T00:00:00Z", actions:[], outbox:[] } as unknown as RunDetail;
 assert.deepEqual(recoveryOperations(run, false), []);
 assert.deepEqual(recoveryOperations(run, true), ["resume", "cancel", "mark_failed"]);
 assert.deepEqual(recoveryOperations({...run, actions:[{status:"uncertain"}]} as RunDetail, true), ["cancel", "mark_failed"]);
 assert.deepEqual(recoveryOperations({...run, status:"completed"}, true), []);
 assert.deepEqual(recoveryOperations({...run, status:"failed", expires_at:"2020-01-01T00:00:00Z"}, true), []);
});
test("queued, sent, and uncertain deliveries are distinct and server capability is required", () => {
 assert.notEqual(deliveryState("pending"), deliveryState("sent"));
 assert.notEqual(deliveryState("dead_letter"), deliveryState("sent"));
 const row = {status:"dead_letter", can_retry:true, expected_attempts:2, attempts:2, error_code:"runtime_delivery_uncertain"} as OutboxItem;
 assert.equal(canRetryDelivery(row, true), false);
 assert.equal(canRetryDelivery({...row, error_code:"runtime_delivery_rejected"}, true), true);
 assert.equal(canRetryDelivery({...row, error_code:"runtime_delivery_rejected"}, false), false);
 assert.equal(canRetryDelivery({...row, can_retry:false}, true), false);
});
test("operator approval requires exact server capability and state", () => {
 assert.equal(canApproveAction({status:"waiting_approval", can_approve:true, expected_version:3}, true), true);
 assert.equal(canApproveAction({status:"succeeded", can_approve:true, expected_version:3}, true), false);
 assert.equal(canApproveAction({status:"waiting_approval", can_approve:false, expected_version:3}, true), false);
});
test("publication requires explicit approval and unexpired ready preview", () => {
 const preview = { ready:true, expires_at:"2099-01-01T00:00:00Z" } as PublicationPreview;
 assert.equal(publicationCanActivate(preview,false,true),false);
 assert.equal(publicationCanActivate(preview,true,true),true);
 assert.equal(publicationCanActivate({...preview,ready:false},true,true),false);
 assert.equal(publicationCanActivate({...preview,expires_at:"2020-01-01T00:00:00Z"},true,true),false);
});
test("binding choices only include declared entries and eligible assigned Bots", () => {
 const def = {target_platforms:["telegram"],assignment:{mode:"selected",bot_ids:["a"]},entry_points:[{kind:"command",key:"apply",node_id:"start"}]} as never;
 const bots = [{id:"a",name:"A",platform:"telegram",status:"active"},{id:"b",name:"B",platform:"telegram",status:"active"},{id:"a",name:"draft",platform:"telegram",status:"draft"}] as never;
 assert.equal(validBindingChoices(def,bots).length,1);
});
test("Scalar editing preserves types and rejects objects, code, fractional references and extra fields", () => {
 assert.equal(parseScalar('"سلام"'), "سلام");
 assert.equal(parseScalar('4'),4);
 assert.equal(parseScalar('false'),false);
 assert.equal(parseScalar('null'),null);
 assert.deepEqual(parseScalar('{"kind":"category","id":7}'),{kind:"category",id:7});
 for(const raw of ['{"kind":"category","id":1.2}','{"kind":"category","id":1,"token":"secret"}','[]','{"text":"x"}','()=>1','1.5']) assert.throws(()=>parseScalar(raw));
});
