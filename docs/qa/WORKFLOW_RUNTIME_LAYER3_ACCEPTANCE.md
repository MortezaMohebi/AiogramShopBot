# Workflow Runtime — Layer 3 acceptance, 2026-11-05

**LAYER 3 PROGRESS: 100%**
**STATUS: COMPLETE — READY FOR LAYER 4**

All implementation and acceptance gates passed. Finalization adds documentation
and verified evidence to the tested application source. Runtime remains off by
default and the PR remains Draft, unmerged and undeployed.

## 1. Base branch

`feat/bot-experience-layer2-action-registry`, final Layer 2 commit
`ec11aec0945c78cff44e084f5f81b81f0b052f2e` (968 baseline Python passes).
The binding scope is [the Layer 3 brief](../planning/BOT_EXPERIENCE_LAYER3_BRIEF.md),
[design](../planning/BOT_EXPERIENCE_LAYER3_DESIGN.md) and
[implementation plan](../planning/BOT_EXPERIENCE_LAYER3_PLAN.md).

## 2. Feature branch

`feat/bot-experience-layer3-workflow-runtime`.
[Draft PR #17](https://github.com/MortezaMohebi/AiogramShopBot/pull/17)
targets the completed Layer 2 branch. It is unmerged. Runtime is off by default;
no customer Bot activation, live message/payment/Broadcast or deployment occurred.

## 3. Final commit and evidence provenance

- Independently reviewed application behavior: `c074fb9c543c71b6dbfefe8bd35d6953f3c8a288`.
- Browser-fixture/formatting checkpoint: `042e4ad54ae9193c66890e7d71830052913828df`.
- Final UI and browser source: `d7a6a0c8d1a016ad601a77623b86b7d502420d9e`.
- Final report/evidence commit is the feature branch HEAD.
- Isolated Codespace: `obscure-space-couscous-p7w6p4jrrxv3j59`.
- Owned checkout: `/workspaces/AiogramShopBot-workflow-runtime`.
- Owned project: `aiogram-workflow-runtime-qa`, PostgreSQL 18, loopback API 8094,
  Next dev 3004. Existing checkout, containers and volumes were preserved.

The second checkpoint corrects two browser-fixture assumptions and formats two
Python files. Both Python ASTs exactly match the tested application commit;
Runtime logic, models and Relay are unchanged. The final UI correction preserves
the known denial code for forbidden delivery replay and gives clear guidance;
its complete Next checks were rerun. See
[source equivalence](workflow-runtime/source-equivalence.json). The matrix below
states the source of each result; earlier failures were not promoted to passes.

## 4. Progress

**100%.** Implementation, independent scoped re-review, regressions, build,
PostgreSQL and browser acceptance are complete. No Layer 4 implementation began.

## 5. Runtime models and persistent sessions

[Runtime storage](../../models/shop_workflow_runtime.py) contains 15 Store-owned
tables: `PublishedWorkflow`, `PublicationPreview`, `RuntimeBinding`, `RuntimeGate`,
`RuntimeAudit`, `RuntimeSlot`, `WorkflowRun`, `WorkflowEvent`, `WorkflowWait`,
`WorkflowCallback`, `WorkflowActionJob`, `WorkflowOutbox`,
`WorkflowDeliveryAttempt`, `WorkflowInbox` and `WorkflowUpload`.
A real wholesale application model supports the form's domain mutation.

Inbox admission commits before processing. A Bot/user Slot serializes customer
state and exact input receipts; duplicate delivery replays its safe result and
increments its counter. Malformed durable input is quarantined without poisoning
other customers. Ordinary input received during a delay cannot answer a later
question. Timely accepted answers retain priority over an input deadline.

Runs pin the immutable publication, typed values, bounded checkpoints and trusted
customer display name. Callback capabilities are opaque, hashed, expiring and
bound to Store/Bot/customer/Run/node/generation. Run TTL also covers approval waits.
Fresh-schema PostgreSQL creation verified 135 tables and the immutable-publication
trigger. This beta acceptance does not certify a production upgrade/migration.

## 6. Publication, rollback and retirement

[Publication](../../services/shop_runtime/publication.py) validates exact saved
revisions, real Action versions, effective per-platform transitions, confirmation,
Bot/media ownership and supported live shapes. An expiring session-bound preview
must receive explicit manager approval with recent authentication.

The preview compares each affected entry's actual current publication with the
proposed definition, including forward-after-rollback, mixed versions, unbound
entries and retained unselected bindings. Studio groups equal comparison pairs.
A Store routing mutex serializes absent-key conflicts, activation and retirement;
its PostgreSQL NO KEY UPDATE lock permits normal child FK checks. Administrative
changes for the same Store serialize even when their keys differ.

Snapshots are immutable through ORM and PostgreSQL guards. Rollback changes only
new-entry pointers. Existing Runs keep their pinned version; retirement preserves
history and idempotent operation replay.

## 7. Entry points and gates

Bindings support declared command, start-payload and menu entries, plus trusted
internal, legacy-bridge and admin-test hooks. These hooks are Backend contracts,
not customer-selected identity or node-jump endpoints. Reserved `cart`, `checkout`,
`catalog`, `orders`, `support` and `payment` commands retain legacy ownership.

Deployment configuration, Store opt-in and Bot opt-in are separate. Both
`SHOP_WORKFLOW_RUNTIME_ENABLED` and `SHOP_WORKFLOW_RUNTIME_KILL_SWITCH` default to
false. The isolated test project opts in explicitly. Gates are checked before
claims and effects; emergency stopping retains already accepted input ownership.
The worker entry is [shop_workflow_runtime.py](../../shop_workflow_runtime.py).

## 8. Supported nodes and precise live limits

24 Runtime node types:

| Purpose | Nodes |
| --- | --- |
| Flow | `start`, `end`, `cancel`, `condition`, `switch`, `go_to_step`, `set_variable`, `delay` |
| Output | `send_text`, `send_photo`, `send_video`, `send_document`, `send_media_group`, `show_buttons`, `confirm` |
| Input | `wait_for_input`, `ask_text`, `ask_number`, `ask_phone`, `ask_email`, `ask_photo`, `ask_document`, `ask_choice` |
| Business | `action` |

Input types, Persian numbers, Back, Cancel, explicit timeout edges and configured
error/timeout policies are exercised. Global /cancel terminates even where an
authored decline edge loops. Configured cancellation output receives a final
notice receipt; obsolete prompts remain suppressed. A hard Run TTL stays expired,
separate from an authored conversational timeout outcome.

Reply labels resolve only to choices actually offered on the current platform
and generation. Identical typed text is equivalent to a reply-key tap. Unsupported
contact/action controls, reserved keys and ambiguous navigation are rejected at
publication. Static `ask_choice` is supported; synthetic product/order choices and
simulator-only commerce wrappers block live publication. Drafts remain editable.

Limits include 60 accepted inputs per Bot/user/minute, 20 pending inputs,
1,000 events and 1,000 outbox intents per Run, bounded values/state/visits/steps,
a 24-hour Run TTL and at most 20 MB of verified inbound evidence with lower
per-node/provider bounds. The wholesale template limits its document to 2 MB.

## 9. Telegram coverage

Raw private updates pass through real normalization, receiver admission, durable
coordinator, typed input and Fake Telegram transport. Tests cover own Contact,
verified PDF/photo evidence, text/media/keyboards, opaque callbacks, duplicates,
forgery/expiry/stale input, limits and delivery failure. The complete wholesale
form persists one domain application and one Layer 2 receipt. Receiver hooks run
before old receipt claims while financial updates retain their existing handlers.

## 10. Bale coverage

The same complete form, real persistence and receipt assertions pass independently
through raw Bale normalization and its adapter. Own Contact, native evidence,
callbacks, reply-label round trips, duplicate input and failures have separate
coverage. Per-platform capabilities are enforced, including media-group support,
compatible album types, row/label bounds and private media ownership. Fake HTTP
responses and actual bytes replace only the external provider boundary.

## 11. Action Registry integration

Business work uses the Layer 2 executor with exact key/version, typed input/output,
Store/Bot/customer identity and stable job/invocation/idempotency IDs. The minimal
real `wholesale.create_application` service is reusable outside Runtime.

There are 19 contracts, 16 with real services. `order.list_return_eligible_orders`,
`returns.create_request` and `notification.notify_admin` remain unavailable.
Return Request therefore cannot publish as a live workflow until its Backend
exists. No successful business mutation is fabricated.

Customer consent uses a server timestamp (300 seconds) and reviewed-value hash;
operator approval is separately required where declared. Recovery reconciles an
already committed success receipt before testing fresh consent. Changed values,
expired/denied proof and unknown effects cannot create a second mutation.
Unavailable exact versions or dependencies follow the authored unavailable edge,
including dependencies disabled between customer confirmation and proof issuance.

Retry/approval waits remain at the same Action/job. Descriptor budgets and durable
backoff govern retry; exhaustion follows error. Publication rejects distinct
simulator-only retry or pending-approval destinations: those ports must identify
the same target as error for live publication. Studio states this contract.

## 12. Outbox, retries and recovery

State transitions and outbound intent commit together. Claim and physical-attempt
evidence commit before the single provider operation, including albums. Ordered
claims skip locked owners before LIMIT so unrelated customers can progress.
Customer/gate state is rechecked at the effect boundary.

Positive provider IDs prove delivery. Definite rejection has bounded automatic
retry (three attempts) and capped explicit retry. An uncertain send/ACK/crash is a
`dead_letter` with `runtime_delivery_unknown`, an uncertain attempt and no retry
capability. Its absence of a receipt never proves that no message was sent.

Audited recovery requires a separate capability, recent authentication and exact
version/operation IDs. Slot-before-Run locking and current-slot checks prevent
resuming over another Run. It cannot force replay of unknown or committed effects.
Studio freezes an unknown administrative write until its exact audit reconciles;
unrelated history and malformed successful responses do not unlock a second write.

## 13. Legacy coexistence and operational visibility

Actual Dispatcher/receiver checks preserve legacy start, catalog, cart, checkout,
orders and native payment bypasses. PostgreSQL fingerprints verify order/payment,
refund/wallet/campaign/digital-delivery table counts and product stock are unchanged.
The form's intended wholesale mutation is verified separately.

Studio `/studio/runtime` covers gates, publications/rollback, bindings, Run lists
and private detail, Action receipts, delivery evidence, audit and recovery. Metrics
use all retained history of the current Store and bounded active version groups;
zero, absent data and unavailable data are distinct. Private values, phone numbers,
provider file handles and proof material are excluded. SQL errors hide parameters.
The signed BFF retains its closed route/argument, Store/session, CSRF, Origin,
request-size and fresh-auth checks.

## 14. Exact tests and results

| Gate | Result and tested scope | Evidence |
| --- | --- | --- |
| Codespace compileall and full Python | PASS — 1,154; 3 inherited Testimonial collection warnings; 206.99 s; c074fb9 | [Python log](workflow-runtime/python-codespace.log) |
| Actual PostgreSQL + Fake Providers | PASS — 23/23 groups; c074fb9 | [Results](workflow-runtime/postgresql.json), [log](workflow-runtime/postgresql.log) |
| Runtime/Action focused proof correction | PASS — 137; disabled dependency and expired-consent controls preserve carts and issue no proof/receipt | [Summary](workflow-runtime/summary.json) |
| Full Next units | PASS — 212, including 112 Runtime tests; d7a6a0c | [Unit log](workflow-runtime/next-units.log) |
| Type checking and lint | PASS — TypeScript and ESLint with zero warnings; d7a6a0c | [Summary](workflow-runtime/summary.json) |
| Production build | PASS — 47 generated pages; d7a6a0c | [Build log](workflow-runtime/next-build.log) |
| Python formatting | PASS — 12 changed-wave files; two final format-only ASTs identical | [Source equivalence](workflow-runtime/source-equivalence.json) |
| Cloudflare Relay | PASS — 14; unchanged Relay tree | [Relay log](workflow-runtime/relay.log) |
| Fresh PostgreSQL DDL | PASS — 135 tables and immutable trigger; unchanged model tree; disposable schema transaction rolled back | [DDL log](workflow-runtime/fresh-schema.log) |
| Actual browser | PASS — 16/16 groups, 28 route/viewport/theme combinations, 45 screenshots; d7a6a0c | [Browser results](workflow-runtime/browser.json) |
| Independent final review | PASS — all 10 Important/3 Minor findings addressed; zero open findings | Scope below |
| GitHub Actions | PASS — Disable actions selected; Allow all unselected; no PR-triggered runs at reviewed source | [Summary](workflow-runtime/summary.json) |
| Branch/PR closure | PASS — committed application and QA evidence, correct Layer 2 base | Draft PR17, no merge/deploy |

The final browser run has zero Page errors, unexpected Console errors or private
response errors, zero external browser requests, and normal server-verified logout.
All six Runtime tabs and Run detail pass at 1100 and 390 px in light and dark.
Selected masked screenshots include [desktop dark](workflow-runtime/desktop-dark-overview.png),
[mobile dark](workflow-runtime/mobile390-dark-overview.png),
[mobile light publications](workflow-runtime/mobile390-light-publications.png),
[rollback review](workflow-runtime/rollback-preview.png) and
[unknown delivery](workflow-runtime/uncertain-no-retry.png). The first three were
also visually inspected.

The 23 PostgreSQL groups include separate Telegram/Bale full forms, duplicate
confirmations, Inbox crash/restart and ordering, post-Layer-2-commit recovery,
outbound ordering/retry/uncertainty/crash, timeout races, navigation, immutable
versions/rollback, emergency gates, real receiver ordering, legacy behavior,
signed Store isolation and commerce fingerprints. New lock cases require a
named second customer to progress while the first Run/Slot is still locked,
observe actual pg_blocking_pids for gate-versus-claim/independent Action commit,
and race two workflow heads for an absent entry plus retirement/activation.

The independent review inspected the complete Layer 3 application diff against
Layer 2, then the single final fix wave and proof-time correction. It verified all
13 findings, independently reproduced the confirmed cart dependency failure and
checked the correction plus expired-consent control. Its verdict covers source
specification/quality; the actual Codespace/browser results are separately owned
and recorded above. No new broad review cycle or live-provider certification is
implied by the verdict.

Actual failures corrected during the loop included PostgreSQL 40P01, stale ORM
claims, revoked-customer sends, locked/terminal-owner queue starvation, typed
reference serialization, delay/input arbitration, implicit consent paths,
reply-key navigation, cancellation receipts, wrong rollback baselines,
activation/retirement races, unavailable Action routing and lost unknown UI state.
Focused final tests produced 26 failures/9 controls on the original source and
35 passes after correction. The additional confirmed-cart case also ran RED
before its fix and GREEN with a real populated cart afterward.

The initial final browser run exposed two harness assumptions: an exclusively
Telegram assignment still targeted Bale, and an unknown send was queried under
a non-persisted `uncertain` queue status. The corrected runner chooses a current
PostgreSQL Run's actual dead-letter/unknown row and retains the real retry-denial
assertion. A stale Next dev process's 404 was resolved by restarting only that
owned process; authentication checks were retained. Failed runs are not final
acceptance evidence.

A subsequent actual browser check found a known Runtime 409 denial lost its
code at the Signed Bridge allowlist and appeared as service_unavailable. Two
new regressions ran RED. The final UI adds that exact bounded denial code and
clear retry-refusal guidance; 212 tests, typecheck, zero-warning lint and build
passed afterward. Unknown upstream codes and private fields remain discarded.
The Backend denial and delivery evidence were preserved.

Reproduction, using only the private isolated QA environment and existing
synthetic fixtures (do not reset an existing database):

```bash
# From the owned Codespace checkout, with its guarded provider-free compose.
docker compose -f compose.workflow-runtime-qa.yml exec -T api \
  python -m scripts.workflow_runtime_e2e
docker compose -f compose.workflow-runtime-qa.yml exec -T api \
  python -m pytest -p no:cacheprovider -q tests

WORKFLOW_PLAYWRIGHT_MODULE=/workspaces/beta-qa-tools/playwright/node_modules/playwright-core/index.mjs \
PLAYWRIGHT_BROWSERS_PATH=/workspaces/beta-qa-tools/playwright-browsers \
/workspaces/beta-qa-tools/bin/node scripts/workflow_runtime_browser.mjs

cd dashboard-next
npm test
npm run typecheck
npm run lint -- --max-warnings=0
npm run build
```

Do not run a production provider worker against these fixtures. The test runner
patches only allowed external provider factories behind a network fence; database,
identity, publication, Action and persistence paths remain real.

## 15. Remaining limitations

- No real Telegram/Bale client, public webhook or monetary transaction was used.
- Return and external admin-notification services remain explicitly unavailable.
- Unsupported live nodes/controls and distinct retry/approval destinations are
  blocked rather than silently given simulator behavior.
- Browser coverage is Chromium, explicit desktop/mobile widths and both themes;
  it is not a complete device, accessibility or production-load certification.
- Fresh beta schema and additive QA checks do not certify an existing production
  database upgrade. Future rollout requires its own authorized plan.
- The three inherited collection warnings are documented, not hidden skips.

## 16. Required Layer 4 contracts

Future designers must use the existing typed definition/catalog, shared
validation/readiness, revision/CAS/history, safe Simulator and exact reviewed
publication APIs. Store/session permissions and explicit human approval remain
Backend authority. Run/Action/delivery inspection stays private. Arbitrary customer
identities, executable service paths, node jumps, implicit publication and automatic
live activation are not designer capabilities. No MCP server, LLM/customer AI or
Layer 4 implementation is included here.

## 17. Known risks and handoff decisions

External delivery cannot be guaranteed exactly once after an unknown provider
outcome; quarantining and evidence-led reconciliation are deliberate. Same-Store
routing writes serialize for coherent missing-key ownership, with a control-plane
throughput cost. Reply transports cannot prove a physical key press rather than
identical typed text. Private pinned state now includes the trusted display name
and bounded offered reply labels; admin projections remain redacted.

The real wholesale service is a minimal reusable dependency of the mandatory
acceptance form and adds a domain capability to maintain. Simulator-only commerce
wrappers remain unpublishable to preserve Layer 2 authority. No unnecessary FK
type rewrite or destructive beta migration was introduced. Existing user work,
stack and volumes are preserved. Runtime defaults and repository Actions remain
off, PR17 remains Draft and unmerged, and Layer 4 has not started.

After acceptance, only the owned Next dev process and Runtime QA project were
stopped. QA volumes were retained; all five original stack containers remained
healthy. The generated Next declaration was restored in the owned checkout,
which was verified clean. Existing user changes were preserved.
