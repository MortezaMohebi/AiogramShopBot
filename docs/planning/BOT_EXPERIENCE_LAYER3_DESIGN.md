# Layer 3 design

Base: ec11aec0945c78cff44e084f5f81b81f0b052f2e. Branch: feat/bot-experience-layer3-workflow-runtime.
Authority: BOT_EXPERIENCE_LAYER3_BRIEF.md. Layer 4 is excluded.

## Boundaries

Keep drafts/revisions unchanged. Publish copies an exact validated revision into an immutable snapshot. Preview is session-bound, expiring, one-use, request-hashed and captures current bindings; activation revalidates dependencies and requires manager scope, workflows.publish and fresh authentication. Per-Bot bindings are versioned pointers. Rollback changes only new Runs. Published retirement never mutates the snapshot.

Runtime is globally off unless explicitly enabled. Persistent Store/Bot gates can disable it immediately. Receiver checks financial updates first, current Bot/Store state and customer restrictions next, Runtime next, legacy last. Payment and reserved legacy callbacks always remain reachable. Legacy navigation suspends the active Run; disabling Runtime preserves Run data and hands inputs to legacy.

Runs pin one published snapshot. A Bot/customer slot serializes starts and input transitions. Events deduplicate authenticated update IDs and persist redacted summaries. Waits and opaque, hashed, expiring, single-use callback capabilities are bound to Store/Bot/customer/Run/node/visit. Wrong customer, stale node, replay and tampering never move a Run. No SDK objects enter the interpreter.

The bounded iterative interpreter emits state plus outbound/action intents in one transaction. It implements primitive control/message/input nodes and generic typed Action nodes. Legacy commerce wrapper nodes and simulator-only choice sources remain explicitly unpublishable: their replacements are exact-version Action nodes. Add only the missing reusable set_variable primitive and category_ref declaration support. Back restores only safe interaction checkpoints; business mutations fence history. Cancel does not undo business operations.

An Action job commits before invocation. The worker holds the Run lock while invoking Layer 2 in its independently committing dedicated session. Stable invocation identity reconciles a crash after Action commit. Proofs come only from persisted customer confirmation or manager approval, bound by Layer 2 to the exact request. No domain mutation bypasses the Action Registry. Implement the missing reusable wholesale application service and exact typed adapter required by the mandatory acceptance scenario. Returns stay unavailable until their real domain service exists.

Outbox intent is atomic with state; delivery is separate. Claim sending before the provider call; validate current flags and Bot again. Known pre-send failures may retry with bounded backoff. Timeout/crash/unknown receipt is marked uncertain/dead letter and never automatically resent. Delivery receipts carry provider message IDs. Explicitly distinguish queued, sent and uncertain delivery; no exactly-once claim.

Adapters normalize Telegram/Bale text, callback, own contact and bounded file metadata. Runtime owns no provider tokens. Platform rendering and upload limits are validated before publication and delivery; incoming file handles stay private and Bot-scoped. Workers use existing credential resolution/provider clients. Runtime uploads are evidence handles, not executable URLs or public media.

Signed Store-scoped APIs and Studio Runtime screens expose publication previews/history, bindings/gates, Runs, redacted events/variables, Action receipts, outbox and audited recovery. Read/write/publish/recovery permissions are separate. All pages use existing Signed Bridge, CSRF and StoreContext.

## Constraints and operational limits

At-least-once inbound processing with deduplication, serialized transitions and idempotent local Actions. No real provider calls in QA. Fail closed on unsupported node, unavailable Action/version, operator proof missing, invalid file/type/size or exhausted budgets. Keep all customer Bot activation off outside disposable QA. Runtime state is bounded by node/step/visit/input/TTL/rate limits, with explicit terminal and suspended recovery. No destructive cleanup of old checkouts, no production schema reset, no merge or deployment.

## Verification

Focused behavioral tests first, then real PostgreSQL concurrency/restart/outbox/rollback tests, real signed HTTP, both authenticated Receiver paths with Fake Providers, and browser desktop/mobile RTL/dark mode. Full Python, Next unit/type/lint/build, Relay and existing acceptance regressions remain required. Independent final code review before completion.
