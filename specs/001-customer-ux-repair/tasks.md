---
description: "Implementation tasks for Customer Experience Simplification and UX Repair"
---

# Tasks: Customer Experience Simplification and UX Repair

**Feature**: `001-customer-ux-repair` · **Branch**: `chore/chatbot-ux-constitution`

**Input**: [Spec](spec.md), [plan](plan.md), [research](research.md), [data model](data-model.md),
[traceability](traceability.md), [quickstart](quickstart.md), [conversation contract](contracts/customer-conversation.md),
[transport contract](contracts/commerce-view-transport.md), and [UX Constitution v1.1.0](../../.specify/memory/constitution.md).

**Tests**: Test first. Record baseline behavior and prove new regression assertions fail for
the intended reason before changing production behavior. Retain unchanged protection tests
that already pass. Re-run tests after each change. All checkboxes are pending.

**Organization**: Setup and foundation are charged to P0. Each story is independently
verifiable after its prerequisites. Close P0 before starting P1, and P1 before P2. Polish
and cross-cutting checks close P2.

## Format and path conventions

`- [ ] T### [P?] [USn?] Objective with exact repository file path`

Paths are relative to the repository root. Every task states its prerequisites, verification
and acceptance. Story labels appear only in story phases; shared tasks list the stories they
support in the phase. `[P]` permits concurrency only within the named batch after all listed
dependencies are complete, with disjoint file edits and independent test fixtures. For each
priority gate use the paired evidence format from [quickstart.md](quickstart.md). No live
payments, production credentials, data deletion, schema reset, new dependencies, or
changes to the approved design are part of this task list.

## Phase 1: Setup (shared P0 infrastructure)

**Goal**: Establish a reproducible, isolated baseline before editing production files.

**Independent test**: Use Python 3.12 and pinned dependencies; capture paired before-state evidence or explicitly record a broken baseline fixture.

**Stories supported**: US1–US8; shared fixtures, legacy compatibility and commerce state.

- [X] T001 Record the focused offline baseline with `.github/workflows/tests.yml`, `Dockerfile`, `requirements.txt` and `specs/001-customer-ux-repair/quickstart.md`.
  **Depends on**: —. **Verify and accept**: Run the focused suites or the network-disabled container path; record Python version and any existing failures separately from feature regressions. Do not add dependencies.

- [X] T002 Repair the paired provider fakes in `scripts/beta_storefront_e2e.py` to record actual message IDs, callbacks, edit/markup calls, acknowledgements and injectable transport outcomes.
  **Depends on**: T001. **Verify and accept**: Self-check native fake shapes and positive send IDs; construct inbound taps from emitted controls. Telegram and Bale independently reproduce success, no change, definite rejection and unknown delivery without external calls.

- [X] T003 Repair the historical journeys in `scripts/beta_storefront_e2e.py` and `scripts/beta_commerce_e2e.py` to use recorded controls and the existing sequential address wizard.
  **Depends on**: T002. **Verify and accept**: Run the guarded seed and repaired baseline journeys; omit hard-coded message ID 1 and the one-line address. Treat expected duplicate/stale statuses explicitly, record sanitized pre-change transcripts where the baseline can run, and do not change production behavior to satisfy a fake.

---

## Phase 2: Foundational (blocking P0 state and migration)

**Goal**: Extend the existing chat-state row without changing its current keys or form fields.

**Independent test**: Upgrade an isolated PostgreSQL database from the prior Alembic head; compare old rows before and after and prove the fixture tolerates a null new field.

**Stories supported**: US1–US8; shared fixtures, legacy compatibility and commerce state.

- [X] T004 Add existing-row and new-row compatibility tests in `tests/test_beta_conversation_ux.py`; adapt `tests/schema_support.py` only if its existing fixture needs it.
  **Depends on**: T003. **Verify and accept**: Run pytest before T005. Require the schema check to fail for the absent new field, then accept legacy null rows while existing scope, form and draft fields remain readable.

- [X] T005 Add the “one nullable SQLAlchemy JSON column, `view_state`” to `models/shop_customer_navigation.py` and the additive migration `migrations/versions/20261108v001_customer_view_state.py`; recheck head `20261107u004`.
  **Depends on**: T004. **Verify and accept**: Run the focused schema tests; retain the existing key and fields, including “`query_text` (100 chars), `query_field` (all/name/sku/description), `page` (0…10000 stored zero-based).” No new table, index, enum, backfill or database rewrite.

- [X] T006 Verify the additive upgrade for `migrations/versions/20261108v001_customer_view_state.py` on private PostgreSQL using `specs/001-customer-ux-repair/quickstart.md`, `compose.beta-qa.yml` and `scripts/test_lab_safety.py`.
  **Depends on**: T005. **Verify and accept**: From the real prior revision, seed existing chat rows and valid drafts and apply Alembic upgrade. Record the expected revision and unchanged existing data with null `view_state`; confirm fresh-schema tests separately. Do not test by resetting data or downgrading a live database.

---

## Phase 3: User Story 1 — Recover from an expired button (Priority: P0)

**Goal**: Reject obsolete mutations before effects and keep one authorized, accessible route forward.

**Independent test**: Tap old Add, Confirm and Pay twice, including after an edit that kept the same message ID. Exercise missing/current views, wrong scope and old permitted gallery reads in both adapters.

### Regression tests first

- [X] T007 [P] [US1] Write Telegram transport contract tests in `tests/test_telegram_channel_transport.py`.
  **Depends on**: T006. **Verify and accept**: Run red first for typed outcomes; require correct IDs, text/media/markup edit paths, zero resends on no change or uncertainty and best-effort ack without business replay.

- [X] T008 [P] [US1] Write Bale transport contract tests in `tests/test_bale_channel_transport.py`.
  **Depends on**: T006. **Verify and accept**: Run red first for typed outcomes; cover text/caption/markup, one intentional photo replacement, both callback ack paths including legacy ID prefix `1`, malformed response and rate limits. Unknown or invalid input never implies permission to resend.

- [X] T009 [P] [US1] Write paired stale-view and recovery tests (R-01) in `tests/test_beta_conversation_ux.py`.
  **Depends on**: T006. **Verify and accept**: Run red for same-ID old generation, null or unknown legacy envelope, invalid slot or missing message, expiration, repeated distinct update IDs, a lost/uncertain target and ack failure. Assert zero cart/account/consent/order/payment/delivery deltas, no active markup stripped, and at most one usable visible recovery. Also exercise exhausted/missing recovery and forbid redisclosure after policy changes.

- [X] T010 [P] [US1] Write paired scoped gallery/recovery tests (R-02) in `tests/test_multibot_catalog_acl_offline.py`.
  **Depends on**: T006. **Verify and accept**: Run red for recovery scope; keep only currently eligible old reads, include Telegram photo and Bale text fallback, and prove revoked/foreign Store, bot or user discloses nothing and does not mutate. Keep exact owned after-sales exceptions.

- [X] T011 [P] [US1] Extend ingress isolation tests in `tests/test_runtime_receivers.py`.
  **Depends on**: T006. **Verify and accept**: Run red for stale commerce reaching Runtime fallback. Assert no stale enrollment, suspension, form capture or invoice; fresh intentional workflow exits, published callback ownership, inbox dedup and finance routing still work.

- [X] T012 [US1] Add real PostgreSQL overlap and recovery cases (R-01) in `scripts/beta_storefront_e2e.py`.
  **Depends on**: T009, T011. **Verify and accept**: Run failing expectations before implementation on guarded fake-provider QA: two simultaneous IDs for one write, independent-chat progress, commit boundary, cancelled wait, lease handoff/restart, lost publish and uncertain edit. Verify one business effect for a fresh action and none for obsolete actions, one connection per guarded chat, cleanup and no replay.

### Implementation and verification

- [X] T013 [US1] Extend the typed reply/transport interface in `channels/contracts.py` with navigation, durable event, requested media and temporary native-contact purpose and classified transport outcomes.
  **Depends on**: T007, T008, T009. **Verify and accept**: Run provider contract tests as implementations land. Keep typed shared DTOs SDK-free and existing callback/text/media bounds; separate confirmed edit/send, no change, definite inability, definite failure and unknown.

- [X] T014 [US1] Implement the bounded view envelope and lifecycle in `services/shop_customer_views.py`: exact `v1:<generation>:<slot>`, URL-safe 12-character generation, canonical 0–31 decimal slot and <=64 UTF-8 bytes.
  **Depends on**: T009, T012, T013. **Verify and accept**: Verify parser/lookup, "active and pending view metadata (one each)", "one recovery marker", "allowlisted logical callback slots (at most 32)", "Keep at most one quarantined target", "Cap encoded JSON at 16 KiB", and "New actionable views expire after at most 30 minutes". Match confirmed positive ID, live expiry, scope and slot; reserve/consume before effects, fence publish, reject malformed versions and store only approved routing refs/fingerprints.

- [X] T015 [US1] Implement bounded per-chat coordination in `services/shop_customer_views.py`: local queue and namespaced PostgreSQL session advisory lock on the same ORM connection.
  **Depends on**: T014. **Verify and accept**: Run R-01 lock cases from T012 once integrated; existing handler commits do not release exclusion, unrelated chats progress, no ORM transaction spans navigation I/O, and unlock failure invalidates the connection. Keep the SQLite in-process test path. Bound wait and provider I/O, check receiver lease before protected routing and before publishing, and stop safely if ownership is lost.

- [X] T016 [P] [US1] Implement Telegram result classification and best-effort ack in `channels/telegram.py` using the approved capability evidence.
  **Depends on**: T007, T013. **Verify and accept**: Pass T007: compatible photo and text edits keep the ID, no change adds zero, only verified edit inability permits replacement, and invalid content, throttling or unknown results do not resend.

- [X] T017 [P] [US1] Implement Bale result classification and legacy ack handling in `channels/bale.py` using the approved capability evidence.
  **Depends on**: T008, T013. **Verify and accept**: Pass T008: preserve text/caption/markup and documented replacement preview; no inferred generic media edit, broad 400/404 fallback or ambiguous resend; legacy callback does not block visible recovery.

- [X] T018 [US1] Route exact reserved and legacy commerce callbacks through the guarded path in `services/shop_multibot_supervisor.py` and `services/shop_runtime/ingress.py`.
  **Depends on**: T011, T015. **Verify and accept**: Run T011 and receipt regressions: stale commerce bypasses side-effectful fallback, authentic scope and native finance routes remain intact, prior Runtime receipts still win, and existing fresh transitions out of a workflow remain possible.

- [X] T019 [US1] Bind dispatch and publishing to the authorized generation in `services/shop_multibot_dispatch.py`. Preserve access to long carts and order histories within the 32-slot limit in `services/shop_cart.py` and `services/shop_orders.py`.
  **Depends on**: T010, T015, T016, T017, T018. **Verify and accept**: Run T009–T012: re-resolve Store/bot/user, runtime and block state after queueing, admit only the current slot or audited live-ACL read, consume consequential controls before handlers, publish only proven positive targets via reservation/owner check, and keep durable outputs outside the editable pointer. Verify current cancellation safety without redesigning existing semantics.

- [X] T020 [US1] Render and retire safe stale recovery in `services/shop_multibot_dispatch.py` using the existing permitted Home/after-sales paths.
  **Depends on**: T019. **Verify and accept**: Pass R-01/R-02: reuse current visible feedback when usable; reserve at most one labeled recovery otherwise, including legacy Bale. Keep newer same-ID controls, retire only distinct known old markup best-effort, and let deliberate Home/start recover an uncertain target without auto-resend. Pass paired and PostgreSQL US1 checks before checkout integration.

---

## Phase 4: User Story 2 — Read terms and return to checkout (Priority: P0)

**Goal**: Keep terms reachable from checkout and preserve the exact valid review without recording consent until the explicit order decision.

**Independent test**: On both providers, open long terms in one action, navigate to the last page, return and cancel; then confirm a fresh valid review and repeat with changed terms/quote.

### Regression tests first

- [X] T021 [P] [US2] Write paired one-action terms and recovery tests (R-03, R-04) in `tests/test_beta_terms_navigation.py`.
  **Depends on**: T020. **Verify and accept**: Run red first for lost origin or invalid pages. Test full Unicode terms and Back on each page, same review and selections, optional `/terms`, cancel, missing/changed terms or quote and unavailable checkout; reading/return/cancel creates zero consent, orders and charges. Verify a pre-commit decision presents the expected confirmation, Terms and Cancel actions in order.

- [X] T022 [P] [US2] Extend checkout acceptance/negative tests for R-03/R-04 in `tests/test_beta_checkout_policy.py`, `tests/test_beta_mixed_split.py`, `tests/test_beta_bale_mixed_cart.py` and `tests/test_beta_bale_mixed_payment_guard.py`.
  **Depends on**: T020. **Verify and accept**: Run before implementation; missing policy and stale proof/ownership/eligibility fail closed. Keep manual and instant paths; verify Telegram separate payment parts and Bale separate-order guidance without a charge.

- [X] T023 [P] [US2] Add PostgreSQL checkout policy/decision races and duplicate-outcome tests (R-04, R-11) in `scripts/beta_commerce_e2e.py`.
  **Depends on**: T020. **Verify and accept**: Run new race cases red first in guarded QA. Exercise both orderings of policy insert/save vs. decision, same-version terms content changes, repeated confirm/pay/refund/delivery/settlement and uncertain provider results. Compare durable state and exact fake calls; preserve one authorized outcome and receipts. Existing guard regressions may pass unchanged. Reuse `tests/test_shared_payment_settlement.py`, `tests/test_beta_digital_refund_serialization.py` and `tests/test_shop_delivery_dedup_offline.py` without broad refactors.

### Implementation and verification

- [X] T024 [US2] Extract the scoped read-only review resolver from `services/shop_cart.py` and reuse the existing cart revision, terms fingerprint, quote proof, mode and delivery selections.
  **Depends on**: T021, T022, T023. **Verify and accept**: Use T021/T022 to verify no cart or financial record is created by review/terms; same valid review keeps total, currency and selections. Keep the locked explicit placement path and payment service separate.

- [X] T025 [US2] Carry checkout origin through terms open, pagination, Back and invalid-page recovery in `services/shop_customer_experience.py`.
  **Depends on**: T024. **Verify and accept**: Pass T021: preserve the entire terms text using existing pagination and one visible return action on every page. Re-resolve policy and proof; offer fresh review or allowed Cart/Home/help with an explanation, without implicit consent.

- [X] T026 [US2] Coordinate final decision and policy writers in `services/shop_cart.py` and `services/shop_checkout_policy.py` with the approved stable per-Store shared/exclusive transaction lock.
  **Depends on**: T024. **Verify and accept**: Pass T022/T023 for updates and absent policy rows in both orderings. Preserve cart/catalog lock order, never take cart lock in policy writer, and reject changed terms/quote/scope/availability before explicit consent/order effects. No dashboard contract or payment change.

- [X] T027 [US2] Keep Terms visible and remove command-dependent instructions in `services/shop_checkout_copy.py` and `services/shop_cart.py`.
  **Depends on**: T025, T026. **Verify and accept**: Run R-03/R-04 and `tests/test_beta_checkout_copy.py`; one tap from review, clear amount/currency/delivery and next effect, plus provider limitations before commitment. Retain optional `/terms` and show a fresh decision when required.

- [X] T028 [US2] Close P0 using `scripts/beta_storefront_e2e.py`, `scripts/beta_commerce_e2e.py` and `specs/001-customer-ux-repair/quickstart.md`.
  **Depends on**: T006, T020, T023, T027. **Verify and accept**: Run focused pytest and real PostgreSQL fake journeys for R-01–R-04 and P0 parts of R-11. Require upgrade/legacy recovery, lease and policy race evidence, zero unauthorized or duplicate writes, valid explicit decisions and paired transcripts or equivalent assertions before P1. At cutover review migration-before-receiver ordering, rollback by pause, and old-consumer compatibility before any resume.

---

## Phase 5: User Story 3 — Use a consistent menu for the current shop (Priority: P1)

**Goal**: Make Home and the native keyboard use one ordered effective policy.

**Independent test**: Compare Store default, bot override, disabled Cart, policy drift and contact completion/cancel/exit on both providers.

### Regression tests first

- [X] T029 [P] [US3] Write paired policy and stale-shortcut tests (R-05) in `tests/test_beta_customer_menu.py` and `tests/test_beta_customer_account.py`.
  **Depends on**: T028. **Verify and accept**: Run red for Home/keyboard drift, denied old shortcuts, all enabled destinations in order and contact restoration. Check sender-owned vs. typed/foreign/expired proof, invalid contact and a subsequent unrelated form input.

- [X] T030 [P] [US3] Write Telegram native keyboard assertions (R-05) in `tests/test_telegram_channel_transport.py`.
  **Depends on**: T028. **Verify and accept**: Run red for policy-derived rows. Assert persistent hint where supported, no mixed markup, first install and contact restore, and zero redundant or ambiguous reinstallation.

- [X] T031 [P] [US3] Write Bale native keyboard assertions (R-05) in `tests/test_bale_channel_transport.py`.
  **Depends on**: T028. **Verify and accept**: Run red for policy-derived rows. Assert documented keyboard/remove requests, no reliance on Telegram-only hints, no mixed markup, explicit contact exit and zero ambiguous replay.

### Implementation and verification

- [X] T032 [US3] Build one ordered allowed snapshot using `effective_menu` in `services/shop_customer_menu.py`, render Home from it in `services/shop_channel_catalog.py`, and carry native rows in `channels/contracts.py`.
  **Depends on**: T029, T030, T031. **Verify and accept**: Pass policy tests: Store/Bot override and live capability filtering, identical Persian labels and configured order, all allowed Home destinations, and only a fingerprint plus installation state persisted.

- [X] T033 [P] [US3] Use ordered policy rows in `channels/telegram.py` instead of hard-coded shortcuts.
  **Depends on**: T032. **Verify and accept**: Pass T030; use separate native keyboard installation only on first install, policy drift, contact completion/exit or explicit removal; never mix Reply and Inline or edit in a Reply Keyboard.

- [X] T034 [P] [US3] Use ordered policy rows and explicit restoration in `channels/bale.py` instead of hard-coded shortcuts.
  **Depends on**: T032. **Verify and accept**: Pass T031; preserve documented contact/keyboard removal, never assume Telegram persistence, and never reinstall on an ambiguous result from an obsolete tap.

- [X] T035 [US3] Recheck old labels and restore current policy after contact in `services/shop_multibot_dispatch.py`, `services/shop_customer_views.py` and `services/shop_customer_account.py`.
  **Depends on**: T033, T034. **Verify and accept**: Pass paired R-05: re-evaluate current policy on authorized navigation, distinguish menu labels from separately authorized commands/deep routes, end temporary contact on success/cancel/exit, preserve provenance and never route old shortcut text into another form.

---

## Phase 6: User Story 4 — Return to my search results (Priority: P1)

**Goal**: Preserve query, filter and page through detail and preview without leaking stale input or losing a valid draft.

**Independent test**: From page two of a filtered search, open a product and Back. Repeat with vanished products, expiry and a parked draft.

### Regression tests first

- [X] T036 [P] [US4] Write paired search-context tests (R-06) in `tests/test_beta_customer_search.py`.
  **Depends on**: T035. **Verify and accept**: Run red for exact later-page Back, plain name in one text turn, optional filter, latest ACL, clamped page and empty/expired recovery. Include Telegram edited preview and Bale replaced preview.

- [X] T037 [P] [US4] Write paired search/form interference tests (R-06) in `tests/test_beta_cart_form_navigation.py`.
  **Depends on**: T035. **Verify and accept**: Run red for Home/Cancel/input precedence, stale support/contact/address text, preservation of current cart and valid parked draft values, original expiry and resume step. Expired drafts cannot be silently extended.

### Implementation and verification

- [X] T038 [US4] Isolate address resume metadata and active form ownership in `services/shop_customer_experience.py`, `services/shop_address_wizard.py` and `services/shop_customer_views.py`.
  **Depends on**: T036, T037. **Verify and accept**: Pass T037: park the step, original expiry and origin while preserving `address_draft`; adopt only valid legacy state; keep wizard Back/Cancel/review/explicit save. Navigation wins before text is delivered to a pending step.

- [X] T039 [US4] Preserve search entry/results/detail state in `services/shop_customer_search.py` using existing query/field/page and the approved envelope.
  **Depends on**: T038. **Verify and accept**: Pass T036: keep the “existing 15-minute search TTL”, reuse `query_text`/field/page bounds, disarm input on detail, recheck expiry and scope on Back/paging, clamp/requery once for concurrent empty pages, and offer allowed Search/Browse/Home recovery without touching unrelated data.

- [X] T040 [US4] Carry the scoped search return through product, preview, media and detail routes in `services/shop_channel_catalog.py` and `services/shop_customer_search.py`.
  **Depends on**: T039. **Verify and accept**: Run R-06 on both transports using actual rendered controls; Back restores exact valid query/filter/page or nearest permitted page. Product visibility is checked again, including old gallery reads. This story is testable before the compact rendering change.

---

## Phase 7: User Story 5 — Browse several products without filling the chat (Priority: P1)

**Goal**: Render compact browse/search pages while preserving deliberate media and durable records.

**Independent test**: Browse all nine eligible items, including uncategorized and coverless items, without category selection; request media, navigate away, and compare exact output counts.

### Regression tests first

- [X] T041 [P] [US5] Write paired compact-list and paging tests (R-07) in `tests/test_shop_channel_catalog.py` and `tests/test_beta_customer_search.py`.
  **Depends on**: T040. **Verify and accept**: Run red for default gallery/single result behavior; require up to four eligible items, at least two when two remain, all nine reachable, optional categories and visible position/paging. Include no-cover, uncategorized and disallowed products.

- [X] T042 [P] [US5] Extend provider navigation and failure regressions (R-07/R-08) in `tests/test_telegram_channel_transport.py` and `tests/test_bale_channel_transport.py`.
  **Depends on**: T040. **Verify and accept**: Require Telegram media edit and Bale photo replacement, supported edits/no change add zero, definite fallback adds at most one, and no duplicate on invalid payload, throttling, unknown send or uncertain edit. Assert only one active control set; count setup and deliberate media separately.

- [X] T043 [P] [US5] Write paired durable-content and media tests (R-08) in `tests/test_beta_conversation_ux.py`, `tests/test_beta_paused_customer_support.py`, `tests/test_beta_digital_delivery.py` and `tests/test_beta_dispatch_paid_notification.py`.
  **Depends on**: T040. **Verify and accept**: Run the new cases before changing presentation. Explicit file/gallery reopen works under current ACL; product media, receipts, support history and delivered files remain usable. No edit, delete or automatic duplicate delivery of durable content.

### Implementation and verification

- [X] T044 [US5] Render compact Shop and Search lists via the shared catalog presentation in `services/shop_channel_catalog.py` and `services/shop_customer_search.py`.
  **Depends on**: T041, T042, T043. **Verify and accept**: Pass T041. Keep scoped query/order and detail/media links, four per default page, full names reachable in detail, and explicit bounded gallery. Fit text and controls to shared limits without clipping material checkout information.

- [X] T045 [US5] Use the active-view transport lifecycle for routine browse, preview and cart navigation in `services/shop_multibot_dispatch.py`, `services/shop_channel_catalog.py` and `services/shop_cart.py`.
  **Depends on**: T044. **Verify and accept**: Pass T042/T043: same ID on proven edit/no-op, at most one confirmed replacement, no edit/retry of an unknown target, and no durable output becomes the active pointer. Preserve optional media, bot-scoped files, text fallback and existing checkout/payment paths.

- [X] T046 [US5] Close P1 with the paired R-05–R-08 journey suite in `scripts/beta_storefront_e2e.py` and `specs/001-customer-ux-repair/quickstart.md`.
  **Depends on**: T035, T040, T045. **Verify and accept**: Run focused offline tests and guarded fake journeys; compare labels/order, contact restore, draft/search state, nine products, message/markup counts and durable records on Telegram and Bale. Rerun affected P0 checks. Do not advance until all required automated cases pass.

---

## Phase 8: User Story 6 — Find Account actions by purpose (Priority: P2)

**Goal**: Put Profile and Addresses first and make all other existing Account actions easy to find.

**Independent test**: Reach every allowed Account destination in at most two selections and resume the same valid address step after leaving.

### Regression tests first

- [X] T047 [US6] Write paired Account, contact and address regressions (R-09) in `tests/test_beta_customer_account.py` and `tests/test_beta_cart_form_navigation.py`.
  **Depends on**: T046. **Verify and accept**: Run red first for the flat Account menu; assert at most four choices excluding Home/Back, all allowed actions within two selections, scoped Back, contact exit, invalid input followed by navigation, and safe draft resume. Verify saved physical address reuse, one field per new address step and no shipping prompt for digital-only checkout. Also verify existing link authorization and safe return from denied linking.

### Implementation and verification

- [X] T048 [US6] Group Account choices and wire group-aware Back in `services/shop_customer_account.py` and `services/shop_address_wizard.py`.
  **Depends on**: T047. **Verify and accept**: Pass R-09 using the two approved group purposes, direct Profile/Addresses and existing allowed routes. Keep account linking/verification semantics, review before save, original valid draft step and unmodified unrelated cart data.

---

## Phase 9: User Story 7 — Read clear Persian prompts (Priority: P2)

**Goal**: Explain the current outcome and next permitted action in Persian.

**Independent test**: Compare paired checkout, verification, linked-account and error transcripts without exposing raw identifiers or losing any amounts or terms.

### Regression tests first

- [X] T049 [US7] Write paired Persian copy and safe-error assertions (automated part of R-10) in `tests/test_beta_checkout_copy.py` and `tests/test_beta_customer_account.py`.
  **Depends on**: T048. **Verify and accept**: Run new assertions before copy edits. Verify named actions and currencies, meaningful scoped references, visible next steps and absence of raw provider diagnostics, internal IDs and unexplained Contact/Client jargon.

### Implementation and verification

- [X] T050 [US7] Refine touched checkout, account and verification copy in `services/shop_checkout_copy.py`, `services/shop_customer_account.py` and `services/shop_cart.py`.
  **Depends on**: T049. **Verify and accept**: Pass T049; explain provider limitations and the order/payment effect, retain exact material terms and amount/currency, use a scoped shopper-facing linked-account label and explain why verified contact is needed.

- [X] T051 [US7] Refine touched stale, invalid input and unavailable/empty recovery messages in `services/shop_multibot_dispatch.py`, `services/shop_customer_experience.py`, `services/shop_customer_search.py` and `services/shop_address_wizard.py`.
  **Depends on**: T049, T050. **Verify and accept**: Run paired error/copy/form tests; customer receives a plain explanation and authorized next action. Keep valid entries and distinguish uncertain outcomes from failed operations; no auto-retry or false success.

---

## Phase 10: User Story 8 — Recover on a narrow screen and with assistive technology (Priority: P2)

**Goal**: Make touched choices readable and accessible, and preserve safe state across failed or abandoned input.

**Independent test**: On each native client verify stale recovery, terms/checkout, search and Account on a narrow supported screen and with available assistive controls.

### Regression tests first

- [X] T052 [US8] Write paired automated label, form and accessibility contract checks (R-10) in `tests/test_beta_conversation_ux.py`, `tests/test_beta_terms_navigation.py` and `tests/test_beta_cart_form_navigation.py`.
  **Depends on**: T051. **Verify and accept**: Run checks before presentation corrections. Require text labels and named recovery, readable mixed-script text fixtures, full terms via reachable pages, explicit Home/Back/Cancel as applicable, and no stale form consuming input for a new journey. Do not treat snapshots as native accessibility proof. Treat right-to-left rendering as a native check; automated tests cover text content and controls.

### Implementation and verification

- [X] T053 [US8] Apply small presentation corrections needed for the text/RTL contract in `services/shop_customer_experience.py`, `services/shop_checkout_copy.py`, `services/shop_customer_account.py` and `services/shop_channel_catalog.py`.
  **Depends on**: T052. **Verify and accept**: Pass T052. Text alone conveys action/outcome without relying on emoji or color, amounts and order references retain meaning, and required text is not clipped. Preserve control order, access and backend behavior.

- [ ] T054 [US8] Perform the native and Persian review for R-10 and native exceptions using `specs/001-customer-ux-repair/quickstart.md`, `specs/001-customer-ux-repair/contracts/customer-conversation.md` and `dashboard-next/components/blocks/customer-experience-policy-panel.tsx` (read-only).
  **Depends on**: T053. **Verify and accept**: Use separately authorized non-production test bots; review Telegram and Bale independently, with a Persian reviewer, on narrow screens and available screen reader/keyboard navigation. Record versions and native findings for terms, next action, mixed-direction amounts, preview, contact restoration and legacy ack where available. No live charges; unavailable cases stay unverified.

---

## Phase 11: Polish & cross-cutting regression (P2 closure)

**Goal**: Close the full regression and review gates without widening the feature.

**Independent test**: Compare both providers and all relevant durable outcomes with the pre-change baseline; distinguish automated, PostgreSQL and native evidence.

**Stories supported**: US1–US8; all priority gates.

- [X] T055 Run the complete paired commerce safety regression (R-11) in `scripts/beta_commerce_e2e.py`, `scripts/beta_digital_refund_e2e.py` and `scripts/beta_account_notifications_e2e.py`.
  **Depends on**: T028, T046, T053. **Verify and accept**: On guarded PostgreSQL with fake transports, replay confirmation, refund, delivery and settlement using fresh synthetic fixtures; assert exact counts, one authorized outcome and intact receipts. Include Telegram native invoice semantics and existing Bale eligible payment/mixed-cart guards; no real invoice or charge.

- [X] T056 Close P2 with `specs/001-customer-ux-repair/quickstart.md`, `specs/001-customer-ux-repair/traceability.md` and `.specify/memory/constitution.md`.
  **Depends on**: T053, T055. **Verify and accept**: Run `python -m pytest -q tests` and review all 11 paired cases, migration/legacy-state proof, 8 outcomes and 13 principles. Require before/after evidence for state, labels/order, controls, messages and durable records. Review T054 evidence separately. If unavailable, keep T054 open as a release requirement and record the gap.

## Dependencies & execution order

| Checkpoint | Scope | Gate |
| --- | --- | --- |
| Setup and foundation | T001–T006 | Fixture baseline plus actual additive upgrade proof. |
| P0 | US1 T007–T020 → US2 T021–T028 | T028: paired R-01–R-04 and P0 portion of R-11; no P1 before closure. |
| P1 | US3 T029–T035 → US4 T036–T040 → US5 T041–T046 | T046: paired R-05–R-08 and affected P0 regressions. |
| P2 | US6 T047–T048 → US7 T049–T051 → US8 T052–T054 → cross-cutting T055–T056 | T056: full suite, paired outcomes, constitution review and native evidence status. |

**Parallel examples by story**: US1 T007–T011 after T006 and adapter tasks T016/T017
after the shared contract; US2 T021–T023 after T020; US3 T029–T031 after T028 and
T033/T034 after T032; US4 T036/T037 after T035; US5 T041–T043 after T040.
Use independent process/fake fixtures; serialize actual guarded PostgreSQL QA operations
that share a seed. US6, US7 and US8 are serial red/green and review sequences because
they share Account, checkout or navigation surfaces.

## Coverage and evidence

### Functional requirements

| Requirement | Implement or preserve | Verify |
| --- | --- | --- |
| FR-001 | T014, T018–T019 | T009–T012, T028 |
| FR-002 | T019–T020 | T009–T010, T028 |
| FR-003 | T014–T020 | T007–T009, T012, T028 |
| FR-004 | T025, T027 | T021, T028 |
| FR-005 | T024–T025 | T021–T023, T028 |
| FR-006 | T024, T026 | T021–T023, T028, T055 |
| FR-007 | T024, T027, T050 | T022–T023, T028, T049, T055 |
| FR-008 | T032–T035 | T029–T031, T046 |
| FR-009 | T033–T035 | T029–T031, T046, T054 |
| FR-010 | T039–T040 | T036, T046 |
| FR-011 | T038–T039 | T036–T037, T046 |
| FR-012 | T039 | T036, T046 |
| FR-013 | T044 | T041, T046 |
| FR-014 | T016–T017, T045 | T042, T046 |
| FR-015 | T016–T020, T045, T051 | T007–T009, T012, T042–T043, T055 |
| FR-016 | T019, T040, T044–T045 | T041–T043, T046, T055 |
| FR-017 | T048 | T047, T056 |
| FR-018 | T050–T051 | T049, T054 |
| FR-019 | T053 | T052 (automated), T054 (native) |
| FR-020 | T035, T038–T039, T048, T051, T053 | T029, T036–T037, T047, T052, T054 |
| FR-021 | T018–T020, T024–T026, T035, T045, T048 | T009–T012, T021–T023, T029, T043, T047, T055–T056 |
| FR-022 | T016–T017, T027, T032–T035, T045, T050 | All paired cases below; T028, T046, T054–T056 |

### Paired Telegram/Bale regression cases

| Case | Explicit test tasks | Expected evidence |
| --- | --- | --- |
| R-01 | T007–T009, T012, T028 | Same-ID/stale/current-or-missing views, duplicate taps, legacy ack and PostgreSQL handoff. |
| R-02 | T010, T028 | Authorized old gallery reads only; revoked and foreign scope disclose nothing. |
| R-03 | T021–T022, T028 | Long terms, one-action return, cancel with zero writes, fresh decision in both order modes. |
| R-04 | T021–T023, T028 | Invalid page, changed or missing terms/quote, unavailable checkout, and native mixed-cart limits. |
| R-05 | T029–T031, T046, T054 | Current Store/Bot policy, obsolete shortcut refusal and native contact restoration. |
| R-06 | T036–T037, T046 | Search return after edit or replacement, expiry/clamp and no form/draft loss. |
| R-07 | T041–T042, T046, T054 | Nine products and exact edit, no-change, replacement and ambiguity counts. |
| R-08 | T042–T043, T046 | Native media variants and no loss/replay of requested or durable content. |
| R-09 | T047, T056 | All allowed Account actions, verified contact exit, address continuity and recovery. |
| R-10 | T049, T052, T054 | Automated text/action assertions plus separate Persian and native accessibility observations. |
| R-11 | T023, T028, T055 | PostgreSQL commerce races, one authorized outcome and intact receipts. |

### Measurable outcomes: automated vs. manual

| Outcome | Automated assertion | Manual or native evidence |
| --- | --- | --- |
| SC-001 | T009–T012, T028: zero stale business mutations; at most one usable recovery; no repeats. | T054: actual recovery and legacy Bale feedback where available. |
| SC-002 | T021–T023, T028: one tap/zero typed commands; every page returns; zero read-side writes. | T054: full terms and readable return controls in both clients. |
| SC-003 | T029–T031, T046: zero forbidden labels; same ordered allowed labels/actions. | T054: policy setup and actual native keyboard and contact restoration. |
| SC-004 | T036–T037, T046: exact Back context, allowed clamp/expiry and safe drafts. | T054: find Search/Back/recovery on the narrow supported client. |
| SC-005 | T041–T043, T046: nine reachable products; at least two when possible; edit/no-op +0 messages and definite fallback at most +1. | T054: confirm actual preview/edit or replacement behavior. |
| SC-006 | T047, T056: at most four choices, at most two selections, same valid resume step. | T054: Account groups and recovery readable and discoverable. |
| SC-007 | T049, T052: readable control text, required terms/actions present, currencies/references retained, no diagnostics. | T054: Persian reviewer can identify primary action, checkout effect and next recovery; actual RTL/narrow and assistive reachability. |
| SC-008 | T009–T012, T023, T043, T055–T056: scoped business state and exact call counts; no receipt/media loss or duplicate side effects. | Review paired transcripts or equivalent assertions; no live financial validation or charges. |

### Constitution v1.1.0 review gates

| Principle | Primary evidence tasks |
| --- | --- |
| I. Minimal Cognitive Load | T041, T047, T052: one primary task/input and no competing duplicate controls. |
| II. Progressive Disclosure | T036, T041, T047: ordinary search first, optional filters/categories/gallery, grouped secondary choices. |
| III. Conversation First | T021, T037, T047, T052: visible controls, ordinary text, command/navigation precedence and one field per address step. |
| IV. Predictable Navigation | T029–T031, T036–T037, T047: allowed Home/keyboard, Back, Cancel and exact valid resume. |
| V. Contextual Actions | T009–T012, T041–T042: current scoped slots, stale write denial and authorized old gallery reads. |
| VI. Minimal Message Clutter | T007–T009, T042–T043, T055: edit/no-op/definite/unknown counts and durable history intact. |
| VII. Clear Product Discovery | T036, T041, T043: all eligible products, no forced category, media remains reachable. |
| VIII. Low-Friction Checkout | T021–T023, T047, T055: one-action terms, totals and effects, saved/new/digital address paths, one authorized outcome. |
| IX. Recoverable Errors | T009, T021, T036–T037, T042, T052, T054: usable next steps, preserved entries and no uncertain replay. |
| X. Security at the Point of Risk | T009–T012, T021–T023, T029, T047, T055: scoped actions, verified contact/linking, consent and commerce guards. |
| XI. Telegram and Bale Parity | T028, T046, T054–T056: equivalent meaning/outcomes with documented, verified provider differences. |
| XII. Accessible and Localized Interaction | T049, T052, T054: Persian text, required terms, mixed direction and native assistive checks. |
| XIII. Plain Customer Language | T049, T052, T054: clear action and outcome, legitimate references, no internal diagnostics. |

## Implementation strategy

- **First independently testable slice:** US1 after setup and foundation. **P0 MVP gate:**
  US1 and US2 together, including private PostgreSQL and migration verification.
- Deliver P1 and P2 in order; keep the current finance, refund, cancellation, delivery and
  Runtime semantics, with no unrelated redesign. Use PEP 8, PEP 257 and typed new interfaces.
- Watch the approved high-risk areas: migration/cutover and lease handoff (T006/T012/T028),
  terms policy and payment races (T023/T026), ambiguous edits (T042), and native
  accessibility/capability evidence (T054). If native coverage is unavailable, record the
  missing evidence; it cannot be substituted by fake results or marked passed.

## Implementation evidence

| Analysis finding | Resolution |
| --- | --- |
| A view's 32-slot bound could strand controls in existing large carts and order histories. | T019 keeps all previously reachable lines and orders through bounded pages. |
| Synthetic journeys used obsolete provider message IDs and a retired address input format. | T002/T003 use actual rendered controls and the current address wizard. |
| The historical migration chain contains SQLite DDL. | T006 verifies the additive revision against the prior schema bootstrapped in private PostgreSQL and preserves a seeded draft. |
| T056 depended on native review while also allowing native omissions. | T054 tracks native release evidence separately from the automated closure in T056. |

The analysis found task coverage for 22/22 requirements, all 11 paired scenarios and
all eight outcomes. The requirements checklist passed 16/16. The authorized workflow
resolved the findings above before their respective gates.

| Gate | Evidence |
| --- | --- |
| P0 | 193 focused tests passed in Python 3.12 Docker. Private PostgreSQL passed the additive upgrade with an unchanged draft and null metadata, paired storefront and callback races, all four Terms/provider/mode combinations, both checkout policy race orderings, and fake-provider commerce settlement, refunds and delivery replay. |
| P1 | Menu/transport checkpoint 82 passed, search/catalog/forms 77 passed and requested-media/gallery 10 passed. Private PostgreSQL passed keyboard, search and discovery for both providers, including edit counts, definitive replacement, uncertainty and durable media. |
| P2 | 82 focused tests passed. Three guarded PostgreSQL runners passed for commerce, digital refund and Account/notifications. Native client evidence T054 remains open for a Persian narrow-screen and assistive review and actual provider keyboard/media/legacy-ack behavior. |
| Final | 1,458 tests passed in isolated Python 3.12 Docker, with 12 collection warnings from four workers reporting the same existing helper classes. The exact final code also passed Python compilation and Git whitespace checks. Linux shell line endings were normalized only in the disposable test snapshot. |
