# Layer 4 WPMCP Workflow Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manage bot workflows through WPMCP with one shared human approval authority and independently enforced native Store policies.

**Architecture:** Extend WPMCP with a closed bot provider and shared connection identity while retaining its existing approval tables and decision authority. A signed private bot adapter invokes existing Layer 1–3 services; immutable intents and native receipts make approved continuation durable.

**Tech Stack:** Existing TypeScript MCP SDK 2.3.1, Fastify, PostgreSQL, Python 3.12/FastAPI/SQLAlchemy, existing cryptography 46.0.4, Next.js 16.4.3/React 19.2.

**Spec:** `docs/planning/BOT_EXPERIENCE_LAYER4_BRIEF.md` with owner override and design in `docs/planning/BOT_EXPERIENCE_LAYER4_DESIGN.md`.

## Global Constraints

- Bot worktree: `/workspace/scratch/3348955ffaf6/AiogramShopBot-workflow-builder`, base `8c220af7b7cedc6c2c5ff717780e50625b433796`.
- Gateway worktree: `/workspace/scratch/3348955ffaf6/wpmcp-workflow-gateway`, base `a12d65fa8a7304ddc0b7ad1e37fc5d68b0358ba4`.
- Preserve both original checkouts and in-progress shared staging work. No merge, deployment, live messages/payments/activation, or GitHub Actions enablement.
- Gateway is the sole approval decision authority; native Backend independently enforces current staff, Store and domain rules.
- First release bot reviews are requester-only, with live native authority checks before disclosure/decision.
- An authorized durable gateway dispatch claim is the operation start; revocation reports in-flight work accurately. Native admission independently honors local revocation.
- Strict closed tools; no arbitrary ORM, Action, URL, SQL or code execution. Secrets and customer answers never enter audit or public projections.
- Integration defaults OFF. Maximum input 256 KiB, patches 128, page size 50; bounded outputs and durable quotas/concurrency.
- Reuse pinned domain services and frozen WordPress proof format; new provider uses a distinct versioned signature type.
- All product changes follow observed RED → GREEN. Evidence files record actual commands; unavailable external clients remain BLOCKED.

## File Map

- Gateway `infra/postgres/migrations/0030_provider_connections.up.sql`: common connection identity and shared approval/operation integration, retaining WordPress lease wrappers.
- Gateway `src/provider-store.ts`, `provider-proof.ts`, `bot-workflow-client.ts`, `bot-workflow-tools.ts`, `provider-worker.ts`: closed provider authority, signed private calls, SDK registration and recovery.
- Gateway existing `runtime.ts`, `tool-executor.ts`, `server-factory.ts`, dashboard approval files: opt-in wiring and accurate provider labels/review boundaries.
- Bot `models/shop_mcp.py`: native grants, pairing, Change Sets, preparations, receipts, quota/audit rows; no independent human decision.
- Bot `services/shop_mcp/`: pure contracts, signatures, authorization, patches/Change Sets, domain dispatch, preparations/commit, admin projections and budgets in focused modules.
- Bot `dashboard/mcp_api.py`: thin private signed gateway; existing signed admin routes serve grant management.
- Bot Next Studio MCP routes/components: native enrollment/grants/usage/audit and links to canonical WPMCP review.
- Tests in each repository exercise production services and real HTTP, PostgreSQL and browser behavior.

## Review Focus

- A queued signed request delivered after gateway revocation must match the documented dispatch start and never acquire new authority.
- A workspace owner with no native Store grant must never see another person's bot proposal or decide it.
- A crash after a domain service commits but before the gateway receipt must reconcile the exact receipt without repeating a write.
- An older client, unknown response or browser refresh must not turn approval/operation uncertainty into success or enable an unsafe replay.
- Existing WordPress ownership/lease expiry, approval App capability and dashboard CSRF behavior must remain enforced across the new generic connection boundary.

### Task 1: Shared provider connection and approval authority

**Files:** gateway migration 0030, `src/provider-store.ts`, tests `test/provider-approvals.test.mjs`; relevant existing approval/dashboard projections.

**Interfaces:** produces `ProviderStore.enroll/resolve/list/prepare/claim/transition/status` and SQL provider connection authorization; existing `gateway_operation_json` and `apply_approval_decision` remain canonical. Provider metadata is `provider, installation_id, native_grant_id, subject, tenant_id, workspace_id, connection_id, status`.

- [ ] Write failing real-database tests: bot connection enroll/resolve; WordPress resolver refuses it; tenant/member isolation; exact operation replay; changed hash conflicts; one requester-only review; same existing dashboard decision authority moves READY/DENIED; editor/foreign reviewer denied; revoked connection/expired review denied; existing WordPress decision still works.
- [ ] Run `node --test test/provider-approvals.test.mjs` after build. Expected: FAIL because provider enrollment/authority is absent, not a fixture error.
- [ ] Add provider identity, migrate operation FK/path constraints, preserve old WordPress entry points/wrappers, and route new provider operations through the same operation/approval tables. Define additive manager-authorized enrollment and atomic operation registration/claim with current requester authority. No bot-specific second approval table.
- [ ] Run build and provider test plus existing approval/lease files. Expected: PASS. Run gateway `npm run test:source`; record any unrelated failures by name.
- [ ] Commit verified gateway deliverable and update ledger.

### Task 2: Signed delegation and native grant boundary

**Files:** bot `models/shop_mcp.py`, `services/shop_mcp/{contracts,proofs,grants}.py`, `dashboard/mcp_api.py`; gateway `src/provider-proof.ts`; tests `tests/test_mcp_authority.py`, gateway `test/provider-proof.test.mjs`.

**Interfaces:** produces `verify_delegation(token, method, target, body, configuration) -> Delegation`, `resolve_grant(db, delegation, store_id, required_scope) -> NativePrincipal`, pairing create/confirm/revoke services. Private fixed `/internal/mcp/v1` uses these before domain dispatch. Canonical JSON and proof fixtures shared across languages.

- [ ] Write tests for a valid signed private read, wrong algorithm/key/issuer/audience/body/method/target/subject/client/tenant/grant/version, expiry/future token, duplicate keys, revoked staff/member/grant, Store/Bot selection and single-use pairing. Assert no domain write on denial.
- [ ] Run focused Python/Node tests; Expected: missing feature FAIL.
- [ ] Implement strict versioned Ed25519 proofs, current native grant/membership intersection and manager-confirmed pairing. Never use gateway token contents supplied in model arguments or fabricate dashboard sessions. Keep replay protection separate from domain idempotency.
- [ ] Run focused tests and cross-language proof fixture. Expected: PASS, plus previous authority/lease gates remain PASS.
- [ ] Commit verified bot/gateway parts and ledger results.

### Task 3: Typed workflow services, patches and Change Sets

**Files:** bot `services/shop_mcp/{catalog,patches,changes,dispatch}.py`, models as needed, tests `tests/test_mcp_workflows.py`.

**Interfaces:** produces closed `tool_catalog()` and `dispatch(db, principal, name, arguments) -> dict`; shared `apply_patches(definition, layout, operations) -> proposal`; Change Set create/get/update/validate/simulate/cancel/apply. All existing services receive trusted scope/actor.

- [ ] Write real-service tests for context/platform/Bot/Action discovery, every typed patch, invalid/foreign media and Bot, exact UUID retry vs changed payload, stale revisions, all mutation paths' risk checks, immutable pending proposal, pure validation/simulation, bounded pagination/output and private Runtime projection.
- [ ] Run focused tests; Expected: FAIL on absent services.
- [ ] Implement read/mutation adapters over existing services, normalized patch engine and durable Change Sets with shared risk policy. Add resources and six bounded prompt contracts without executing user text. Staged high-risk changes return exact preparation, never effects.
- [ ] Run `pytest tests/test_mcp_authority.py tests/test_mcp_workflows.py`; Expected: PASS. Run current domain workflow/Action/Runtime tests.
- [ ] Commit verified services and ledger.

### Task 4: Exact sensitive intent and native receipt reconciliation

**Files:** bot `services/shop_mcp/{preparations,execution}.py`, gateway proof and provider store; tests `tests/test_mcp_approved_execution.py`.

**Interfaces:** `prepare(db, principal, kind, payload) -> immutable intent`; `commit(db, principal, intent_id, approval_proof) -> native receipt`; `receipt(db, principal, operation_id)`. Types include publish/rollback/ChangeSet/gate/run retry/cancel/known-rejected delivery retry. Unknown effects remain forbidden.

- [ ] Write tests for exact hash/revision/Store/connection/actor/grant-version/expiry binding; real publication/recovery/gate services; stale revision/binding/dependency requires new review; no local decision API; duplicate approved request makes one effect; crash after domain commit reconciles; native revocation vs admission race.
- [ ] Run focused tests; Expected: absent preparation/commit FAIL.
- [ ] Persist native intent/operation receipt only, validate distinct generic approval proof, use stable existing domain operation IDs and exact publication previews. Reconcile existing revision/publication/audit receipts before retry; serialize native authority and effect admission in consistent lock order.
- [ ] Run focused and existing Runtime publication/recovery tests; Expected: PASS.
- [ ] Commit and ledger proof of RED/GREEN and receipt behavior.

### Task 5: Actual gateway MCP tools and automatic continuation

**Files:** gateway `src/{bot-workflow-client,bot-workflow-tools,provider-worker}.ts`, existing runtime/server files, tests `test/bot-workflow-mcp.test.mjs`, `test/provider-recovery.test.mjs`.

**Interfaces:** consumes Tasks 1–4. `registerBotWorkflowTools(server,runtime)` registers only closed typed `bot.*` catalog/resources/prompts. `ProviderWorker.tick()` claims approved work, rechecks authority, signs exact private requests and reconciles native receipt after unknown response/restart.

- [ ] Write actual SDK HTTP tests for auth, scoped tool/resource/prompt discovery, native calls, unavailable/forged routes, rejected input, namespace collisions and legacy client compatibility. Test auto continuation with no further model call; worker competition; timeout/restart; exact pending replay; revoked-before-claim denial; paused signed request after dispatch/revoke reflects in-flight semantics.
- [ ] Run Node test files; Expected: missing registration/worker FAIL.
- [ ] Implement fixed-origin signed client (no redirects/arbitrary URL), bounded responses/timeouts, DB leases/fences, persisted normalized proposal and exact approved proof. Extend supported WPMCP review surfaces with live native authority and requester restriction; no model-callable approve path.
- [ ] Run actual transport tests and gateway source suite; Expected: PASS. Unavailable native/gateway/approval infrastructure fails closed and does not impersonate success.
- [ ] Commit and ledger.

### Task 6: Enrollment, administration, quota and audit UX

**Files:** bot signed admin routes, `services/shop_mcp/admin.py`, Next Studio MCP pages/components/tests; gateway provider connection management/review projections.

**Interfaces:** native manager-confirmed pair, list/get/revoke grants, audit/usage; WPMCP review URL/status only. Gateway manager connection enrollment and revocation report existing in-flight work accurately.

- [ ] Read installed Next docs and existing UI conventions. Write failing behavior tests for exact enrollment grant, foreign-store redaction, revocation, pending/conflict/unknown response preservation, role-gated controls and no local approval decision.
- [ ] Run focused Backend/Next tests; Expected: new behavior FAIL.
- [ ] Wire actual APIs, durable counters/leases and safe audit. Implement Persian RTL/dark/responsive views with usable empty/error/loading states and canonical review links.
- [ ] Run tests, Typecheck, Lint, Build and actual browser interactions at mobile/desktop in both themes. Expected: PASS; no private values or browser errors.
- [ ] Commit and ledger.

### Task 7: Real product inquiry and PostgreSQL acceptance

**Files:** versioned catalog Action projection if required; `scripts/qa_workflow_mcp.py`, isolated gateway acceptance harness, `docs/qa/WORKFLOW_MCP_LAYER4_ACCEPTANCE.md` evidence.

**Interfaces:** consumes complete actual MCP/private protocol. Fake transport/payment providers are external test boundaries; real DB/services/approval state machine remain real.

- [ ] Write the product inquiry acceptance through real MCP: authenticate, discover Stores/Bots/platforms/Actions/catalog, draft Start/question/category/search/display/contact/confirmation/end, assign Telegram/Bale, validate; introduce/fix actual compatibility error; simulate both; exact ChangeSet/diff; one controlled human decision; auto publish; actual Fake Runtime/Action receipt and audit.
- [ ] If scalar search output is required, first reproduce its absence, then add an additive versioned projection from actual visible catalog results. Existing version stays unchanged.
- [ ] Run acceptance with actual PostgreSQL: independent workers, duplicate input, revision conflict, restart, signature/proof replay, reviewer/tenant isolation and native/gateway revocation order. Expected: all controlled gates PASS; no live provider call.
- [ ] Attempt available Inspector/developer/ChatGPT client paths without publishing private QA. Record exact unavailable paths BLOCKED.
- [ ] Commit safe evidence and ledger.

### Task 8: Regression, final review and reviewable branches

**Files:** final report, verified fixes, branch/PR descriptions.

**Interfaces:** complete branches with safe acceptance evidence, full brief's 24-field handoff.

- [ ] Run full Python, Next unit/type/lint/build, gateway source tests, Relay and PostgreSQL/browser acceptance after final product changes. Expected: PASS with inherited warnings/unavailable external gates identified.
- [ ] Produce whole-branch review package for both repositories; one fresh reviewer checks security, domain authority, compatibility and recovery against the brief/design and ledger rulings. Regrade findings by user impact.
- [ ] Reproduce Critical/Important findings RED, fix in one pass, then run affected full suites GREEN. Record deferred minors and rationale for any declined important finding.
- [ ] Publish only isolated feature branches/Draft PRs with exact bases and evidence; preserve shared staging. Keep Actions OFF. Verify clean own worktrees and no owned QA service left running unnecessarily.
- [ ] Report earned progress, commits/PRs, results, actual limitations, deferred items and rulings/costs. Never claim 100% while a locally runnable mandatory gate fails.
