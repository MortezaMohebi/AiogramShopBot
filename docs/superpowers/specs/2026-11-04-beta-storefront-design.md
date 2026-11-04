# Beta Customer Experience P0–P6 — Telegram + Bale

**Approved product direction:** A single Store-owned backend and Next.js dashboard with Telegram/Bale adapters, six consistent customer Home actions and verified per-bot access. The user explicitly requested to implement without migration because the project is a disposable no-data Beta.

## Scope & decisions
- Reuse the existing PR #13 stack and update models directly for **fresh PostgreSQL installations**. Do not drop production or unverified existing data; the reset is an operator action with a hard Beta guard.
- One `Store` owns products, customer profiles, addresses, wishlist, order lifecycle, promotions, tickets, shipment records and preferences. Every `Bot` owns its provider credentials, customer chat identity, menu config and payment grants.
- Every incoming message must be authenticated by BotContext. Never infer Store from callback/text/platform user ID. Numeric user IDs may collide among bots.
- Distinguish Admin `StoreContext` from Bot `BotContext`. Admins may view multiple active Stores but may only mutate their single current Store; Bot users never acquire admin permissions.
- Telegram/Bale have a shared **semantic menu** and shared business flows; adapters translate `BotReply` into official API primitives. Existing legacy Telegram keyboard should be reconciled without breaking old purchasable orders.
- Product catalog/search only includes `published` AND `Product.store_id == Bot.store_id` AND bot ACL allow; default deny for registered bots. Same enforcement on stale callbacks, cart, checkout and deep links.
- Home buttons: **Shop, Search, Cart, Orders, Account, Support**. Their visibility is configurable for each Store/Bot, but no preference overrides security/capability checks.
- Search first uses existing shared Product field registry with a **customer allowlist** and a short chat FSM; no arbitrary SQL expressions from chat.
- Account: address book, wishlist, verified channel identity linking and consent preferences; no phone/name-based identity merges.
- Checkout mode: `manual` by default; `instant` is explicit Store opt-in. Telegram digital goods must be charged with XTR Stars; never use IRR Store Credit to bypass it. Bale Wallet uses IRR, separate from Store Credit. Mixed digital/physical carts remain fail-closed rather than generating a misleading invoice.
- Order tracking: Store-owned shipment/fulfillment events; only provider-confirmed payments release digital assets. Refund references remain attached to originating payment account and Bot.
- Tickets and customer support: Store-scoped, bot-scoped origin, customer authenticated; ticket comments append-only and auditable. No raw provider credentials in messages or exports.
- Notification/stock alerts: separate operational and marketing consent; opt-in per bot. Never send unsolicited marketing.
- Telegram: callback_data max 64 UTF-8 bytes; answerCallbackQuery; XTR digital sendInvoice provider token omitted; reply to pre_checkout_query in 10s; process successful_payment before fulfillment; /terms, /support, /paysupport.
- Bale: bot API `https://tapi.bale.ai`; inline/reply keyboards and callback answer; IRR wallet with precheckout and independent `inquireTransaction`; media limits and native Mini Apps only after signed initData verification.
- No automatic provider call or token activation from mere code deployment. Runtime feature flags default off until E2E acceptance.

## Screens and APIs
- Next.js: Bot menu editor/preview, per-Store checkout policy, Address/Customer pages, Orders fulfillment, Support Tickets, Notifications/Stock Alerts; existing Product/UoM/Payment/Store screens reused.
- Backend: Store/Bot menu config, customer search, user account, addresses, wishlist, ticket/fulfillment models, checkout policy, contact/consent management, administrative endpoints and read/write scopes.
- Shared `CustomerExperienceFlow` orchestrates new actions before existing `ShopEngagementFlow`/`ShopOrdersFlow`/`ShopCartFlow`/`CatalogFlow` with an explicit `handled/unhandled` contract.
- No migration scripts for P0-P6; fresh schema is generated from SQLAlchemy metadata in a disposable Beta instance. Legacy Alembic code remains untouched in the branch until a separate reviewed archival decision.

## Acceptance gates
1. P0: cross-Store catalog read & callback denied, registered bot default-deny, getUpdates never failovers, no data reset in an unverified database.
2. P1: Telegram/Bale Home identical by semantics, menu customization safe; Search cannot read unpublished/denied/cross-Store fields or product IDs.
3. P2: identical platform user IDs from two bots cannot read each other's addresses/wishlist; verified link opt-in behavior.
4. P3: Manual/Instant policy, invoice currency selection, immutable order/payment ownership, no duplicate charge or digital fiat bypass.
5. P4: support ticket authorization and delivery status event precedence; no digital release on precheckout-only.
6. P5: consent scoped to Bot, stock alerts opt-in and no retry after ambiguous send.
7. P6: executable Python unit/security tests, Next.js lint/typecheck/build, PostgreSQL fresh schema smoke, Telegram/Bale provider simulations, a complete six-menu customer E2E suite, regression tests of legacy payments.

**Not covered by scope:** production activation, destructive resets, shipping carrier API contracts not provided, digital license storage without secure media pipeline, arbitrary payment gateways, bulk movement of legacy credit, fractional Checkout without rational-quantity migration.

**Testing truth:** Current Codespace/Provider access is not available via connected tools. Each change must be committed as unverified if its tests cannot run; do not mark P0–P6 as completed until the prescribed gates pass.
