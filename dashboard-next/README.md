# Next.js dashboard — Telegram + Bale

This is the **new**, separate Persian/RTL dashboard workspace. It lives on
`feat/nextjs-rtl-dashboard-20261103`, branched from the complete Python bot
development branch. It **does not replace or migrate SQLAdmin automatically**.

## Stack

- Next.js App Router + TypeScript, React 19, Tailwind CSS v4.
- shadcn/ui-compatible **dashboard-01 / sidebar-07 / login-01** block
  composition. Native UI primitives live in `components/ui`; individual
  blocks are in `components/blocks`. `components.json` sets `rtl: true`.
- `Vazirmatn Variable` bundled by Fontsource, no build-time Google font
  network request.
- Persian `fa` RTL, optional Dark Mode, responsive sidebar and semantic data
  tables. Payments and numeric SKU/IDs preserve LTR where appropriate.
- FastAPI remains the **single authority** for database access, staff roles,
  product validation, orders, wallet, and Broadcast.

## Authentication

The browser never sees `NEXT_ADMIN_BRIDGE_SECRET`. Next.js's signed,
HttpOnly, SameSite=Strict staff cookie stores only ID, session version and
expiry; every server-rendered page checks FastAPI `/auth/me`. Backend
credentials use the **existing Argon2 ShopStaff** accounts.

The FastAPI bridge requires HMAC-SHA256 over timestamp, method, route including
query, body hash, staff ID and session version; it also checks actual staff
`is_active` and `session_version` in PostgreSQL on each call. Login is
throttled in Redis. A role change or session revocation invalidates access.

Public Next.js routes comprise login/logout and **authenticated** upload/preview
handlers. All other data mutations use server actions. The upload handler
checks exact HTTPS Origin, signed staff identity, role and a hard 50.1 MB
request ceiling before forwarding byte-for-byte signed multipart to FastAPI.
Never put backend credentials in a `NEXT_PUBLIC_` setting.

## Optional CAPTCHA and CDN

The login supports Cloudflare Turnstile, Google reCAPTCHA v2 checkbox and
Google reCAPTCHA v3 (score-based), configured with server-only environment
variables. No provider is required by default, but enabling one requires
working keys and provider verification: errors fail closed. The existing
CSRF double-submit cookie and FastAPI credential throttling remain in place.

An optional HTTPS CDN can serve the build's immutable /_next/static assets.
Without NEXT_ADMIN_CDN_URL, Next.js serves them locally. Private media and
all authentication/API traffic remain same-origin and are NEVER public CDN
objects. See [deployment and security guide](../docs/ADMIN_CAPTCHA_CDN.fa.md).

Run the offline provider policy tests with npm run test:captcha (Node 22+).

## Local integration (after final approval)

1. Copy the root `.env.template` to the actual private `.env` and set
   `NEXT_ADMIN_BRIDGE_ENABLED=true` with a strong secret.
2. Create `dashboard-next/.env.local` from `.env.example`. Set
   `SHOP_FASTAPI_INTERNAL_URL=http://localhost:5000` for local dev and
   copy exactly the backend bridge secret into `NEXT_ADMIN_BRIDGE_SECRET`.
   Use a **different** 32+ character `NEXT_ADMIN_SESSION_SECRET`.
3. Configure `NEXT_ADMIN_PUBLIC_ORIGIN` to the exact admin HTTPS origin
   (such as `https://admin.example.com`, without trailing slash).
   At the ingress/proxy, allow a **50,100,000-byte** upload request body.
4. Generate and review `package-lock.json`, use `npm ci`, then
   `npm run typecheck`, `npm run lint`, `npm run build`, `npm run dev`.
5. Sign in with an account provisioned by
   `python scripts/manage_shop_staff.py add <username> --role superadmin`.
6. Test all CRUD, role isolation, session revocation and RTL behavior against
   an **isolated** PostgreSQL/Redis database; do not point a development UI
   at production.

`components.json` permits extending from the actual shadcn registry:

```bash
npx shadcn@latest add dashboard-01 sidebar-07
```

Do not overwrite this fork's adapted application blocks without reviewing
imports, Persian translations and existing access controls.

## Implemented screens

- /login — Argon2 staff login via signed BFF
- /dashboard — actual KPIs / channel comparison / order highlights
- /products and /products/[id]/edit — live product CRUD
- /categories — live category CRUD
- /orders — scoped orders, plus audited accept/reject of unpaid manual orders
- /customers — scoped, read-only customer identities
- /campaigns — draft creation, audited approval/start/pause/resume
- /campaigns/[id] — evidence/reconciliation, draft attachment upload,
  private preview, draft deletion, and guarded Bale private-chat preparation
- /reports — separate IRR, store credit and XTR
- /settings — editable welcome/FAQ/help/shop name and referral reward policy
- /shipping and /coupons — live merchant CRUD, exact IRR charges
- /media — bounded native upload, private preview, caption/order editing,
  approve/unpublish and delete-only-when-unpublished
- /reviews — native text/file upload, approval, revocation and deletion
- /finance — live store-credit ledger and capped/idempotent manual adjustments,
  provider-verified manual refunds, merchant-credit refunds and opt-in Stars API
- /staff — superadmin account creation, roles, disablement and password rotation

**Source migration scope:** the Next.js forms and corresponding signed Python
endpoints for uploads, moderation, financial cases, staff, manual order decisions
and referral settings are implemented. **They are not yet production accepted.**
Old Telegram legacy transaction history, migration/deployment and provider live
validation remain separate. Retain SQLAdmin as a tested fallback until the
entire new dashboard passes real integration and browser security QA.

## Deployment

Use the optional Compose profile `dashboard-next` after final acceptance.
One shared Node.js service serves all admin users; never one container/user.
The API remains on the private Docker network. Serve the Node.js service
behind an HTTPS-only Caddy/nginx admin hostname. Do **not** publicly
forward `/internal/admin/v1` without the HMAC protection.

The deployment profile and root `NEXT_ADMIN_BRIDGE_ENABLED` flag both
remain disabled by default. **No real bots, payments or migrations have run.**

Production hardening TODO: generate/review `package-lock.json` and use
`npm ci` before production; verify HMAC/session/login throttling,
full 10/50 MB multipart ingestion, permission/isolation, durable financial
cases, build/typecheck/lint, RTL browser QA and Content Security Policy with
the final reverse proxy. Added isolated regression source under
`tests/test_next_admin_operations_offline.py`; execution still pending.

## Operations endpoint and security design

```text
Browser (HTTPS, RTL, host-only staff cookie)
  -> Next.js Route Handler /api/admin/upload?target=...
     -> exact Origin + authenticated role + total body <=50.1 MB
     -> HMAC(SHA256 of the identical multipart bytes)
  -> FastAPI signed /internal/admin/v1/upload/{target}
     -> live ShopStaff RBAC + body limit + media signature detection
     -> private media file (0600) + database metadata (unpublished)
  -> Next.js authenticated /api/admin/preview/{kind}/{id}
     -> signed FastAPI FileResponse (no-store, sandbox, nosniff)

Sensitive Server Actions (orders, wallet, refund, staff, campaigns)
  -> signed Python bridge -> guarded existing services and audit records
```

**No direct browser-to-storage URLs, provider tokens, private file keys,
PostgreSQL credentials or merchant financial secrets.** The HMAC bridge is
opt-in, request-limited and checks each database staff role/version. No server
component should bypass the authoritative Python services.


## Telegram API outbound transport

The Bot Connections page now stages Direct / HTTP or SOCKS5 Proxy /
Cloudflare Worker routes, probes them with `getMe`, requires a fresh
password and MFA to activate, persists the encrypted verified settings in
PostgreSQL, and offers separate, explicit rollback staging. Outbound
configuration is independent of Webhook/getUpdates and Bale.
Only deployment-allowlisted destinations may receive the Telegram token.

See [the Persian admin transport runbook](../docs/TELEGRAM_TRANSPORT_DASHBOARD.fa.md).
This PR remains Draft until Codespaces Docker/PostgreSQL/Next.js/browser and
real-provider acceptance tests pass.


## Multi-Bot Management (P2, stacked Draft PR)

The admin menu has a new **Bots** entry (`/bots`) with paginated
Telegram/Bale registry, store/draft-bot creation, scoped details,
redacted credential receipts, provider `getMe` verification and
evidence-based per-bot health.

Legacy bots can independently be switched between Active, Maintenance,
Paused and Disabled. Ordinary Telegram updates pass through an Aiogram
outer middleware; Bale ordinary messages use their own gate; broadcasts
are not claimed for paused bots. Pending pre-checkouts, successful
payments and existing refund requests remain eligible for settlement.

New bots **remain draft and unconnected** until P4 introduces
bot-scoped dispatchers, identities, carts, wallets and payment receipts.
No new token is activated by simply saving it or passing `getMe`.

See [P2 management and acceptance checklist](../docs/planning/multibot/P2_BOT_MANAGEMENT.fa.md)
and [Multi-Bot roadmap](../docs/planning/multibot/IMPLEMENTATION_ORDER.fa.md).
