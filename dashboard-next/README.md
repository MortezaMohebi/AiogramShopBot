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

Public Next.js routes are limited to login/logout. All data mutations are
server actions, subjected to Next.js Origin checks and backend role validation.
Never put backend credentials in a `NEXT_PUBLIC_` setting.

## Local integration (after final approval)

1. Copy the root `.env.template` to the actual private `.env` and set
   `NEXT_ADMIN_BRIDGE_ENABLED=true` with a strong secret.
2. Create `dashboard-next/.env.local` from `.env.example`. Set
   `SHOP_FASTAPI_INTERNAL_URL=http://localhost:5000` for local dev and
   copy exactly the backend bridge secret into `NEXT_ADMIN_BRIDGE_SECRET`.
   Use a **different** 32+ character `NEXT_ADMIN_SESSION_SECRET`.
3. `npm install` from `dashboard-next`, then `npm run typecheck`,
   `npm run build`, `npm run dev`.
4. Sign in with an account provisioned by
   `python scripts/manage_shop_staff.py add <username> --role superadmin`.
5. Test all CRUD, role isolation, session revocation and RTL behavior against
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
- /orders, /customers — scoped, read-only operational tables
- /campaigns — draft creation, audited approval/start/pause/resume
- /campaigns/[id] — uncertain delivery evidence/reconciliation
- /reports — separate IRR, store credit and XTR
- /settings — mutable welcome/FAQ/help/shop name
- /shipping and /coupons — live merchant CRUD, exact IRR charges
- /media — read-only metadata, legacy private uploader fallback
- /reviews — read-only testimonial review queue
- /finance — read-only wallets and refund case metadata

**Intentional gradual replacement:** heavy 50 MB file upload, media moderation,
refund confirmation, sensitive merchant credit adjustments, staff provisioning,
old Telegram Legacy transaction history stay within
their existing guarded SQLAdmin/CLI pathways. Do not claim those features have
migrated until complete BFF APIs and tests exist.

## Deployment

Use the optional Compose profile `dashboard-next` after final acceptance.
One shared Node.js service serves all admin users; never one container/user.
The API remains on the private Docker network. Serve the Node.js service
behind an HTTPS-only Caddy/nginx admin hostname. Do **not** publicly
forward `/internal/admin/v1` without the HMAC protection.

The deployment profile and root `NEXT_ADMIN_BRIDGE_ENABLED` flag both
remain disabled by default. **No real bots, payments or migrations have run.**

Production hardening TODO: generate/review `package-lock.json` and use
`npm ci` before production; verify HMAC/session and login throttling in
integration tests, role penetration tests, build/typecheck, RTL browser QA
and Content Security Policy with the final reverse proxy.
