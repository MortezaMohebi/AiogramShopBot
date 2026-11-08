# Implementation Plan: Customer Experience Simplification and UX Repair

**Feature**: `001-customer-ux-repair` | **Branch inspected**: `chore/chatbot-ux-constitution` (`e636f4e`) | **Date**: 2026-11-08

**Input**: [Approved specification](spec.md) and [UX Constitution v1.1.0](../../.specify/memory/constitution.md).

## Summary

Deliver the eight stories in P0 → P1 → P2 order. Keep one active authorized commerce view
per private conversation, preserve checkout origin and its existing explicit consent
transaction, and reuse current menu policy, search, catalog, address and Account flows.
Share customer intent across Telegram and Bale; isolate transport capabilities and fallbacks
in each adapter. Keep published workflows, durable records and financial ingress separate.

## Technical Context

**Language/Version**: Python 3.12 (CI and container); PEP 8, PEP 257, annotations on new
interfaces and existing repository conventions. No Next.js changes planned.

**Primary Dependencies**: aiogram 3.14.0, aiohttp (Bale), SQLAlchemy 2.0.36,
Alembic 1.14.0 and PostgreSQL. No new package or provider integration.

**Storage**: Existing bot/customer chat state and domain tables. One nullable JSON field on
the chat-state row; no backfill, new table or Redis dependency for storefront navigation.

**Testing**: pytest 8.4.2 and pytest-asyncio 1.2.0, paired fake transports, guarded PostgreSQL
Compose runners and separately recorded native accessibility/capability checks.

**Target Platform**: Existing Python backend and both private-chat clients (Telegram, Bale).
Existing dashboard menu and checkout policies supply acceptance inputs.

**Project Type**: Multi-bot conversational commerce; shared orchestration and provider adapters.

**Performance Goals**: Zero new messages on supported edits/no-op; at most one confirmed
replacement per navigation transition and one usable stale recovery where needed. Bound view
state and queue capacity; no global chat lock or unsupported latency/SLA claim.

**Constraints**: Current authorization, verification, consent, settlement, payment, refund,
delivery, workflows and durable customer data stay intact. No OTP, Mini Apps, live charges,
or unrelated dashboard/API redesign. Unknown transport outcomes never trigger automatic
financial, delivery or navigation replay.

**Scale/Scope**: 8 stories, 22 requirements, 8 measurable outcomes and 11 paired regression
scenarios. Routine browsing/Account/checkout interactions and their existing guarded paths.

## Constitution Check

Pre-research gate: all 13 principles apply; priority and boundaries follow the approved
spec. Research resolved provider and persistence choices. Post-design evaluation below
passes at plan level; each listed check remains required as implementation evidence.

| Principle | Design decision and required evidence |
| --- | --- |
| I. Minimal Cognitive Load | One scannable list or focused view, four Account choices at most; count choices/messages in R-07 and R-09. |
| II. Progressive Disclosure | Optional category/filter/gallery and grouped Account choices; confirm plain search starts immediately and each allowed action stays reachable (R-06–09). |
| III. Conversation First | Native text and contextual buttons; no external app or command dependency for checkout; verify the paired terms and address journeys (R-03, R-09). |
| IV. Predictable Navigation | Stable allowed shortcuts, scoped search Back, explicit Cancel and resume; paired policy/draft/expiry checks (R-05–06, R-09). |
| V. Contextual Actions | Bind action slots to current view and effective policy. Keep older authorized media reads as narrow exceptions; assert exactly the live controls, including same-ID revisions (R-01–02, R-07). |
| VI. Minimal Message Clutter | Edit/no-op where supported, at most one definite replacement, durable content excluded from edits; compare paired counts and preservation (R-07–08, R-11). |
| VII. Clear Product Discovery | Multi-product pages without forced category and with optional permitted media; reach nine eligible products including no cover/category (R-06–08). |
| VIII. Low-Friction Checkout | Terms one tap and Back every page; preserve totals, currency, delivery and explicit acceptance. Check both order modes and native provider split behavior (R-03–04, R-11). |
| IX. Recoverable Errors | One permitted recovery for stale/invalid/empty or changed review, no replay on uncertainty. Check current, missing, unknown and unavailable paths (R-01, R-04, R-06–07, R-10). |
| X. Security at the Point of Risk | Existing authorization, verified-contact, quote, consent, settlement and idempotency stay authoritative; consume stale/duplicate controls before effects (R-01–05, R-11). |
| XI. Telegram and Bale Parity | Same intent and business outcomes under equivalent policies, with documented provider exceptions; run all paired cases and record capability evidence separately. |
| XII. Accessible and Localized Interaction | Text labels, Persian RTL, readable mixed-direction amounts and visible recovery; paired native review including narrow screen and available assistive navigation (R-10). |
| XIII. Plain Customer Language | Plain outcome and next step, no raw provider errors/internal IDs; material terms and legitimate references stay visible (R-03–04, R-10). |

The constitution's audit mentions broader review of cancellation of unpaid orders. The
approved spec excludes cancellation redesign: preserve existing cancellation semantics and
guards while preventing stale invocation. No conflict with the scoped feature or change
to the constitution is required. Before implementation approval, retain paired
before/after transcripts or equivalent assertions, exact control order and message
counts, state/record changes, and dashboard policy configuration.

## Project Structure

### Documentation (this feature)

- [research.md](research.md): source inventory, provider evidence, alternatives and risk register.
- [data-model.md](data-model.md): scoped state, migration and concurrency lifecycle.
- [contracts/customer-conversation.md](contracts/customer-conversation.md) and
  [contracts/commerce-view-transport.md](contracts/commerce-view-transport.md).
- [quickstart.md](quickstart.md): commands and acceptance evidence.
- [traceability.md](traceability.md): FR-001–FR-022, SC-001–SC-008 and R-01–R-11.
- `tasks.md` is generated separately by `$speckit-tasks`.

### Source Code (repository root)

| Location | Planned role |
| --- | --- |
| `channels/contracts.py`, `channels/telegram.py`, `channels/bale.py` | Extend reply intent and typed transport outcomes; provider-specific ack, edit, media and keyboard behavior. |
| `services/shop_multibot_dispatch.py`, `services/shop_multibot_supervisor.py`, `services/shop_runtime/ingress.py` | Current scope, ingress ownership, per-chat guarded dispatch, stale recovery and transport coordination. |
| New `services/shop_customer_views.py`; `models/shop_customer_navigation.py`; new `migrations/versions/20261108v001_customer_view_state.py` | Small typed state/lock helper, existing chat-state extension and additive migration. |
| `services/shop_cart.py`, `services/shop_checkout_policy.py`, `services/shop_customer_experience.py`, `services/shop_checkout_copy.py` | Terms origin, read-only checkout resolution, explicit decision guard and copy. |
| `services/shop_customer_menu.py`, `services/shop_customer_search.py`, `services/shop_channel_catalog.py`, `services/shop_address_wizard.py`, `services/shop_customer_account.py` | Policy-driven navigation, compact views, scoped return context, form ownership and Account grouping. |
| `tests/` existing suites listed in traceability; `tests/schema_support.py` if its fixture needs the new model field; `scripts/beta_storefront_e2e.py`, `scripts/beta_commerce_e2e.py` | Paired fake transports, fixture maintenance, PostgreSQL races and durability tests. |
| `channels/shop_payment_dispatch.py`, `channels/media_policy.py`, `services/shop_bot_catalog_acl.py`, settlement/refund/delivery services, dashboard policy UI/API | Preserve as dependency/validation surfaces; no business or dashboard change planned. |

**Structure Decision**: Extend the shared dispatcher and two existing provider adapters.
Use one helper for the new state lifecycle and the current flows for domain operations.
Do not create a second routing framework, separate catalog engine, or parallel payment path.

## Implementation groups

### P0 — US1 stale controls and US2 checkout terms

**Affected files:** dispatcher, supervisor, Runtime ingress, chat-state model and migration,
view helper, reply contract, adapters, cart, checkout policy, customer experience, checkout
copy and P0 tests/runners from the source table.

1. Land additive schema and fixtures. Introduce the guarded interactive path and compact
   current-view slots. Preserve workflow inbox and financial routing. Classify reserved
   commerce callbacks before side-effectful Runtime fallback; stale callbacks cannot enroll
   the shopper, suspend a workflow, clear a form, call a mutating handler, or send an invoice.
   Retain explicitly allowed gallery reads and current paid-order refund/paused routes.
   Re-resolve live scope after queueing. Best-effort ack; check generation and authorize a
   safe current/recovery view; consume consequential generation before the handler.
   Keep the existing full cart and recent-order limits reachable through bounded pages
   where their action counts would otherwise exceed 32 slots.
2. Implement typed provider outcomes and the minimum recovery rendering needed for P0.
   Track current view only on confirmed publish; separate durable receipts/requested media
   from edit targets. Repeated obsolete controls cannot replay an uncertain action or remove
   current markup. Keep same-chat ordering through lease handoff, and bound waits/pool use.
3. Factor read-only quote preparation from checkout and use it for terms open/page/return.
   Keep terms content in existing pagination, with Back from every page, including recovery
   on changed policy, price, availability or page. Preserve the existing signed quote proof,
   cart lock, terms fingerprint and explicit order/consent transaction. For concurrent policy
   saves, share a stable per-Store transaction lock between final decision (shared) and
   policy writers (exclusive), before policy reads/writes; this also covers missing policy
   rows. Keep existing cart and catalog lock order, and never take a cart lock in a policy
   writer. Test both orderings and avoid introducing lock cycles. This changes coordination,
   not policy rules or the dashboard contract. No charge from viewing terms or quote.
4. Repair fake IDs/markup/wizard inputs early; add paired fresh/stale/duplicate/unauthorized,
   current/missing/unknown recovery, workflow/finance isolation and terms drift cases.
   Exercise PostgreSQL locks, failure/cancellation, lost lease, policy insert/save races
   and zero domain deltas on stale or review-only flows.

**Dependencies and risks:** provider outcome classification, production migration ordering,
receiver claim ownership, existing cart/terms/mixed-payment guards. Legacy commerce writes
fail closed and recover. Simulate old controls and concurrently delivered distinct updates.

**Acceptance and done:** FR-001–007 and relevant FR-015/021/022 behavior; SC-001/002,
security portions of SC-008; paired R-01–04 plus P0 subset of R-11. Explicit valid decisions
still work in manual/instant modes with native differences. Scope, one recovery, zero
unapproved writes, unknown-result quarantine, migration and PostgreSQL evidence reviewed
before starting P1.

### P1 — US3 menus, US4 search context and US5 compact browsing

**Affected files:** menu, catalog, search, address wizard and customer experience; dispatch,
reply contract and both adapters for keyboard and presentation; existing menu/search/form,
transport/catalog/media tests and storefront runner.

1. Resolve an ordered menu snapshot from the existing Store/Bot policy service. Render Home
   and persistent keyboard from the same snapshot. Restore after native contact, re-evaluate
   policy drift on next authorized navigation, and guard old labels without disabling
   separately authorized deep flows. Keep Contact native and verification unchanged.
2. Keep 15-minute search context separate from address resume. Share compact result/catalog
   presentation using existing scoped queries. Search accepts a plain name; optional field
   controls and new search stay reachable. Preserve origin through detail/media, clamp Back,
   handle changed ACL/empty/expired pages and park valid unrelated address inputs.
3. Default browsing and search use one list view (up to four eligible products), text labels
   and page position; category/gallery are optional. Update the active view on supported
   list/cart navigation, replace once where justified, preserve product previews, text
   fallback and deliberately requested gallery/media. Measure routine navigation, keyboard
   setup and durable sends separately.

**Dependencies and risks:** P0 view/transport lifecycle and verified claim; policy/contact
interplay, retired labels, mixed form state, differences in Bale media replacement. Use
current storefront fixture with policy updates and nine eligible products.

**Acceptance and done:** FR-008–016 and related FR-020–022; SC-003–005 and media portion of
SC-008; paired R-05–08. Verify exact valid search Back, action order, zero forbidden shortcuts,
one active set of controls, bounded message counts, and no unintended durable media loss.

### P2 — US6 Account, US7 Persian copy and US8 accessibility

**Affected files:** Account, address wizard, customer experience, checkout copy and touched
recovery/menu/search strings in their owning services. Extend paired Account, form, checkout
copy and transcript tests; use the existing dashboard policies for native review.

1. Keep Profile and Addresses direct, group remaining actions by the two purposes in the
   conversation contract, preserve existing exact routes and group-aware Back. Use current
   capabilities and authorization, and check every previously permitted action. Keep
   address steps, review, save and resume; invalid form input cannot trap the customer.
2. Apply plain Persian wording to touched paths. Replace raw errors and internal identifiers
   with actionable text or meaningful scoped names. Keep contractual terms, clear verification
   reason, amounts and currency; test text labels, narrow RTL, mixed-direction references
   and available assistive navigation on both clients.
3. Run full offline and paired regressions and compare native/simulated evidence against
   the constitution, including real-client capabilities that fakes cannot prove.

**Dependencies and risks:** P0 security/recovery and P1 keyboard/form state; copy changes
could hide material information; pairing does not imply native UI sameness.

**Acceptance and done:** FR-017–022; SC-006/007 plus R-09–10; repeat R-11 and all P0/P1
regressions. Four initial Account choices at most and all allowed actions within two
selections; no draft loss, unreachable required terms, raw error or duplicate business
effect. Separate unavailable native observations from confirmed results.

## Complexity Tracking

No constitution exception. The nullable field and per-chat coordination are needed for
same-message revision safety, restart recovery and independently expiring context. They
reuse the current DB/receiver boundaries; [research.md](research.md) records alternatives
and release risks. Install the additive migration before switching receivers. Keep it
during code rollback and assess legacy callbacks before allowing an older consumer to
resume; use receiver pause to contain a failed cutover without deleting data.

## Readiness

Technical design is ready for `$speckit-tasks`. There is no open design blocker. Required
implementation evidence includes true PostgreSQL concurrency and migration checks, repaired
paired fake journeys and separately authorized native provider/accessibility verification.
No implementation or live validation is represented as complete.
