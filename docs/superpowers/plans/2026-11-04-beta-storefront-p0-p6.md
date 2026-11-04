# Beta Storefront P0–P6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one Store-aware, security-gated Telegram/Bale commerce journey with six complete customer menus and Next.js management.

**Architecture:** Shared SQLAlchemy Store-owned domain models, trusted BotContext, a declarative Bot-menu policy, shared Experience Router, and provider-native adapters. Admin mutations bind to signed StoreContext. Fresh Beta schema only, no new Alembic revisions.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, FastAPI, Aiogram 3, Next.js TypeScript/React, Postgres 16, Redis, official Telegram/Bale Bot APIs.

**Spec:** `docs/superpowers/specs/2026-11-04-beta-storefront-design.md`

## Global Constraints

- Preserve provider credentials, live payment receipts, and all pre-existing data unless user separately authorizes a destructive reset on a known Beta database.
- Never use Telegram fiat or Store Credit to sell digital goods within Telegram; Stars XTR.
- Use authenticated BotContext and allowlisted SQL, no client-selected Bot or Store.
- No auto retry of uncertain invoice, payment, refund or outbound message.
- Keep previous Draft PRs and code paths stable.
- New tables only in `Base.metadata`; fresh-schema bootstrap is required for disposable Beta.
- PEP 8 and 257, auditable mutation rules, Persian RTL labels and accessible Next.js inputs.

## Review Focus

- [ ] Identical user IDs in two distinct bots have isolated accounts.
- [ ] Stale button cannot access a denied or cross-Store Product.
- [ ] Callback payload cannot exceed Telegram 64 UTF-8 bytes.
- [ ] Payment success is independent of notification delivery/timeout.
- [ ] New chat form does not intercept unrelated legacy Telegram text.

---

### Task P0: Tenant and update transport security

**Files:** `services/shop_bot_catalog_acl.py`, `services/shop_channel_catalog.py`, `services/shop_relay_routing.py`, `services/shop_cart.py`, `tests/test_beta_p0_security.py`.

**Interfaces:** `CatalogScope`, `resolve_scope(db,bot_id)`, `permitted_product_clause(scope)` and `BotContext`.

- [ ] Write regression tests for cross-Store ACL and failover allowlist.
- [ ] Run tests and observe RED.
- [ ] Remove default Store gate, enforce Store FK predicates and recheck stale cart callbacks.
- [ ] Run tests and verify GREEN plus existing tests.
- [ ] Commit P0 and record any unverified test dependencies.

### Task P1: Shared customer Home, menu policy and product search

**Files:** `models/shop_customer_experience.py`, `services/shop_customer_menu.py`, `services/shop_customer_search.py`, `services/shop_channel_catalog.py`, `services/shop_multibot_dispatch.py`, `dashboard/shop_customer_experience_api.py`, `dashboard-next/app/(console)/bots/[id]/page.tsx`, related tests.

**Interfaces:** `CustomerMenuPolicy.resolve()`, `CustomerExperienceFlow.reply(event, session) -> BotReply | None`.

- [ ] Write tests for menu visibility, 64-byte callback payload and ACL-filtered search.
- [ ] Run tests (RED).
- [ ] Implement menu rules, search FSM and admin menu configuration; wire to both adapters.
- [ ] Run tests (GREEN), commit.

### Task P2: Account, AddressBook and Wishlist

**Files:** `models/shop_customer_experience.py`, `services/shop_customer_account.py`, `dashboard/shop_customer_experience_api.py`, Next.js Customer UI and tests.

**Interfaces:** `customer_for_bot()`, `account_actions()`, `StoreCustomerAddress`, `StoreWishlistItem`.

- [ ] Write negative ownership tests.
- [ ] Run tests (RED).
- [ ] Implement bot-scoped account/menu actions and admin read views; secure CRUD.
- [ ] Run tests (GREEN), commit.

### Task P3: Store checkout policy and native-payment conditions

**Files:** `models/shop_customer_experience.py`, `services/shop_checkout_policy.py`, `services/shop_cart.py`, `services/shop_orders.py`, Dashboard Store checkout policy, tests.

**Interfaces:** `checkout_mode(store_id)` returns `manual|instant` and prevents digital fiat/credit bypass.

- [ ] Write RED tests for manual default, instant gating and payment constraints.
- [ ] Apply policy at order placement and expose Store-only admin controls.
- [ ] Run GREEN tests, commit.

### Task P4: Tickets and fulfillment

**Files:** `models/shop_customer_experience.py`, `services/shop_customer_support.py`, `services/shop_fulfillment.py`, admin APIs, dashboard pages and tests.

**Interfaces:** `create_ticket`, `append_message`, `record_fulfillment_event`.

- [ ] Write RED ownership and state-transition tests.
- [ ] Implement Store/Customer scoped ticket and shipment records; no digital delivery without paid receipt.
- [ ] Run GREEN tests, commit.

### Task P5: Consent, notifications, stock alerts

**Files:** `models/shop_customer_experience.py`, `services/shop_customer_notification.py`, `services/shop_engagement_flow.py`, Dashboard pages, tests.

- [ ] Write RED tests for Bot-scoped marketing opt-in, alert dedup and paused delivery.
- [ ] Implement opt-in state and safe, no-blind-retry delivery queue, commit after GREEN.

### Task P6: Unified Telegram/Bale handlers, tests and Beta bootstrap

**Files:** `run.py`, `bot.py`, `services/shop_multibot_dispatch.py`, `channels/telegram_handlers.py`, `channels/bale.py`, `db.py`, `scripts/setup_codespace.sh`, `tests/test_beta_customer_e2e.py`, docs.

- [ ] Write RED end-to-end menu tests for both platforms and historical payment regression.
- [ ] Integrate CustomerExperienceFlow, normalize legacy /start and pay support/terms actions.
- [ ] Add explicit safe fresh-Beta schema initialization and scripts; never drop unknown DBs.
- [ ] Run Python and Next.js full suites, PostgreSQL smoke and provider simulation when available.
- [ ] Request code review; leave Draft until all gates pass.

## Execution ledger

- [ ] P0
- [ ] P1
- [ ] P2
- [ ] P3
- [ ] P4
- [ ] P5
- [ ] P6

**Environment note:** GitHub connector supports source changes but not Codespaces commands. Local test execution requires a source checkout and dependencies; the code must not be declared tested unless command output is observed.
