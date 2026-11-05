# Layer 3 implementation plan

Spec: BOT_EXPERIENCE_LAYER3_BRIEF.md. Design: BOT_EXPERIENCE_LAYER3_DESIGN.md.

## Global constraints

All work stays on feat/bot-experience-layer3-workflow-runtime. No real messages, payments, Broadcast or production activation. No merge/deploy. Global default is off. Fake Providers are only external transport doubles; database and business services remain real. Python PEP 8/257. Do not expose credentials or raw personal data in telemetry or admin traces. Runtime never invokes business mutations outside the Layer 2 executor. Existing user checkout is untouched.

## Task 1: Publication and persistence

RED: add tests for snapshot immutability, publication readiness, cross-Store binding, stale preview, exact retries, version-pinning, callback ownership and slot uniqueness. GREEN: models/shop_workflow_runtime.py, services/shop_runtime/contracts.py and publication.py; register Store ORM rules and fresh-schema imports. Add category_ref/set_variable through the existing reusable contracts. Persist published snapshots, activation previews/history, binding versions, Store/Bot gates, slots, Runs, events, waits, callback tokens, Action jobs, outbox/attempts. Preserve all draft APIs. Verify with focused pytest.

## Task 2: Interpreter and Action integration

RED: deterministic typed input/branch/loop/back/cancel tests, wholesale domain isolation and real Registry receipt tests. GREEN: pure bounded interpreter and transaction coordinator; immutable version pinned on start, deduplicated event processing under slot/Run locks. Add reusable wholesale application service/model and typed Registry adapter. Durable Action jobs use stable invocation IDs, bound confirmation/approval, exact existing Layer 2 invocation and validated outputs. Test failures/retries/crash reconciliation; no direct business executor in interpreter.

## Task 3: Delivery, adapters and receivers

RED: raw Telegram/Bale contact/file/command/callback cases, forged/stale callbacks, duplicate/concurrent input, kill switch and legacy-payment regressions, definite/ambiguous send failures. GREEN: platform normalization/rendering and Fake Provider boundary; transactional outbox worker, bounded retries, timeout scheduler, action worker and audited recovery; attach after settlement and customer restrictions in registry dispatcher and legacy receivers. Verify actual PostgreSQL restart/locking races and both Fake Provider E2Es.

## Task 4: Administrative API and Studio

RED: signed HTTP permission/Store/CSRF/preview/fresh-auth tests and UI state tests. GREEN: runtime API and BFF allowlists plus Studio Runtime publication preview/approve/rollback, flags/bindings, run list/detail, safe trace, deliveries and recovery. Read Next installed docs before app changes. Verify real browser desktop/mobile, both themes, RTL, no overflow and truthful delivery/activation states.

## Task 5: Acceptance and final review

Run isolated Codespace PostgreSQL and complete Wholesale form flow for both platforms with Fake Providers, duplicate updates, restart, pinned old Run versus new publication, rollback, gates, legacy handoff, action receipts, competing workers and unknown delivery. Run full Python, Next unit/type/lint/build and Relay; preserve logs and a PASS/FAIL/BLOCKED matrix. Independent whole-branch review, fix with regression, commit and publish feature branch/Draft PR against Layer 2, verify clean own worktree. Document supported nodes, limits and Layer 4-safe contracts without implementing MCP.
