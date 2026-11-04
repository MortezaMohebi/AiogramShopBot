# Beta storefront P0–P6 — implementation and acceptance handoff

**Branch:** `feat/beta-customer-experience-p0-p6-20261104`, based on PR #13.
**State:** Changes committed, **all local/test/provider gates unverified** in this session.

## Why no Alembic for this Beta

The user confirmed there is no business data worth migrating. **No new
Alembic revision** was authored for P0–P6. The pre-existing deployment
compatibility/migration files are preserved, not deleted, to avoid irreversible
changes on unknown databases.

For a disposable, verified-empty `shop_codespace` PostgreSQL database,
the existing locked fresh-schema `scripts.codespace_bootstrap` creates tables
from `Base.metadata` and `scripts.security_bootstrap` performs safe
idempotent setup: default Store, legacy Bot registrations, Store-owned
base UoMs, and an explicit manager membership for the freshly created admin.

These scripts **reject a database with unknown/partial tables or Alembic
revisions**. They do NOT delete rows, drop tables, reassign Payment Accounts
or erase a volume. If a previous Beta database is populated, backup and
review before a separate explicit reset; never point these commands at
Production.

## Delivered source by phase

| Phase | Source work | Acceptance |
|---|---|---|
| P0 | Product Store guard in correlated ACL, cross-Store target rejection, nondefault Store receiver/relay enrollment, remove getUpdates failover | **Not tested in Codespace** |
| P1 | Declarative Store/Bot six-button Menu Policy, dynamic Home, field-scoped Persian product search with private per-Bot FSM; Next.js Menu Builder | **Not E2E tested** |
| P2 | StoreCustomer address book, Wishlist, verified Contact, original ownership for linked historical Orders/Tickets; account and customer dashboard | **Not E2E tested** |
| P3 | Explicit Manual/Instant policy, seller terms snapshot, Stars-only digital product flow, frozen XTR order amounts and INR/Rial guardrails | **Provider tests pending** |
| P4 | Store-owned ticket/message and physical fulfillment events; staff tickets and shipping console; digital delivery **fail-closed** until secure media handoff exists | **Digital asset pipeline pending** |
| P5 | Bot-scoped consent and stock alerts, durable outbox, periodic staging, opt-in independent Telegram/Bale worker, no replay after uncertain provider send | **Worker disabled; transport E2E pending** |
| P6 | Legacy and Registry dispatch share six-menu semantic flow, Telegram UX callback routing and native Contact keyboard, Bale Contact support, chat FSM cleanup | **Legacy and Registry E2E pending** |

## Steps to run in a real Codespace

1. Ensure the correct repository branch, Python and Node dependencies are
   installed and environment guard is a *disposable Codespace*. Do not
   activate real credentials until approvals.
2. Run `bash scripts/beta_storefront_acceptance.sh`. Inspect *every*
   failure instead of skipping or changing the expected test outputs.
3. Create an empty `shop_codespace` database. With the existing guard
   variables and a strong `LIVE_ADMIN_PASSWORD`, run the repository's
   normal fresh-schema/bootstrap operation. Confirm no Alembic changes.
4. Run `python3 -m scripts.codespace_dashboard_probe`; verify Console
   auth, current Store, two active Store selections, and frontend rendering.
5. Execute a seeded Telegram and Bale fake-Provider E2E matrix:
   - /start and six Home actions in both platforms.
   - Search: Farsi name/SKU, empty term, paging, hidden Product, stale
     callback, cross-Store Product ID, same numeric customer ID in two Bots.
   - Account: share Contact from owner versus forwarded third-party
     Contact, address save/choose/remove, wishlist, cross-Bot link and
     historical paid-order/ticket visibility.
   - Cart: no-stock, disabled Bot ACL, shared Cart, coupon, address/ship,
     manual review, instant approval, changed terms, stale revision.
   - Telegram digital: `XTR` only, exact frozen order Stars, no Fiat or
     IRR credit, no mixed digital/physical cart, no invoice duplicate.
   - Bale: wallet IRR, provider token owned by correct Bot, precheckout
     deadline, successful_payment + independently verified
     `inquireTransaction`, replay/timeout and refund checks.
   - Tickets: create/respond, linked account history, Store isolation,
     Bot source, Outbox notification.
   - Physical paid Order: processing → ready → shipped (carrier + code)
     → delivered, reject unpaid/out-of-order.
   - Digital paid Order: do **not** mark delivered before a verified
     file/license transfer.
   - Advertising consent per Bot, stock subscribe/cancel while queued,
     worker crash after claimed-before-provider, ambiguous outbound
     response quarantined instead of resent.
6. Check cloud relay failover, webhook verification, per-Bot Receiver lease,
   rate limits, Bounce/Timeout behavior and media size caps per provider.
7. Request independent security/code review. Keep PR **Draft** until
   PostgreSQL + provider tests and admin UI build pass.

## Risk/known gaps

- Real Codespace commands, tests, migrations/fresh-schema smoke and provider
  E2E were **not runnable via the connected GitHub tool** in this session.
- Telegram/Bale live credentials, invoices, notifications, webhook activation
  and campaign sending were **not used** by this work.
- Secure digital file/license fulfillment is deliberately **not falsely
  marked complete**. It requires a verified post-payment artifact transfer
  with a durable receipt.
- New SQLAlchemy tables are meant for an **empty Beta schema**, not as an
  additive in-place change on databases already containing Shop data.
- Mixed physical/digital Telegram carts must be split into separate
  checkouts; they currently fail closed and require manual separation by
  the customer, rather than doing an automatic split.
- Provider-visible status, secrets, logs and financial outcomes must be
  audited before enabling `SHOP_CUSTOMER_NOTIFICATIONS_ENABLED` or any
  runtime rollout flag.

**Completion rule:** A GitHub commit or Draft PR is evidence of source
changes, not of successful QA. The acceptance status stays pending until
there are actual command outputs and two-provider test records.
