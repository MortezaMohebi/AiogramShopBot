# Final disposition: F1–F3 fixed and re-reviewed

The original findings below are historical; the focused follow-up at the end verifies their fixes.

# Layer 4 whole-branch review

Review date: 2026-11-06. This is a fresh, read-only review of the complete branch diffs against these exact bases:

| Repository | Base | Reviewed HEAD |
| --- | --- | --- |
| Native | `8c220af7b7cedc6c2c5ff717780e50625b433796` | `28f6efda5b9b61c437f4239ccd2903971c93ecfb` |
| WPMCP | `a12d65fa8a7304ddc0b7ad1e37fc5d68b0358ba4` | `257f96abe884ade05a245351bb6af442853c7b4d` |

The review used the Layer 4 brief, design, implementation plan, and the user override making WPMCP the sole public MCP authentication and human business approval authority. It covered the Native private protocol, grants and authority serialization, proposals/intents/proofs, execution receipts, shared domain changes, closed Next BFF and management UI, gateway connection/enrollment/approval/worker state, migrations 0030–0034, quotas, and additive product-search v2 changes. The parent is independently running full suites and cross-service acceptance. This review does not establish their results. No product files were changed and no live messages, payments, deployment, or merge was attempted.

Three Important findings were reproduced. No Critical issue or authority/tenant isolation bypass was established. Minor observations are intentionally omitted.

## F1 — Important: a known pre-dispatch stale intent leaves all later work on the connection blocked

**Primary location:** WPMCP `apps/saas-gateway/src/provider-worker.ts:76–80`.

**Supporting locations:** `infra/postgres/migrations/0031_bot_provider_worker.up.sql:45–46,67–68,94–95`; Native `services/shop_mcp/preparations.py:320,468–479`.

An approved intent can become stale when a human changes the Workflow in Native Studio before its worker tick. Native review correctly rejects the old revision with `409 workflow_revision_conflict`. The fresh worker has not called `native.commit`, but its unconditional catch stores `UNCERTAIN`. SQL excludes every READY operation on that connection while any UNCERTAIN operation exists. Recovery rechecks the permanently stale intent every ten seconds and restores UNCERTAIN, so a newly prepared and approved current operation cannot run. The same connection has no exposed way to terminalize this known non-dispatched failure. Recreating the connection is a workaround.

The private reproduction uses production `ProviderStore`, `PostgresOperationStore`, `ProviderWorker`, and the real migration functions in isolated PGlite. Only the external Native transport is faked. Native receipt reports the prepared intent and review definitively rejects the stale revision. It asserts zero commit calls, the first operation UNCERTAIN, the second READY, no available claim for the second, and the same state after a recovery tick.

**Runnable reproduction:** `repro_gateway.mjs`, function `staleReviewBlocksConnection`.

**Safe fix scope:** distinguish a fresh `DISPATCHING` claim before this process has attempted the first commit from previously dispatched/recovered work. For a definitive live-review rejection or intent expiry at that fresh boundary, finish FAILED with a stable safe error code and release the connection. The existing SQL provides the discriminator: `claim_provider_operation` accepts only READY and returns DISPATCHING (`0030:228–243`), whereas all recovered DISPATCHING/RECONCILING/UNCERTAIN work returns RECONCILING (`0031:71–76`). There is no provider transition back to READY. The local `attempted` flag is set immediately before the commit await. Together, fresh state plus `!attempted` is sufficient for this narrow fix; a separate durable commit-start marker is unnecessary unless recovery itself is allowed to infer an earlier worker never dispatched. Preserve the claim fence: a fresh worker whose lease was replaced cannot terminalize the replacement's operation. Preserve receipt-first reconciliation and UNCERTAIN for RECONCILING work, every attempted commit, and unknown responses. Do not reinterpret all `attempted=false` errors as safe failure.

**Regression coverage:** stale review/expiry on a fresh claim ends without commit and permits a later current operation to run; recovered work with no receipt remains UNCERTAIN; a timed-out or delayed previous commit can still reconcile to SUCCEEDED after revocation; an old fresh fence cannot override a recovery claim. The existing altered-review test at `test/provider-recovery.test.mjs:122–127` currently expects the broken UNCERTAIN outcome and should change only for the proven fresh boundary.

## F2 — Important: committed proposal writes cannot recover when the MCP journal finalization is interrupted

**Primary location:** Native `services/shop_mcp/journal.py:75–90`.

**Supporting locations:** `services/shop_mcp/dispatch.py:85–89`; `services/shop_mcp/changes.py:191–193,221–224,311–318`; immutable evidence at `models/shop_mcp.py:264–278`.

Proposal creation, proposal update, and sensitive apply each commit before `journal.finish` stores the recovery reference. A process interruption in that gap leaves a durable pending McpRequest with `result_json = NULL` plus the already committed proposal/version/freeze. Journal recovery searches only domain Workflow revisions before returning None for that journal state, so dispatch repeats the proposal mutation. Exact retries then fail with `mcp_change_set_exists` (staged Workflow creation and changes.create), `mcp_change_set_version_conflict` (changes.update), or `mcp_change_set_frozen` (sensitive changes.apply). The operation receipt continues reporting pending without its recoverable result. This strands an accepted edit or sensitive proposal precisely when the caller is instructed to reuse the same operation ID after an unknown result.

The private reproduction uses the real Native service and database fixture, injects an interruption immediately before journal finalization without editing implementation files, confirms pending/NULL state survived rollback, and retries the exact request. It reproduces all four failures against actual persistence. This is a proposal recovery failure; the review did not demonstrate a duplicate domain effect.

**Runnable reproduction:** `repro_native.py`.

**Safe fix scope:** persist the journal reference atomically with each proposal commit, or recover it from immutable owned proposal evidence. `McpChangeSetRevision.operation_id` is unique and binds the exact version; use it together with the already validated full journal digest/tool/grant/Store and the owned parent, rather than assuming the parent's current version is the original result. Sensitive apply has no new proposal revision and needs the owned frozen parent's matching `effect_operation_id` plus its exact requested version, while domain receipts remain authoritative if the operation later applied. Recovery must return the original version/reference even if the proposal was subsequently updated, cancelled, or applied. It must not replay a write, increase a version, create a new approval, or accept an operation from another entry point or grant.

**Regression coverage:** interrupt after each of the committed proposal writes and before journal.finish, then retry exactly and inspect the operation receipt. Both return the original proposal/version or pending-approval reference; proposal versions and approvals stay unchanged. Also advance the proposal with a later operation before recovering the older operation and assert that recovery returns its immutable historical version.

## F3 — Important: the displayed enrollment recovery cannot repair a prepare request that never reached Native

**Primary location:** WPMCP `apps/saas-gateway/src/bot-workflow-connections.ts:33–38`.

**Supporting locations:** `bot-workflow-connections.ts:21–22`; `bot-connection-pages.ts:82–84,91–93`; `dashboard-routes.ts:490–518`.

Enrollment first commits the pending gateway connection, then sends the Native pairing preparation. If the transport fails before Native receives it, the gateway correctly preserves the original IDs and shows its unknown-result recovery page. That page leads to the same connection detail, whose only recovery action calls `synchronize`. Synchronize only queries Native status. Native therefore returns `mcp_pairing_not_found` on every attempt, the Native Studio link also has no pairing to show, and the connection remains pending even after connectivity returns. The request service can replay the original prepare if supplied the full original parameters, but the displayed detail/recovery flow cannot invoke it. The user can abandon/revoke this request and create another as a workaround; the same-ID recovery promised by the UI is missing.

The private reproduction uses the real enrollment service/store and isolated migration database. The first prepare throws before any Native pairing exists; after transport restoration, two synchronize attempts still query only status. It asserts pending state, no Native pairing, one prepare call, and two status calls.

**Runnable reproduction:** `repro_gateway.mjs`, function `pairingRecoveryCannotRepairMissingPrepare`.

**Safe fix scope:** give the authenticated owner a recovery path that retries Native preparation for this same pending connection, using its persisted immutable actor, installation, grant, Stores, and scopes. This can be an exact prepare replay on a definite Native missing-pairing response or a dedicated retry action. Do not accept edited form authority, generate new IDs, or replace a confirmed, conflicting, revoked, or expired request. Retain independent Native manager consent and all existing expiry/conflict checks.

**Regression coverage:** both fail-before-Native-commit and lost-response-after-Native-commit recover the original connection/pairing and eventually one grant; replay never widens scopes/Stores, changes identity, or extends expired consent.

## Reproduction commands and observed results

Run the Gateway command from its `apps/saas-gateway` directory with the existing built production modules and installed dependencies:

```sh
node private-review-reproductions/repro_gateway.mjs
```

Run the Native command from `/workspace/scratch/3348955ffaf6/AiogramShopBot-workflow-builder`:

```sh
../AiogramShopBot/.venv/bin/python private-review-reproductions/repro_native.py
```

Both commands exited 0 and asserted the broken states. Gateway ran against isolated PGlite; Native ran against an isolated in-memory SQLite fixture. These are focused reproductions, not PostgreSQL/browser cross-service acceptance. Exact output is recorded in `reproduction-output.txt`.

## Readiness assessment

The public/native authority split, exact proof binding, Store-first serialization, owned immutable intent/proposal evidence, replay protection, closed BFF routes, and additive search v2 design are consistent with the stated boundaries in the reviewed paths. No evidence was found of a second Native human business approval mechanism, arbitrary execution surface, reviewer/tenant isolation escape, or duplicated domain effect.

The branch can be shared as a work-in-progress Draft PR with these findings explicitly listed. It is not ready to be presented as review-complete or recovery-verified. Fix F1–F3, run their focused regressions, and complete the parent's actual PostgreSQL/Chromium cross-service acceptance before a readiness claim. Full-suite counts and acceptance outcomes remain the parent's responsibility; none are claimed here.


# F1–F3 focused fix review

Reviewed the uncommitted fixes in the same Native and WPMCP worktrees on 2026-11-06. This review is limited to F1–F3 and the requested inline-availability assessment. No product files were modified.

**Result: F1–F3 are addressed in the reviewed changes. No new Important safety, adoption, or atomicity issue was found within these fixes.**

| Finding | Assessment | Safety evidence |
| --- | --- | --- |
| F1: fresh stale-review rejection blocks the connection | Addressed | `provider-worker.ts` terminalizes only a fresh `DISPATCHING` claim before a commit attempt, with a definite Native rejection or explicit failed precondition. SQL returns `RECONCILING` for every recovered dispatch/uncertain claim. The commit flag is set before the commit await; old claim fences cannot override replacement claims. Recovered or commit-attempted work retains receipt-first uncertainty. |
| F2: committed proposals lack recoverable journal references | Addressed | `journal.py` keeps authoritative domain receipts first, then finds the unique immutable proposal revision operation ID under the journal's grant and Store. It returns that revision's historical version. Sensitive apply requires the owned parent, matching `effect_operation_id`, and original requested version. Neither path repeats the mutation or creates another version. |
| F3: missing Native preparation cannot be repaired through same-ID recovery | Addressed | `synchronize` retries only a definite Native `404 mcp_pairing_not_found` while the persisted gateway request remains unexpired. Preparation uses the saved connection, actor, and spec. A second independent status read is still required before activation; unknown/expired states do not trigger preparation, and Native retains exact binding/conflict and consent checks. |

The Native recovery path retains the existing exact-request digest check before retry recovery; the status route independently filters the journal by current grant and Store. Proposal evidence is committed with its journal row, its operation ID is unique, and the owned-parent filters prevent adoption from a different grant or Store. The new query does not widen the accepted write surface. Returning an older immutable proposal with its current parent status/version is consistent with the existing proposal projection. The historical-v1-after-v2 regression verifies the material case.

An additional durable commit-start marker is unnecessary for F1's restricted fresh-claim finalization. It would be required before extending safe-failure inference to recovered work that might have dispatched in an earlier process. The current code preserves that distinction.

Independently reran these focused checks against the reviewed fixes:

```sh
# Native worktree
../AiogramShopBot/.venv/bin/python -m pytest -q tests/test_mcp_proposal_recovery.py
# 4 passed in 5.78s
```

```sh
# Gateway apps/saas-gateway
node --test test/provider-recovery.test.mjs test/provider-enrollment.test.mjs
# 17 passed; 0 failures, cancelled, or skipped
```

The Native tests cover the four actual post-commit/pre-journal-finalization crash boundaries, no additional immutable versions, recoverable operation status, and an original v1 proposal recovered after another request created v2. The Gateway tests cover fresh failure releasing later READY work, recovery failure remaining UNCERTAIN, lost successful responses, timeout/revocation receipt reconciliation, stale fences, no duplicate competing claim, exact preparation replay, and no preparation on unknown or expired status. These checks use isolated local fixtures; no new full-suite or PostgreSQL/browser acceptance claim is made.

## Requested inline capability assessment

`BotWorkflowService.approval` still returns `inline_available:false` unconditionally at `apps/saas-gateway/src/bot-workflow-tools.ts:115`. This is misleading as a capability report: a supported authenticated client with configured `runtime.approvalUi` can immediately obtain an inline card through `show_approval_panel`, whose handler calls `ApprovalUiService.present` and returns `inline_available:true` plus UI-private capability metadata. A consumer that treats the initial false as unavailability can unnecessarily send the human to the dashboard. The actual card path remains functional.

The narrow fix is to omit this field from the initial preparation result and let `show_approval_panel` report the verified, actor-specific availability. Do not replace it with a simple `Boolean(runtime.approvalUi)`: configuration alone does not establish supported client identity, current pending status, expiry, or a valid private capability. This reporting inconsistency does not reopen F1–F3 or establish an approval bypass.
