# Registry-only Legacy Removal Implementation Plan

> For agentic workers: execute task by task with regression tests and whole-branch review.

**Goal:** Remove the historical application, compatibility execution paths and disconnected old schema across the repository, preserving modern Telegram/Bale commerce and Workflow/Action/MCP functionality.

**Architecture:** Every bot is registered explicitly and every business operation carries authenticated bot/Store scope. Fresh installations seed Store/UOM/admin access, never environment-owned bots. Historical schema cleanup inventories references and fails closed before deleting anything used by modern commerce.

**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL, Next.js 16.4.3/React 19.2.

**Spec:** User request on 2026-11-07 and explicit scope selection: entire repository, including compatibility modules and old schema.

## Global constraints
- Preserve owner password/MFA/session and modern Store/product/order/payment data.
- No live messenger sends/payments, provider webhook takeover, public-port exposure or customer workflow activation.
- Preserve unrelated dirty browser loading harness.
- Keep old DB backup private; no credentials in commits or logs.
- No silent platform-derived bot ownership and no provider-token fallback to environment.
- Historical QA evidence remains historical, not rewritten to claim new acceptance.

## Review focus
- Missing bot scope must fail closed, including direct service/API callers.
- Customer support and payment verification must survive removal of old receivers.
- Foreign references to legacy bot IDs must block destructive cleanup.
- Fresh bootstrap twice must produce zero bots/credentials and retain valid Store/UOM/admin grants.
- All deploy paths must start Registry ASGI and expose only authenticated v2 webhook ingress.

## Task 1: Preserve and verify immediate Codespaces fix
- [ ] Finish production /bots browser and Server Action regression; record exact Origin rejection fix.
- [ ] Run full Next/Python suites, production build and current environment health.
- [ ] Commit separately before broad cleanup.

## Task 2: Schema, models and bootstrap
Files: db.py, models/*.py, migrations/, services/shop_multibot_bootstrap.py, services/shop_bot_operations_bootstrap.py, scripts/*bootstrap.py, tests/schema_support.py.
- [ ] Add failing tests: fresh metadata excludes original 15 tables; bootstrap is idempotent with zero bots.
- [ ] Remove old model modules, SQLAdmin classes, implicit bot defaults; seed Store/UOM/grants only.
- [ ] Make historical revisions self-contained and provide explicit guarded old-table cleanup without CASCADE.
- [ ] Verify preservation/foreign-reference failure tests and fresh PostgreSQL.

## Task 3: Explicit scope in shared commerce
Files: retained services/shop_identity.py, shop_cart.py, shop_orders.py, shop_payments.py, shop_wallet.py, shop_refunds.py, shop_referrals.py, shop_identity_links.py, shop_channel_features.py, shop_payment_rails.py, shop_media_delivery.py, shop_updates.py, shop_broadcast_rate.py, shop_engagement_flow.py, shop_channel_catalog.py, models/shop_scope.py.
- [ ] Add missing/wrong bot scope regressions.
- [ ] Replace platform fallback with explicit authenticated Registry context; preserve existing receipts and provider verification.
- [ ] Update modern fixtures/callers and run commerce/security suites.

## Task 4: Runtime, messaging and credentials
Files: services/shop_runtime/, shop_bot_context.py, shop_bot_operations.py, shop_bot_secrets.py, shop_multibot_client.py, shop_bot_verification.py, shop_broadcast*.py, shop_campaigns.py, workers/, services/bale_wallet.py, services/shop_bale_payments.py.
- [ ] Add Registry-only credential/broadcast/runtime tests; retain durable support/payment assertions.
- [ ] Remove old receiver ownership, profile inheritance, Legacy ingress and execution fallback.
- [ ] Preserve explicit Registry receipts, idempotency, independent Bale inquiry and tenant boundaries.
- [ ] Run focused Runtime/Registry/broadcast tests.

## Task 5: Dashboard/API and operational removal
Files: dashboard/, dashboard-next/, Dockerfiles, compose files, deploy/, config.py, utils/utils.py, old roots/trees and docs.
- [ ] Remove SQLAdmin and old global profile/connection controls; adapt bot/campaign/runtime UI to Registry-only contracts.
- [ ] Delete original handlers/repositories/crypto and related services/tests; retain shared modern transport/password helpers.
- [ ] Deploy Registry ASGI, v2-only webhook gateway; remove obsolete dependencies/secrets/prompts and write current installation docs.
- [ ] Verify retired routes 404 and modern routes/CSRF remain enforced.

## Final acceptance
- [ ] Full Python and Next suites; Typecheck/Lint/Build.
- [ ] Fresh PostgreSQL bootstrap, guarded cleanup/preservation and competing workers.
- [ ] Authenticated production /bots, bot draft/settings/receiver flows, both themes/mobile and no runtime/console errors with Fake Providers.
- [ ] Whole-branch review and fix/retest; record PASS/FAIL/BLOCKED and keep Draft.
